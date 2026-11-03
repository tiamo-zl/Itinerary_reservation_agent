"""LLM-as-judge 校准：对比人工标签与 judge 输出。

数据集为 JSONL，每行包含：

    id, human_score (0-5), human_verdict (pass|fail), label_source,
    task: {task_id, status},
    values: {status, request, options, selected, policy_result, approval, summary}

默认使用 live 模型和 judge v1；输出一致率、混淆矩阵、fail
precision/recall、score MAE 和 quadratic weighted kappa。
"""

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from itinerary_agent.domain.models import CallContext, ModelTier
from itinerary_agent.infra.config import Settings
from itinerary_agent.model_gateway.gateway import OpenAIChatGateway
from itinerary_agent.model_gateway.prompts import default_prompt_registry
from itinerary_agent.workers.llm_judge import JUDGE_SCHEMA, build_judge_payload

DEFAULT_DATASET = Path("tests/eval/judge_calibration.jsonl")
DEFAULT_OUT = Path("docs/status/judge-calibration.md")


def load_cases(path: Path) -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        for key in ("id", "human_score", "human_verdict", "values"):
            if key not in case:
                raise ValueError(f"{path}:{lineno}: missing {key}")
        if case["id"] in seen:
            raise ValueError(f"{path}:{lineno}: duplicate id {case['id']}")
        seen.add(case["id"])
        score = int(case["human_score"])
        if not 0 <= score <= 5:
            raise ValueError(f"{path}:{lineno}: human_score out of range")
        if case["human_verdict"] not in {"pass", "fail"}:
            raise ValueError(f"{path}:{lineno}: invalid human_verdict")
        case["human_score"] = score
        case.setdefault("task", {"task_id": case["id"], "status": "COMPLETED"})
        case.setdefault("label_source", "unknown")
        cases.append(case)
    if not cases:
        raise ValueError(f"{path}: no cases")
    return cases


def _parse_judge_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
        text = text.strip()
    data = json.loads(text)
    score = int(data["score"])
    verdict = data["verdict"]
    if verdict not in {"pass", "fail"} or not 0 <= score <= 5:
        raise ValueError("judge returned invalid verdict/score")
    return {"score": score, "verdict": verdict,
            "reason": str(data.get("reason", ""))[:500]}


async def evaluate_cases(cases: list[dict], model, *,
                         prompt_version: str = "v1") -> list[dict]:
    registry = default_prompt_registry()
    template = registry.get("judge", prompt_version)
    results: list[dict] = []
    for case in cases:
        payload = build_judge_payload(case["task"], case["values"])
        ctx = CallContext(
            trace_id=f"calibration:{case['id']}",
            tenant_id="calibration",
            task_id=case["id"],
            purpose="judge",
            prompt_version=template.version,
        )
        messages = [
            {"role": "system", "content": template.text},
            {"role": "user", "content": json.dumps(
                payload, ensure_ascii=False
            )},
        ]
        row = {
            "id": case["id"],
            "human_score": case["human_score"],
            "human_verdict": case["human_verdict"],
            "label_source": case["label_source"],
            "judge_score": None,
            "judge_verdict": None,
            "reason": "",
            "model": "",
            "provider": "",
            "error": None,
        }
        try:
            completion = await model.complete(
                ctx, messages, ModelTier.STANDARD,
                response_schema=JUDGE_SCHEMA,
            )
            data = _parse_judge_json(completion.text)
            row.update({
                "judge_score": data["score"],
                "judge_verdict": data["verdict"],
                "reason": data["reason"],
                "model": completion.model,
                "provider": completion.provider,
            })
        except Exception as exc:  # noqa: BLE001 - 单条失败不阻塞校准
            row["error"] = f"{type(exc).__name__}: {exc}"
        results.append(row)
    return results


def _quadratic_weighted_kappa(
    left: list[int], right: list[int], *, minimum: int = 0,
    maximum: int = 5,
) -> float | None:
    if not left or len(left) != len(right):
        return None
    size = maximum - minimum + 1
    observed = [[0] * size for _ in range(size)]
    for a, b in zip(left, right):
        observed[a - minimum][b - minimum] += 1
    row_sums = [sum(row) for row in observed]
    col_sums = [sum(observed[i][j] for i in range(size)) for j in range(size)]
    total = len(left)
    numerator = 0.0
    denominator = 0.0
    for i in range(size):
        for j in range(size):
            weight = ((i - j) ** 2) / ((size - 1) ** 2)
            expected = row_sums[i] * col_sums[j] / total
            numerator += weight * observed[i][j]
            denominator += weight * expected
    if denominator == 0:
        return None
    return 1.0 - numerator / denominator


