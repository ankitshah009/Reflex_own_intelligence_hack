"""Bounded curriculum generation with real sandbox checks and fake cloud I/O.

Reference handlers are used only by the external-provider test double. Tests
verify that private checks/references never enter the actual model prompts.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import time

from fastapi.testclient import TestClient
import pytest

from reflex.app import create_app
from reflex.curriculum import generate_curriculum
from reflex.integrations.river import RiverOperationError, RiverResponseError
from reflex.repair_cases import held_out_cases
from reflex.repair_routes import source_fingerprint


BASE_MODEL = "Qwen/Qwen3.5-9B"


class FakeCurriculumProvider:
    """Cloud-only boundary with deterministic handlers and observed concurrency."""

    configured = True
    base_model = BASE_MODEL

    def __init__(self):
        self.calls = []
        self.training_calls = []
        self.reference_by_source = {}
        self.active = 0
        self.max_active = 0
        self.expected_parallel = 1
        self.arrived = None
        self.fail_on_call = None
        self.invalid_on_call = None
        self.return_original = False

    async def repair(self, prompt, checkpoint=None):
        self.calls.append({"prompt": prompt, "checkpoint": checkpoint})
        call_number = len(self.calls)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.arrived is None:
            self.arrived = asyncio.Event()
        if self.active >= self.expected_parallel:
            self.arrived.set()
        try:
            await asyncio.wait_for(self.arrived.wait(), timeout=5)
            await asyncio.sleep(0.02)
            if self.fail_on_call == call_number:
                raise RiverOperationError("Test transport lost contact; completion is unconfirmed.")
            if self.invalid_on_call == call_number:
                raise RiverResponseError("Test model returned malformed curriculum repair JSON.")
            visible = json.loads(prompt.split("WORKSPACE\n", 1)[1])
            code = visible["source"] if self.return_original else self.reference_by_source[visible["source"]]
            result = {"summary": "Fix event replay without duplicating state changes.", "code": code}
            return {
                **result, "raw": json.dumps(result), "model": self.base_model,
                "input_token_hash": hashlib.sha256(prompt.encode()).hexdigest(),
                "base_model": self.base_model, "tokenizer_revision": "test-only-tokenizer",
                "generation": {"temperature": 0.0, "seed": 42},
            }
        finally:
            self.active -= 1

    async def train(self, examples, *, name, method="sft", on_event=None):
        self.training_calls.append({"examples": deepcopy(examples), "name": name, "method": method})
        if on_event:
            await on_event({"type": "training_step", "step": 1, "loss": 1.0, "method": method})
        return {
            "checkpoint": f"river://test-only/sampler_weights/{name}",
            "model": self.base_model, "steps": 1,
            "metrics": {"method": method, "initial_loss": 1.0, "final_loss": 1.0},
        }


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("REFLEX_INGEST_TOKEN", raising=False)
    monkeypatch.setenv("RIVER_BASE_MODEL", BASE_MODEL)


@pytest.fixture
def provider():
    return FakeCurriculumProvider()


@pytest.fixture
def app(tmp_path, provider):
    application = create_app(str(tmp_path / "curriculum-api.sqlite3"), provider=provider)
    yield application
    application.state.store.close()


@pytest.fixture
def client(app):
    with TestClient(app) as session:
        yield session


def finish_job(client, response, *, expected="completed"):
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "interrupted"}:
            assert job["status"] == expected, job
            return job
        time.sleep(0.01)
    pytest.fail(f"Curriculum job {job_id} did not finish within thirty seconds")


def prepare_provider(provider, *, count, seed=42, concurrency=1):
    cases = generate_curriculum(count=count, seed=seed)
    provider.reference_by_source = {case["source"]: case["_reference_code"] for case in cases}
    provider.expected_parallel = concurrency
    return cases


def generate(client, *, count, concurrency=1, seed=42):
    return client.post("/api/curriculum/generate", json={
        "count": count, "concurrency": concurrency, "seed": seed,
    })


def machine_approved(row):
    return row.get("machine_feedback", {}).get("approved") is True


def test_bounded_generation_executes_real_checks_and_trains_only_machine_verified_rows(client, provider):
    cases = prepare_provider(provider, count=6, concurrency=3)
    job = finish_job(client, generate(client, count=6, concurrency=3))
    assert job["kind"] == "repair_curriculum"
    assert len(provider.calls) == 6
    assert provider.max_active == 3
    assert provider.active == 0
    state = client.get("/api/repairs/state").json()
    assert len(state["repairs"]) == 6
    assert {row["case_id"] for row in state["repairs"]} == {case["id"] for case in cases}
    for row in state["repairs"]:
        assert "human_feedback" not in row
        assert row["baseline_report"]["status"] == "failed"
        assert row["report"]["status"] == "passed"
        assert row["report"]["isolation"]["enforced"] is True
        expected_hash = hashlib.sha256(row["code"].encode()).hexdigest()
        assert row["accepted_report"]["code_hash"] == expected_hash
        feedback = row["machine_feedback"]
        assert feedback["approved"] is True
        assert feedback["source"] == "river_generated_execution_verified"
        assert feedback["curriculum_job_id"] == job["id"]
        assert row["job_id"] == job["id"]
        assert feedback["code"] == row["code"]
        assert feedback["code_hash"] == expected_hash

    held_out_sources = {source_fingerprint(case["source"]) for case in held_out_cases()}
    assert not held_out_sources.intersection(source_fingerprint(case["source"]) for case in cases)
    assert all(call["checkpoint"] is None for call in provider.calls)
    for call in provider.calls:
        assert all(key not in call["prompt"] for key in ("_checks", "_reference_code", "_generation"))
        assert all(case["_reference_code"] not in call["prompt"] for case in cases)
        assert all(case["id"] not in call["prompt"] for case in held_out_cases())
    assert "_checks" not in json.dumps(state["cases"])
    assert "_reference_code" not in json.dumps(state["cases"])

    exported = client.get("/api/repairs/export")
    assert exported.status_code == 200, exported.text
    examples = [json.loads(line) for line in exported.text.splitlines()]
    assert len(examples) == 6
    assert {row["experience_id"] for row in examples} == {row["id"] for row in state["repairs"]}
    checkpoint = finish_job(client, client.post("/api/repairs/train", json={"name": "curriculum-test-weights"}))["result"]
    assert checkpoint["example_count"] == 6
    assert checkpoint["task_kind"] == "repair"
    assert provider.training_calls == [{"examples": examples, "name": "curriculum-test-weights", "method": "sft"}]
    assert checkpoint["checkpoint"] == "river://test-only/sampler_weights/curriculum-test-weights"


def test_failed_generated_candidates_are_retained_and_never_trainable(client, provider):
    prepare_provider(provider, count=3, concurrency=2)
    provider.return_original = True
    finish_job(client, generate(client, count=3, concurrency=2))
    repairs = client.get("/api/repairs/state").json()["repairs"]
    assert len(repairs) == 3
    assert all(row["report"]["status"] != "passed" for row in repairs)
    assert all(not machine_approved(row) for row in repairs)
    assert all("human_feedback" not in row for row in repairs)
    assert client.get("/api/repairs/export").text == ""
    assert client.post("/api/repairs/train", json={"name": "must-not-train-failures"}).status_code == 422
    assert provider.training_calls == []
    assert len(provider.calls) == 3


def test_transport_error_stops_generation_without_retries_or_new_requests(client, provider):
    prepare_provider(provider, count=6)
    provider.fail_on_call = 2
    job = finish_job(client, generate(client, count=6), expected="failed")
    assert "transport" in job["error"].lower() or "unconfirmed" in job["error"].lower()
    assert len(provider.calls) == 2
    assert provider.max_active == 1
    assert provider.active == 0
    rows = client.get("/api/repairs/state").json()["repairs"]
    assert len(rows) == 2
    assert sum(machine_approved(row) for row in rows) == 1
    assert sum(row["report"]["status"] != "passed" for row in rows) == 1
    assert all("human_feedback" not in row for row in rows)
    assert len(client.get("/api/repairs/export").text.splitlines()) == 1


def test_malformed_completion_is_retained_and_other_cases_continue(client, provider):
    prepare_provider(provider, count=3)
    provider.invalid_on_call = 2
    finish_job(client, generate(client, count=3))
    assert len(provider.calls) == 3
    rows = client.get("/api/repairs/state").json()["repairs"]
    assert len(rows) == 3
    assert sum(machine_approved(row) for row in rows) == 2
    assert sum(row["report"]["status"] != "passed" for row in rows) == 1
    assert len(client.get("/api/repairs/export").text.splitlines()) == 2


@pytest.mark.parametrize("payload", [
    {"count": 0}, {"count": 25}, {"count": 1, "concurrency": 0},
    {"count": 1, "concurrency": 5}, {"count": 1, "seed": -1},
])
def test_generation_rejects_unbounded_requests_before_cloud_access(client, provider, payload):
    response = client.post("/api/curriculum/generate", json=payload)
    assert response.status_code == 422, response.text
    assert provider.calls == []
    assert client.get("/api/repairs/state").json()["repairs"] == []


def test_missing_provider_cannot_generate_a_fake_curriculum(client, provider):
    provider.configured = False
    response = generate(client, count=2)
    assert response.status_code == 503, response.text
    assert provider.calls == []
    state = client.get("/api/repairs/state").json()
    assert state["repairs"] == []
    assert state["checkpoints"] == []


@pytest.mark.parametrize("tamper", ["source", "job", "code_hash", "isolation", "agent_code"])
def test_machine_feedback_requires_exact_execution_and_curriculum_provenance(client, provider, app, tamper):
    prepare_provider(provider, count=2)
    finish_job(client, generate(client, count=2))
    row = deepcopy(client.get("/api/repairs/state").json()["repairs"][0])
    if tamper == "source":
        row["machine_feedback"]["source"] = "unverified-generated-label"
    elif tamper == "job":
        row["machine_feedback"]["curriculum_job_id"] = "missing-generation-job"
    elif tamper == "code_hash":
        row["accepted_report"]["code_hash"] = "0" * 64
    elif tamper == "isolation":
        row["accepted_report"]["isolation"]["enforced"] = False
    else:
        row["agent_code"] += "\n# Changed after model generation\n"
    app.state.store.save("repairs", row)
    response = client.get("/api/repairs/export")
    assert response.status_code == 422, (tamper, response.text)
    response = client.post("/api/repairs/train", json={"name": f"must-reject-{tamper}"})
    assert response.status_code == 422, (tamper, response.text)
    assert provider.training_calls == []
