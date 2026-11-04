"""生成 judge 质量运营报告。

一次产出三部分，全部是只读聚合：

1. 工具报告：judge 配置、在线结果、复核队列、judge 调用成本；
2. 数据集报告：校准集规模、标签分布、字段完整度、ID 一致性；
3. 校准报告：读取 judge-calibrate 产出的 JSON，汇总一致率与门禁。

用法：

    python -m itinerary_agent.eval.judge_report
    python -m itinerary_agent.eval.judge_report --out /tmp/judge-report.md
"""

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.infra.repositories import (
    PostgresJudgeRepository,
    PostgresModelCallRepository,
)

DEFAULT_DATASET = Path("tests/eval/judge_calibration_50.jsonl")
DEFAULT_HUMAN = Path("tests/eval/judge_calibration_human.jsonl")
DEFAULT_CALIBRATION = Path("docs/status/judge-calibration-human.json")
DEFAULT_OUT = Path("docs/status/judge-report.md")

REQUEST_FIELDS = (
    "destination_city", "origin_city", "start_date", "end_date",
    "budget_limit", "hotel_area", "cabin", "need_flight", "need_hotel",
)


def _read_rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _dataset_stats(path: Path) -> dict | None:
    if not path.exists():
        return None
    rows = _read_rows(path)
    ids = [row["id"] for row in rows]
    values = [row.get("values") or {} for row in rows]
    requests = [value.get("request") or {} for value in values]
    labels = Counter(
        row.get("human_verdict") or "unlabeled" for row in rows
    )
    prefix_mismatch = [
        row["id"] for row in rows
        if row.get("human_verdict")
        and not row["id"].startswith(row["human_verdict"])
    ]
    return {
        "path": str(path),
        "sha256": _sha256(path),
        "total": len(rows),
        "labels": dict(labels),
        "sources": dict(Counter(
            row.get("label_source") or "unknown" for row in rows
        )),
        "duplicate_ids": sorted(
            value for value, count in Counter(ids).items() if count > 1
        ),
        "prefix_mismatch": prefix_mismatch,
        "null_request_fields": {
            field: sum(1 for request in requests if request.get(field) is None)
            for field in REQUEST_FIELDS
        },
        "empty_options": sum(
            1 for value in values
            if not (value.get("options") or {}).get("flights")
            and not (value.get("options") or {}).get("hotels")
        ),
        "empty_selected": sum(1 for value in values if not value.get("selected")),
        "empty_summary": sum(1 for value in values if not value.get("summary")),
        "missing_policy": sum(
            1 for value in values if not value.get("policy_result")
        ),
        "missing_approval": sum(
            1 for value in values if not value.get("approval")
        ),
    }


