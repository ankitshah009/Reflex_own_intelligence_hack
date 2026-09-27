"""Repair API checks with real case execution and only cloud I/O replaced.

Every test uses a temporary SQLite ledger. Fake model outputs and checkpoint
URIs are contract fixtures, never measurements of River performance.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from threading import Event
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from reflex.app import create_app
from reflex.integrations.river import RiverOperationError, RiverProvider, RiverResponseError
from reflex.integrations.ufo import UFO_SDK_COMMIT


BASE_MODEL = "Qwen/Qwen3.5-9B"
BUGGY_CODE = """def apply(state, event):
    state["balance"] += event["amount"]
    return {"balance": state["balance"]}
"""
FIXED_CODE = """def apply(state, event):
    if event["id"] not in state["seen"]:
        state["balance"] += event["amount"]
        state["seen"].append(event["id"])
    return {"balance": state["balance"]}
"""
RESERVE_BUG = """def apply(state, event):
    state["available"] -= event["quantity"]
    return {"reserved": True, "available": state["available"]}
"""
RESERVE_FIX = """def apply(state, event):
    if event["quantity"] > state["available"]:
        return {"reserved": False, "available": state["available"]}
    state["available"] -= event["quantity"]
    return {"reserved": True, "available": state["available"]}
"""


class FakeRepairProvider:
    """Replace River sampling/training while retaining the production API path."""

    configured = True
    base_model = BASE_MODEL

    def __init__(self):
        self.calls = []
        self.training_calls = []
        self.failure = None
        self.fail_on_call = None

    async def repair(self, prompt, checkpoint=None):
        self.calls.append({"prompt": prompt, "checkpoint": checkpoint})
        if self.failure is not None and (
            self.fail_on_call is None or len(self.calls) == self.fail_on_call
        ):
            raise self.failure
        response = {"summary": "Deduplicate repeated credits by event identity.", "code": FIXED_CODE}
        return {
            **response,
            "raw": json.dumps(response),
            "model": checkpoint or self.base_model,
            "base_model": self.base_model,
            "input_token_hash": hashlib.sha256(prompt.encode()).hexdigest(),
            "tokenizer_revision": "test-only-tokenizer",
            "generation": {"temperature": 0.0, "seed": 42},
        }

    async def train(self, examples, *, name, method="sft", on_event=None):
        self.training_calls.append({"examples": deepcopy(examples), "name": name, "method": method})
        if on_event:
            await on_event({"type": "training_step", "step": 1, "loss": 1.0, "method": method})
        return {
            "checkpoint": f"river://test-only/sampler_weights/{name}",
            "model": self.base_model,
            "steps": 1,
            "metrics": {"method": method, "initial_loss": 1.0, "final_loss": 1.0},
        }


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("REFLEX_INGEST_TOKEN", raising=False)
    monkeypatch.setenv("RIVER_BASE_MODEL", BASE_MODEL)


@pytest.fixture
def provider():
    return FakeRepairProvider()


@pytest.fixture
def app(tmp_path, provider):
    application = create_app(str(tmp_path / "repair-api.sqlite3"), provider=provider)
    yield application
    application.state.store.close()


@pytest.fixture
def client(app):
    with TestClient(app) as session:
        yield session


def finish_job(client, response, *, expected="completed"):
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "interrupted"}:
            assert job["status"] == expected, job
            return job
        time.sleep(0.01)
    pytest.fail(f"Repair job {job_id} did not finish within fifteen seconds")


def case_payload():
    return {
        "title": "Deduplicate credits in the isolated test ledger",
        "service": "credit-ledger",
        "description": "The same credit event can be delivered twice; count it once.",
        "source": BUGGY_CODE,
        "initial_state": {"balance": 0, "seen": []},
        "events": [{"id": "credit-1", "amount": 7}, {"id": "credit-1", "amount": 7}],
        "expected_state": {"balance": 7, "seen": ["credit-1"]},
        "expected_results": [{"balance": 7}, {"balance": 7}],
    }


def provenance():
    return {
        **{key: str(uuid4()) for key in ("workspace_id", "thread_id", "turn_id", "agent_id")},
        "sdk_commit": UFO_SDK_COMMIT,
    }


def reservation_case_payload():
    return {
        "title": "Reject an oversized isolated reservation",
        "service": "test-capacity",
        "description": "A reservation beyond available capacity leaves inventory unchanged.",
        "source": RESERVE_BUG,
        "initial_state": {"available": 3},
        "events": [{"quantity": 5}],
        "expected_state": {"available": 3},
        "expected_results": [{"reserved": False, "available": 3}],
    }


def create_case(client, payload=None):
    response = client.post("/api/repairs/cases", json=payload or case_payload())
    assert response.status_code == 201, response.text
    case = response.json()
    assert "_checks" not in case
    assert "expected_state" not in case
    assert "expected_results" not in case
    return case


def accept_repair(client, case, code):
    job = finish_job(client, client.post("/api/repairs/run", json={"case_id": case["id"], "code": code}))
    repair = job["result"]
    assert repair["report"]["status"] == "passed", repair["report"]
    assert repair["report"]["isolation"]["enforced"] is True
    response = client.post("/api/repairs/feedback", json={
        "repair_id": repair["id"], "code": code,
        "reason": "Confirmed by the isolated behavior checks and developer inspection.", "approved": True,
    })
    assert response.status_code == 200, response.text
    return response.json()


def accepted_dataset(client):
    first_case = create_case(client)
    second_case = create_case(client, reservation_case_payload())
    return [accept_repair(client, first_case, FIXED_CODE), accept_repair(client, second_case, RESERVE_FIX)]


def trained_checkpoint(client):
    accepted_dataset(client)
    return finish_job(client, client.post("/api/repairs/train", json={"name": "test-repair-weights"}))["result"]


def test_manual_reproduction_acceptance_training_and_held_out_replay(client, provider):
    initial = client.get("/api/repairs/state").json()
    assert initial["stats"] == {
        "attempts": 0,
        "accepted": 0,
        "checkpoints": 0,
        "eligible": 0,
        "machine_verified": 0,
    }
    assert initial["provider"]["verified"] is False
    assert "_checks" not in json.dumps(initial["cases"])
    assert "_reference_code" not in json.dumps(initial["cases"])
    case = create_case(client)
    original = client.post("/api/repairs/reproduce", json={"case_id": case["id"]})
    assert original.status_code == 200, original.text
    report = original.json()
    assert report["status"] == "failed", report
    assert report["passed"] < report["total"]
    assert report["preview"]["state"]["balance"] == 14
    assert report["isolation"]["enforced"] is True

    first = accept_repair(client, case, FIXED_CODE)
    second = accept_repair(client, create_case(client, reservation_case_payload()), RESERVE_FIX)
    assert provider.calls == []
    assert client.get("/api/repairs/state").json()["provider"]["verified"] is False
    assert first["baseline_report"]["status"] == "failed"
    assert first["report"]["preview"]["state"] == case_payload()["expected_state"]
    assert first["origin"] == "manual"
    assert "seen" in first["diff"]
    assert first["agent_code"] == FIXED_CODE
    assert first["accepted_report"]["status"] == "passed"
    exported = [json.loads(line) for line in client.get("/api/repairs/export").text.splitlines()]
    assert {row["experience_id"] for row in exported} == {first["id"], second["id"]}
    assert {json.loads(row["completion"])["code"] for row in exported} == {FIXED_CODE, RESERVE_FIX}

    checkpoint = finish_job(client, client.post("/api/repairs/train", json={"name": "test-repair-weights"}))["result"]
    assert checkpoint["task_kind"] == "repair"
    assert checkpoint["example_count"] == 2
    assert checkpoint["method"] == "sft"
    assert provider.training_calls == [{"examples": exported, "name": "test-repair-weights", "method": "sft"}]
    assert checkpoint["checkpoint"] == "river://test-only/sampler_weights/test-repair-weights"
    assert "accuracy" not in checkpoint["metrics"]
    assert client.post("/api/repairs/train", json={"name": "test-repair-weights"}).status_code == 409

    evaluation = finish_job(client, client.post("/api/repairs/evaluate", json={"checkpoint": checkpoint["id"]}))["result"]
    assert evaluation["status"] == "completed"
    assert evaluation["matched_prompts"] is True
    assert evaluation["dataset_hash"] == checkpoint["dataset_hash"]
    assert [condition["name"] for condition in evaluation["conditions"]] == ["base", "memory", "learned"]
    base, memory, learned = evaluation["conditions"]
    count = evaluation["case_count"]
    assert count > 0
    assert all(condition["total"] == count for condition in evaluation["conditions"])
    assert all(condition["success_rate"] == condition["passed"] / count for condition in evaluation["conditions"])
    assert [row["prompt_hash"] for row in memory["results"]] == [row["prompt_hash"] for row in learned["results"]]
    assert [row["prompt_hash"] for row in base["results"]] != [row["prompt_hash"] for row in memory["results"]]
    assert len(provider.calls) == 3 * count
    assert [call["prompt"] for call in provider.calls[count:2 * count]] == [call["prompt"] for call in provider.calls[2 * count:]]
    assert all(call["checkpoint"] is None for call in provider.calls[:2 * count])
    assert all(call["checkpoint"] == checkpoint["checkpoint"] for call in provider.calls[2 * count:])
    assert all("_checks" not in call["prompt"] and "_reference_code" not in call["prompt"] for call in provider.calls)
    assert client.get("/api/repairs/state").json()["stats"]["attempts"] == 2


def test_failed_or_unapproved_candidate_cannot_train(client, provider):
    case = create_case(client)
    repair = finish_job(client, client.post("/api/repairs/run", json={"case_id": case["id"], "code": BUGGY_CODE}))["result"]
    assert repair["report"]["status"] == "failed"
    rejected = client.post("/api/repairs/feedback", json={
        "repair_id": repair["id"], "code": BUGGY_CODE, "reason": "Try to accept a failing patch", "approved": True,
    })
    assert rejected.status_code == 422
    assert "does not pass" in rejected.json()["detail"]
    assert client.get("/api/repairs/export").text == ""
    assert client.post("/api/repairs/train", json={"name": "must-not-train"}).status_code == 422
    response = client.post("/api/repairs/feedback", json={
        "repair_id": repair["id"], "code": FIXED_CODE, "reason": "Passing but not accepted yet", "approved": False,
    })
    assert response.status_code == 200
    assert response.json()["report"]["status"] == "passed"
    assert client.get("/api/repairs/export").text == ""
    assert provider.training_calls == []


def test_renamed_held_out_source_cannot_become_custom_training_case(client, provider):
    from reflex.repair_cases import held_out_cases

    held_out = held_out_cases()[0]
    payload = case_payload()
    payload.update(title="New title cannot hide held-out source", service="changed-service", source="# Renamed submission\n" + held_out["source"])
    response = client.post("/api/repairs/cases", json=payload)
    assert response.status_code == 422, response.text
    assert "held-out" in response.json()["detail"]
    assert provider.calls == []
    assert client.get("/api/repairs/state").json()["repairs"] == []


def test_checkpoint_snapshot_and_evaluation_memory_survive_feedback_mutation(client, provider):
    checkpoint = trained_checkpoint(client)
    endpoint = f"/api/datasets/{checkpoint['dataset_hash']}/export"
    before = client.get(endpoint)
    assert before.status_code == 200, before.text
    examples = [json.loads(line) for line in before.text.splitlines()]
    first = examples[0]
    code = json.loads(first["completion"])["code"]
    response = client.post("/api/repairs/feedback", json={
        "repair_id": first["experience_id"], "code": code,
        "reason": "LATER_REPAIR_FEEDBACK_SENTINEL", "approved": True,
    })
    assert response.status_code == 200, response.text
    assert "LATER_REPAIR_FEEDBACK_SENTINEL" in client.get("/api/repairs/export").text
    assert client.get(endpoint).text == before.text
    finish_job(client, client.post("/api/repairs/evaluate", json={"checkpoint": checkpoint["id"]}))
    assert all("LATER_REPAIR_FEEDBACK_SENTINEL" not in call["prompt"] for call in provider.calls)


def test_missing_provider_allows_manual_checks_but_never_fakes_training(tmp_path):
    application = create_app(str(tmp_path / "repair-offline.sqlite3"), provider=RiverProvider(api_key=""))
    with TestClient(application) as session:
        case = create_case(session)
        assert session.post("/api/repairs/run", json={"case_id": case["id"]}).status_code == 503
        saved = accept_repair(session, case, FIXED_CODE)
        assert saved["model"] == "manual"
        assert session.post("/api/repairs/train", json={"name": "offline"}).status_code == 503
        assert session.post("/api/repairs/evaluate", json={"checkpoint": "missing"}).status_code == 503
        state = session.get("/api/repairs/state").json()
        assert state["provider"] == {"configured": False, "model": BASE_MODEL, "verified": False}
        assert state["checkpoints"] == []
        assert state["evaluations"] == []
    application.state.store.close()


def test_malformed_repair_output_counts_as_failed_evaluation_attempt(client, provider):
    checkpoint = trained_checkpoint(client)
    provider.failure = RiverResponseError("River returned malformed repair JSON.")
    provider.fail_on_call = 1
    evaluation = finish_job(client, client.post("/api/repairs/evaluate", json={"checkpoint": checkpoint["id"]}))["result"]
    first = evaluation["conditions"][0]["results"][0]
    assert first["invalid_output"] is True
    assert first["report"]["status"] == "failed"
    assert "malformed" in first["error"]
    assert all(condition["total"] == evaluation["case_count"] for condition in evaluation["conditions"])
    assert len(provider.calls) == 3 * evaluation["case_count"]


def test_transport_failure_preserves_partial_repair_evaluation(client, provider):
    checkpoint = trained_checkpoint(client)
    provider.failure = RiverOperationError("Repair sampling timed out; completion is unknown.")
    provider.fail_on_call = 2
    job = finish_job(client, client.post("/api/repairs/evaluate", json={"checkpoint": checkpoint["id"]}), expected="failed")
    assert "timed out" in job["error"]
    artifact = client.get("/api/repairs/state").json()["evaluations"][0]
    assert artifact["status"] == "failed"
    assert artifact["matched_prompts"] is False
    assert artifact["conditions"][0]["total"] == 1
    assert len(artifact["conditions"][0]["results"]) == 1
    assert len(provider.calls) == 2


def test_learned_repair_requires_matching_saved_checkpoint(client, provider):
    case = create_case(client)
    response = client.post("/api/repairs/run", json={"case_id": case["id"], "condition": "learned"})
    assert response.status_code == 404
    checkpoint = trained_checkpoint(client)
    learned = finish_job(client, client.post("/api/repairs/run", json={
        "case_id": case["id"], "condition": "learned", "checkpoint": checkpoint["id"],
    }))["result"]
    assert learned["checkpoint"] == checkpoint["checkpoint"]
    assert learned["model"] == checkpoint["checkpoint"]
    assert provider.calls[-1]["checkpoint"] == checkpoint["checkpoint"]
    assert learned["report"]["status"] == "passed"
    provider.base_model = "different/base-model"
    assert client.post("/api/repairs/evaluate", json={"checkpoint": checkpoint["id"]}).status_code == 409


def test_ufo_repair_defaults_to_learned_and_retries_without_duplicate_cloud_calls(client, provider):
    checkpoint = trained_checkpoint(client)
    case = create_case(client)
    payload = {"case_id": case["id"], "provenance": provenance()}
    headers = {"Idempotency-Key": "test-repair-turn"}
    first = client.post("/api/repairer", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["checkpoint"] == checkpoint["checkpoint"]
    assert result["repair"]["condition"] == "learned"
    assert len(provider.calls) == 1
    provider.configured = False
    repeated = client.post("/api/repairer", json=payload, headers=headers)
    assert repeated.status_code == 200
    assert repeated.json() == result
    assert len(provider.calls) == 1
    conflicting = {**payload, "condition": "base"}
    assert client.post("/api/repairer", json=conflicting, headers=headers).status_code == 409
    state = client.get("/api/repairs/state").json()
    assert sum(row["id"] == result["experience_id"] for row in state["repairs"]) == 1


def test_ufo_repair_requires_auth_and_rejects_manual_approval_injection(client, provider, monkeypatch):
    case = create_case(client)
    payload = {"case_id": case["id"], "condition": "base", "provenance": provenance()}
    monkeypatch.setenv("REFLEX_INGEST_TOKEN", "test-repair-token")
    assert client.post("/api/repairer", json=payload).status_code == 401
    headers = {"Authorization": "Bearer test-repair-token"}
    assert client.post("/api/repairer", json=payload, headers=headers).status_code == 422
    headers["Idempotency-Key"] = "injection-turn"
    assert client.post("/api/repairer", json={**payload, "code": FIXED_CODE}, headers=headers).status_code == 422
    assert client.post("/api/repairs/run", json=payload).status_code == 422
    assert provider.calls == []


def test_ufo_trajectory_import_requires_saved_case_and_runtime_identity(client):
    case = create_case(client)
    runtime = provenance()
    result = client.post("/api/repairer", json={"case_id": case["id"], "condition": "base", "provenance": runtime}, headers={"Idempotency-Key": "import-repair-turn"})
    assert result.status_code == 200, result.text
    repair_id = result.json()["experience_id"]
    value = {
        "experience_id": repair_id, "case_id": case["id"], "source": "ufo", "ufo": runtime,
        "trajectory": [{"type": "instruction", "message": "Repair the duplicate event"}],
    }
    response = client.post("/api/repairs/import", json={"experience": value})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == repair_id
    assert response.json()["trajectory"] == value["trajectory"]
    different_identity = deepcopy(value)
    different_identity["ufo"]["turn_id"] = str(uuid4())
    assert client.post("/api/repairs/import", json={"experience": different_identity}).status_code == 409
    assert client.post("/api/repairs/import", json={"experience": {**value, "case_id": "not-the-original-case"}}).status_code == 409
    assert client.post("/api/repairs/import", json={"experience": {**value, "human_feedback": {"approved": True}}}).status_code == 422
    assert client.get("/api/repairs/export").text == ""


def test_redaction_cannot_change_executed_code_and_keep_a_passing_report(client, app):
    # Deliberately synthetic credential-shaped text: no real secret is used.
    credential_line = 'API_KEY = "synthetic-test-value-with-no-account"\n'
    altered_source = {**case_payload(), "source": credential_line + BUGGY_CODE}
    response = client.post("/api/repairs/cases", json=altered_source)
    assert response.status_code == 422, response.text

    case = create_case(client)
    accepted = accept_repair(client, case, FIXED_CODE)
    original_hash = hashlib.sha256(FIXED_CODE.encode()).hexdigest()
    assert accepted["accepted_report"]["code_hash"] == original_hash
    altered_candidate = credential_line + FIXED_CODE
    response = client.post("/api/repairs/feedback", json={
        "repair_id": accepted["id"], "code": altered_candidate,
        "reason": "Must not save a redacted version of the tested handler", "approved": True,
    })
    assert response.status_code == 422, response.text
    response = client.post("/api/repairs/run", json={"case_id": case["id"], "code": altered_candidate})
    assert response.status_code == 422, response.text
    persisted = next(row for row in client.get("/api/repairs/state").json()["repairs"] if row["id"] == accepted["id"])
    assert persisted["code"] == FIXED_CODE
    assert persisted["accepted_report"]["code_hash"] == original_hash
    assert persisted["human_feedback"]["code"] == FIXED_CODE

    # A historical inconsistent record cannot reuse a report for different code.
    persisted["human_feedback"]["code"] = FIXED_CODE + "\n# edited after execution\n"
    app.state.store.save("repairs", persisted)
    assert client.get("/api/repairs/export").status_code == 422
    assert client.post("/api/repairs/train", json={"name": "must-reverify"}).status_code == 422


def test_frozen_checkpoint_evaluation_survives_later_conflicting_approvals(client, provider):
    checkpoint = trained_checkpoint(client)
    snapshot_path = f"/api/datasets/{checkpoint['dataset_hash']}/export"
    snapshot = client.get(snapshot_path).text
    duplicate_case = create_case(client)
    alternative = FIXED_CODE + "\n# Equivalent repair accepted after checkpoint creation.\n"
    accept_repair(client, duplicate_case, alternative)
    # The current corpus needs conflict resolution, but an older frozen run is reproducible.
    assert client.get("/api/repairs/export").status_code == 422
    result = finish_job(client, client.post("/api/repairs/evaluate", json={"checkpoint": checkpoint["id"]}))["result"]
    assert result["status"] == "completed"
    assert result["matched_prompts"] is True
    assert result["dataset_hash"] == checkpoint["dataset_hash"]
    assert client.get(snapshot_path).text == snapshot
    assert all("Equivalent repair accepted after checkpoint creation" not in call["prompt"] for call in provider.calls)


def test_feedback_preserves_ufo_trace_imported_while_real_execution_is_awaited(client, monkeypatch):
    from reflex import repair_routes

    case = create_case(client)
    runtime = provenance()
    reviewed = client.post("/api/repairer", json={
        "case_id": case["id"], "condition": "base", "provenance": runtime,
    }, headers={"Idempotency-Key": "feedback-trace-race"})
    assert reviewed.status_code == 200, reviewed.text
    repair_id = reviewed.json()["experience_id"]
    entered, release = Event(), Event()
    execute_real_case = repair_routes.execute_case

    def synchronized_execution(case, code, events=None):
        # This adds scheduling only; the real OS sandbox still produces the report.
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("The test did not release the feedback execution barrier")
        return execute_real_case(case, code, events)

    monkeypatch.setattr(repair_routes, "execute_case", synchronized_execution)
    trace = [{"type": "answer", "message": "UFO final trace arrived during developer validation."}]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, "/api/repairs/feedback", json={
            "repair_id": repair_id, "code": FIXED_CODE,
            "reason": "Accepted after actual isolated execution", "approved": True,
        })
        try:
            assert entered.wait(timeout=5), "Feedback did not reach its asynchronous execution boundary"
            imported = client.post("/api/repairs/import", json={"experience": {
                "experience_id": repair_id, "case_id": case["id"], "source": "ufo",
                "ufo": runtime, "trajectory": trace,
            }})
            assert imported.status_code == 200, imported.text
        finally:
            release.set()
        saved = pending.result(timeout=10)
    assert saved.status_code == 200, saved.text
    assert saved.json()["accepted_report"]["status"] == "passed"
    assert saved.json()["accepted_report"]["isolation"]["enforced"] is True
    row = next(row for row in client.get("/api/repairs/state").json()["repairs"] if row["id"] == repair_id)
    assert row["trajectory"] == trace
    assert row["human_feedback"]["approved"] is True


def test_malformed_memory_output_without_token_hash_cannot_claim_matched_learning(client, provider):
    from reflex.repair_cases import held_out_cases

    checkpoint = trained_checkpoint(client)
    case_count = len(held_out_cases())
    provider.failure = RiverResponseError("Malformed Memory repair with no input-token metadata")
    provider.fail_on_call = case_count + 1
    job = finish_job(client, client.post("/api/repairs/evaluate", json={"checkpoint": checkpoint["id"]}), expected="failed")
    assert "provenance" in job["error"]
    artifact = client.get("/api/repairs/state").json()["evaluations"][0]
    assert artifact["status"] == "failed"
    assert artifact["matched_prompts"] is False
    memory = next(condition for condition in artifact["conditions"] if condition["name"] == "memory")
    assert memory["total"] == case_count
    assert memory["results"][0]["invalid_output"] is True
    assert memory["results"][0]["input_token_hash"] is None
    assert len(provider.calls) == 2 * case_count
    assert all(call["checkpoint"] is None for call in provider.calls)