def compute_metrics(results: list[dict]) -> dict:
    evaluated = [r for r in results if r["error"] is None]
    total = len(results)
    errors = total - len(evaluated)
    if not evaluated:
        return {
            "total": total, "evaluated": 0, "errors": errors,
            "agreement": None, "mae": None, "kappa": None,
            "confusion": {}, "fail_precision": None,
            "fail_recall": None, "fail_f1": None,
        }

    confusion = Counter(
        (r["human_verdict"], r["judge_verdict"]) for r in evaluated
    )
    agreement = sum(
        r["human_verdict"] == r["judge_verdict"] for r in evaluated
    ) / len(evaluated)
    mae = sum(
        abs(r["human_score"] - r["judge_score"]) for r in evaluated
    ) / len(evaluated)
    tp = confusion.get(("fail", "fail"), 0)
    fp = confusion.get(("pass", "fail"), 0)
    fn = confusion.get(("fail", "pass"), 0)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None
        and precision + recall > 0 else None
    )
    kappa = _quadratic_weighted_kappa(
        [r["human_score"] for r in evaluated],
        [r["judge_score"] for r in evaluated],
    )
    return {
        "total": total,
        "evaluated": len(evaluated),
        "errors": errors,
        "agreement": agreement,
        "mae": mae,
        "kappa": kappa,
        "confusion": {
            "human_pass_judge_pass": confusion.get(("pass", "pass"), 0),
            "human_pass_judge_fail": confusion.get(("pass", "fail"), 0),
            "human_fail_judge_pass": confusion.get(("fail", "pass"), 0),
            "human_fail_judge_fail": confusion.get(("fail", "fail"), 0),
        },
        "fail_precision": precision,
        "fail_recall": recall,
        "fail_f1": f1,
    }


def render_markdown(cases: list[dict], results: list[dict],
                    metrics: dict, *, dataset: Path,
                    prompt_version: str) -> str:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    models = sorted({
        f"{r['provider']}/{r['model']}" for r in results
        if r["error"] is None and r["model"]
    })
    labels = Counter(c["label_source"] for c in cases)
    lines = [
        "# LLM-as-judge 校准报告",
        "",
        f"- 时间：{now}",
        f"- 数据集：`{dataset}`",
        f"- 用例数：{metrics['total']}",
        f"- 标签来源：{dict(labels)}",
        f"- prompt：judge {prompt_version}",
        f"- 模型：{', '.join(models) or 'n/a'}",
        "",
        "## 指标",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 有效评审 | {metrics['evaluated']}/{metrics['total']} |",
        f"| verdict 一致率 | {_fmt(metrics['agreement'])} |",
        f"| score MAE | {_fmt(metrics['mae'])} |",
        f"| quadratic weighted kappa | {_fmt(metrics['kappa'])} |",
        f"| fail precision | {_fmt(metrics['fail_precision'])} |",
        f"| fail recall | {_fmt(metrics['fail_recall'])} |",
        f"| fail F1 | {_fmt(metrics['fail_f1'])} |",
        "",
        "## 混淆矩阵",
        "",
        "| 人工 \\ judge | pass | fail |",
        "|---|---|---|",
        (f"| pass | {metrics['confusion'].get('human_pass_judge_pass', 0)} | "
         f"{metrics['confusion'].get('human_pass_judge_fail', 0)} |"),
        (f"| fail | {metrics['confusion'].get('human_fail_judge_pass', 0)} | "
         f"{metrics['confusion'].get('human_fail_judge_fail', 0)} |"),
        "",
        "## 逐条结果",
        "",
        "| case | 人工 | judge | 一致 | 理由 / 错误 |",
        "|---|---|---|---|---|",
    ]
    for row in results:
        human = f"{row['human_verdict']}/{row['human_score']}"
        if row["error"]:
            judge = "error"
            same = "-"
            detail = row["error"]
        else:
            judge = f"{row['judge_verdict']}/{row['judge_score']}"
            same = "yes" if row["human_verdict"] == row["judge_verdict"] else "no"
            detail = row["reason"]
        lines.append(
            f"| {row['id']} | {human} | {judge} | {same} | "
            f"{detail.replace('|', '/')} |"
        )
    lines.extend([
        "",
        "> 当前标签为 seeded 基线；正式校准前应替换为人工标注。",
        "",
    ])
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LLM judge calibration")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-under-agreement", type=float, default=None)
    parser.add_argument("--fail-under-kappa", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = load_cases(args.dataset)
    settings = Settings()
    if settings.model_mode != "live":
        print("judge calibration requires MODEL_MODE=live", file=sys.stderr)
        return 2
    if not settings.deepseek_api_key:
        print("DEEPSEEK_API_KEY is required for judge calibration",
              file=sys.stderr)
        return 2
    model = OpenAIChatGateway(settings)
    results = asyncio.run(evaluate_cases(
        cases, model, prompt_version=args.prompt_version
    ))
    metrics = compute_metrics(results)
    report = {
        "dataset": str(args.dataset),
        "prompt_version": args.prompt_version,
        "metrics": metrics,
        "results": results,
    }
    markdown = render_markdown(
        cases, results, metrics, dataset=args.dataset,
        prompt_version=args.prompt_version,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(markdown)
        print(f"\nwritten to {args.out}")
    if metrics["evaluated"] == 0:
        return 2
    if (args.fail_under_agreement is not None
            and (metrics["agreement"] or 0) < args.fail_under_agreement):
        return 1
    if (args.fail_under_kappa is not None
            and (metrics["kappa"] or 0) < args.fail_under_kappa):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