def _fmt(value, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, (float, Decimal)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _tool_section(settings: Settings, db_summary: dict,
                  call_summary: dict, db_error: str | None) -> list[str]:
    lines = [
        "## 1. 工具报告",
        "",
        "### 配置",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| MODEL_MODE | {settings.model_mode} |",
        f"| JUDGE_ENABLED | {settings.judge_enabled} |",
        f"| judge prompt | {settings.judge_prompt_version} |",
        f"| sample rate | {settings.judge_sample_rate} |",
        f"| interval (s) | {settings.judge_interval_seconds} |",
        f"| lookback (min) | {settings.judge_lookback_minutes} |",
        f"| max tasks | {settings.judge_max_tasks} |",
        f"| primary provider | {settings.primary_provider_name} |",
        f"| standard model | {settings.model_standard} |",
        "",
        "### 在线结果与复核队列",
        "",
    ]
    if db_error:
        lines += [f"> 数据库不可用：{db_error}", ""]
    else:
        lines += [
            "| 指标 | 值 |",
            "|---|---|",
            f"| judge_results 总数 | {db_summary.get('total', 0)} |",
            f"| pass | {db_summary.get('pass', 0)} |",
            f"| fail | {db_summary.get('fail', 0)} |",
            f"| pending 复核 | {db_summary.get('pending', 0)} |",
            f"| reviewed | {db_summary.get('reviewed', 0)} |",
            f"| 平均分 | {_fmt(db_summary.get('avg_score'))} |",
            f"| 最近一次 | {db_summary.get('latest_at') or 'n/a'} |",
            "",
        ]
    lines += [
        "### judge 模型调用",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 调用数 | {call_summary.get('calls', 0)} |",
        f"| 成功 | {call_summary.get('ok', 0)} |",
        f"| 失败 | {call_summary.get('errors', 0)} |",
        f"| cache hits | {call_summary.get('cache_hits', 0)} |",
        f"| tokens | {call_summary.get('tokens', 0)} |",
        f"| cost (USD) | {_fmt(call_summary.get('cost_usd'))} |",
        f"| 平均延迟 (ms) | {_fmt(call_summary.get('avg_ms'), 1)} |",
        "",
    ]
    if (
        call_summary.get("calls", 0) > 0
        and call_summary.get("tokens", 0) > 0
        and not call_summary.get("cost_usd", 0)
    ):
        lines += [
            "> cost=0 但 tokens>0：检查 `config/pricing.yaml` 是否覆盖当前模型。",
            "",
        ]
    return lines


def _dataset_section(title: str, stats: dict | None) -> list[str]:
    if stats is None:
        return [f"### {title}", "", "数据集不存在。", ""]
    labels = ", ".join(
        f"{key}={value}" for key, value in sorted(stats["labels"].items())
    )
    sources = ", ".join(
        f"{key}={value}" for key, value in sorted(stats["sources"].items())
    )
    null_fields = ", ".join(
        f"{key}={value}"
        for key, value in stats["null_request_fields"].items()
        if value
    ) or "无"
    return [
        f"### {title}",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 路径 | `{stats['path']}` |",
        f"| SHA-256 前缀 | `{stats['sha256']}` |",
        f"| 用例数 | {stats['total']} |",
        f"| 标签分布 | {labels} |",
        f"| 标签来源 | {sources} |",
        f"| 重复 ID | {', '.join(stats['duplicate_ids']) or '无'} |",
        f"| ID 前缀与标签不一致 | {', '.join(stats['prefix_mismatch']) or '无'} |",
        f"| request 空字段 | {null_fields} |",
        f"| options 全空 | {stats['empty_options']} |",
        f"| selected 为空 | {stats['empty_selected']} |",
        f"| summary 为空 | {stats['empty_summary']} |",
        f"| 缺 policy_result | {stats['missing_policy']} |",
        f"| 缺 approval | {stats['missing_approval']} |",
        "",
    ]


def _calibration_section(path: Path) -> list[str]:
    if not path.exists():
        return [
            "## 3. 校准报告",
            "",
            f"未找到 `{path}`。先运行：",
            "",
            "```bash",
            "make judge-calibrate-human",
            "```",
            "",
        ]
    report = json.loads(path.read_text(encoding="utf-8"))
    metrics = report.get("metrics") or {}
    confusion = metrics.get("confusion") or {}
    agreement = metrics.get("agreement")
    kappa = metrics.get("kappa")
    gate = (
        "pass" if (agreement or 0) >= 0.85 and (kappa or 0) >= 0.6
        else "not met"
    )
    return [
        "## 3. 校准报告",
        "",
        f"- 数据集：`{report.get('dataset')}`",
        f"- 标签来源：{report.get('label_source')}",
        f"- prompt：judge {report.get('prompt_version')}",
        f"- 生成时间：{report.get('generated_at', 'n/a')}",
        f"- 参考门禁（agreement≥0.85, kappa≥0.6）：**{gate}**",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 有效评审 | {metrics.get('evaluated')}/{metrics.get('total')} |",
        f"| verdict 一致率 | {_fmt(agreement)} |",
        f"| score MAE | {_fmt(metrics.get('mae'))} |",
        f"| weighted kappa | {_fmt(kappa)} |",
        f"| fail precision | {_fmt(metrics.get('fail_precision'))} |",
        f"| fail recall | {_fmt(metrics.get('fail_recall'))} |",
        f"| fail F1 | {_fmt(metrics.get('fail_f1'))} |",
        "",
        "| 人工 \\ judge | pass | fail |",
        "|---|---|---|",
        (f"| pass | {confusion.get('human_pass_judge_pass', 0)} | "
         f"{confusion.get('human_pass_judge_fail', 0)} |"),
        (f"| fail | {confusion.get('human_fail_judge_pass', 0)} | "
         f"{confusion.get('human_fail_judge_fail', 0)} |"),
        "",
    ]


async def _load_db_summary(settings: Settings) -> tuple[dict, dict, str | None]:
    db = Database(settings.database_url)
    try:
        await db.connect()
        judge = await PostgresJudgeRepository(db).report_summary()
        calls = await PostgresModelCallRepository(db).purpose_summary("judge")
        return judge, calls, None
    except Exception as exc:  # noqa: BLE001 - 报告不应因 DB 故障中断
        return {}, {}, f"{type(exc).__name__}: {exc}"
    finally:
        await db.close()


async def _run(args) -> int:
    settings = Settings()
    db_summary, call_summary, db_error = await _load_db_summary(settings)
    lines = [
        "# LLM-as-judge 质量报告",
        "",
        f"- 生成时间：{datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- 数据集：`{args.dataset}`",
        "",
        *_tool_section(settings, db_summary, call_summary, db_error),
        "## 2. 数据集报告",
        "",
        *_dataset_section("校准集", _dataset_stats(args.dataset)),
        *_dataset_section(
            "人工标签集", _dataset_stats(args.human_dataset)
        ),
        *_calibration_section(args.calibration_json),
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"written to {args.out}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Judge quality report")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--human-dataset", type=Path, default=DEFAULT_HUMAN)
    parser.add_argument(
        "--calibration-json", type=Path, default=DEFAULT_CALIBRATION
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
