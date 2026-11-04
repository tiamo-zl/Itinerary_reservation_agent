"""离线 judge 人工标注流程。"""

import json
from pathlib import Path
from types import SimpleNamespace

from itinerary_agent.eval.judge_calibration import load_cases
from itinerary_agent.eval.judge_context import (
    CheckpointSnapshotReader,
    load_judge_context,
)
from itinerary_agent.eval.judge_labeling import _finalize
from tests.db_utils import open_test_db


def test_calibration_dataset_has_50_balanced_cases():
    cases = load_cases(Path("tests/eval/judge_calibration_50.jsonl"))
    assert len(cases) == 50
    labels = [case["human_verdict"] for case in cases]
    assert labels.count("pass") == 25
    assert labels.count("fail") == 25


async def test_checkpoint_reader_returns_latest_values():
    db = await open_test_db()
    thread_id = "judge-reader-test"
    await db.execute(
        "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
    )
    for checkpoint_id, summary in (("a", "old"), ("b", "new")):
        payload = {"channel_values": {"summary": summary, "status": "COMPLETED"}}
        await db.execute(
            "INSERT INTO checkpoints "
            "(thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata) "
            "VALUES (?, '', ?, ?::jsonb, '{}'::jsonb)",
            (thread_id, checkpoint_id, json.dumps(payload)),
        )

    reader = CheckpointSnapshotReader(db)
    snapshot = await reader.get_state_snapshot(thread_id)
    assert snapshot["values"]["summary"] == "new"
    await db.close()


async def test_load_judge_context_reuses_judge_payload():
    class FakeReader:
        async def get_state_snapshot(self, task_id):
            return {
                "values": {
                    "status": "COMPLETED",
                    "request": {"destination_city": "北京"},
                    "summary": "ok",
                },
                "next": [],
            }

    task = {"task_id": "t1", "status": "COMPLETED"}
    context = await load_judge_context(FakeReader(), task)  # type: ignore[arg-type]
    assert context is not None
    assert context["request"]["destination_city"] == "北京"
    assert context["summary"] == "ok"


def test_finalize_only_writes_labeled_rows(tmp_path):
    source = tmp_path / "labeling.jsonl"
    output = tmp_path / "human.jsonl"
    rows = [
        {
            "id": "a",
            "task": {"task_id": "a", "status": "COMPLETED"},
            "values": {"status": "COMPLETED"},
            "judge_score": 5,
            "judge_verdict": "pass",
            "judge_reason": "ok",
            "human_score": 5,
            "human_verdict": "pass",
            "comment": "",
            "reviewer": "tester",
        },
        {
            "id": "b",
            "task": {"task_id": "b", "status": "COMPLETED"},
            "values": {"status": "COMPLETED"},
            "judge_score": 2,
            "judge_verdict": "fail",
            "judge_reason": "bad",
            "human_score": None,
            "human_verdict": None,
            "comment": "",
        },
    ]
    source.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = _finalize(SimpleNamespace(infile=source, out=output))
    assert result == 0
    emitted = [
        json.loads(line)
        for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert len(emitted) == 1
    assert emitted[0]["id"] == "a"
    assert emitted[0]["label_source"] == "human"
    assert emitted[0]["reviewer"] == "tester"
