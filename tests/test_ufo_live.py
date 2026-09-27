"""Offline checks for the live SDK runner's persistence and evidence binding."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ufo_live_runner", Path(__file__).parents[1] / "integrations/ufo/run_live_repair.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.mark.asyncio
async def test_store_is_durable_and_compare_and_swap_protects_updates(tmp_path):
    store = runner.JsonStore(tmp_path / "store.json")
    assert await store.get("turn") is None
    assert await store.put_if("turn", {"status": "reserved"}, None)
    assert not await store.put_if("turn", {"status": "changed"}, None)
    reopened = runner.JsonStore(tmp_path / "store.json")
    assert await reopened.get("turn") == {"status": "reserved"}
    assert await reopened.put_if("turn", {"exported": True}, {"status": "reserved"})
    assert await store.get("turn") == {"exported": True}
    await reopened.delete("turn")
    assert await store.get("turn") is None
    assert (tmp_path / "store.json").stat().st_mode & 0o777 == 0o600


def response():
    code = "def apply(state, event):\n    return state, None\n"
    return {
        "checkpoint": "river://real/sampler/checkpoint",
        "repair": {
            "condition": "learned",
            "code": code,
            "report": {
                "code_hash": hashlib.sha256(code.encode()).hexdigest(),
                "isolation": {"enforced": True},
                "status": "failed",
                "passed": 2,
                "total": 4,
            },
        },
    }


def test_failed_behavior_is_preserved_as_real_evidence():
    value = response()
    row = runner.validate_repair(value, value["checkpoint"])
    assert row["report"]["status"] == "failed"


@pytest.mark.parametrize("mutation", ["checkpoint", "code_hash", "isolation"])
def test_mismatched_evidence_is_rejected(mutation):
    value = response()
    expected = value["checkpoint"]
    if mutation == "checkpoint":
        value["checkpoint"] = None
    elif mutation == "code_hash":
        value["repair"]["report"]["code_hash"] = "wrong"
    else:
        value["repair"]["report"]["isolation"]["enforced"] = False
    with pytest.raises(RuntimeError):
        runner.validate_repair(value, expected)


def test_atomic_receipt_has_no_partial_json(tmp_path):
    path = tmp_path / "receipt.json"
    runner.write_json(path, {"source": runner.SOURCE, "full_agent_conversation": False})
    assert json.loads(path.read_text())["source"] == "programmatic SDK invocation"
    assert not list(tmp_path.glob("*.tmp"))
