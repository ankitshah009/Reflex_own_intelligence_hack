"""Exercise Reflex's real API and SQLite ledger; fake only River cloud I/O.

All generated experiences and checkpoints live in pytest's temporary directory.
Fake results are test fixtures and are never product performance evidence.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from reflex.app import create_app
from reflex.fixtures import HELD_OUT_PRS
from reflex.integrations.river import RiverOperationError, RiverProvider, RiverResponseError
from reflex.integrations.ufo import UFO_SDK_COMMIT


BASE_MODEL = "Qwen/Qwen3.5-9B"
REVIEW = {
    "decision": "REJECT",
    "summary": "Catch a specific payment error and add a regression test.",
    "issues": [
        {"tag": "broad_exception", "severity": "high", "message": "Catch a specific error."},
        {
            "tag": "missing_regression_test",
            "severity": "medium",
            "message": "Cover the failure in a regression test.",
        },
    ],
}
FEEDBACK = {
    "decision": "REJECT",
    "reason": "The broad exception hides a payment failure; add a regression test.",
    "issues": ["broad_exception", "missing_regression_test"],
    "approved": True,
}


class FakeProvider:
    """Deterministic replacement for the remote inference and training boundary."""

    configured = True
    base_model = BASE_MODEL

    def __init__(self, *, review_failure=None, fail_on_call=None, training_failure=None):
        self.calls = []
        self.training_calls = []
        self.review_failure = review_failure
        self.fail_on_call = fail_on_call
        self.training_failure = training_failure

    async def review(self, prompt, checkpoint=None):
        self.calls.append({"prompt": prompt, "checkpoint": checkpoint})
        if self.review_failure and (
            self.fail_on_call is None or self.fail_on_call == len(self.calls)
        ):
            raise self.review_failure
        return {
            **deepcopy(REVIEW),
            "model": checkpoint or self.base_model,
            "input_token_hash": hashlib.sha256(prompt.encode()).hexdigest(),
        }

    async def train(self, examples, *, name, method="sft", on_event=None):
        self.training_calls.append({"examples": deepcopy(examples), "name": name, "method": method})
        if on_event:
            await on_event({"type": "training_step", "step": 1, "loss": 1.2, "method": method})
        if self.training_failure:
            raise self.training_failure
        return {
            "checkpoint": f"river://test-only/sampler_weights/{name}",
            "model": self.base_model,
            "steps": 1,
            "metrics": {"initial_loss": 1.2, "final_loss": 1.2, "examples": len(examples)},
        }


class CombinedTrainingProvider(FakeProvider):
    """Cloud contract with a confirmed SFT checkpoint before optional RL failure."""

    def __init__(self, *, fail_rl=False):
        super().__init__()
        self.fail_rl = fail_rl

    async def train(self, examples, *, name, method="sft", on_event=None):
        self.training_calls.append({"examples": deepcopy(examples), "name": name, "method": method})
        sft = {
            "checkpoint": f"river://test-only/sampler_weights/{name}-sft",
            "model": self.base_model,
            "steps": 1,
            "metrics": {
                "method": "sft",
                "sft_steps": 1,
                "rl_steps": 0,
                "rl_status": "not_requested",
                "examples": len(examples),
            },
        }
        await on_event({"type": "sft_checkpoint_saved", **sft})
        if self.fail_rl:
            raise RiverOperationError("RL backward failed; no RL optimizer update was confirmed.")
        await on_event({"type": "rl_step", "step": 1, "updated": True})
        return {
            "checkpoint": f"river://test-only/sampler_weights/{name}",
            "model": self.base_model,
            "steps": 2,
            "metrics": {
                "method": method,
                "sft_steps": 1,
                "rl_steps": 1,
                "rl_status": "updated",
                "examples": len(examples),
            },
        }


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("REFLEX_INGEST_TOKEN", raising=False)
    monkeypatch.setenv("RIVER_BASE_MODEL", BASE_MODEL)


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def app(tmp_path, provider):
    application = create_app(str(tmp_path / "reflex.sqlite3"), provider=provider)
    yield application
    application.state.store.close()


@pytest.fixture
def client(app):
    with TestClient(app) as session:
        yield session


def review_input(sample):
    return {key: sample[key] for key in ("title", "diff", "context", "repo")}


def finish_job(client, response, *, expected="completed"):
    assert response.status_code == 202, response.text
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"completed", "failed", "interrupted"}:
            assert job["status"] == expected, job
            return job
        time.sleep(0.01)
    pytest.fail(f"Job {job_id} did not finish within five seconds")


def two_confirmed_examples(client):
    samples = client.get("/api/state").json()["samples"]
    saved = []
    for sample in samples[:2]:
        response = client.post("/api/experiences/manual", json={**review_input(sample), **FEEDBACK})
        assert response.status_code == 201, response.text
        saved.append(response.json())
    return saved


def trained_checkpoint(client):
    two_confirmed_examples(client)
    return finish_job(client, client.post("/api/training", json={"name": "test-checkpoint"}))[
        "result"
    ]


def test_ufo_auto_adopts_checkpoint_and_retry_keeps_original_result(client, provider):
    first_request = {**ufo_input(), "condition": "auto"}
    headers = {"Idempotency-Key": "ufo-auto-first-turn"}
    first = client.post("/api/reviewer", json=first_request, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["checkpoint"] is None
    assert provider.calls[-1]["checkpoint"] is None
    checkpoint = trained_checkpoint(client)
    call_count = len(provider.calls)
    retry = client.post("/api/reviewer", json=first_request, headers=headers)
    assert retry.status_code == 200, retry.text
    assert retry.json() == first.json()
    assert len(provider.calls) == call_count
    next_request = {**ufo_input(), "condition": "auto"}
    next_review = client.post(
        "/api/reviewer", json=next_request, headers={"Idempotency-Key": "ufo-auto-second-turn"}
    )
    assert next_review.status_code == 200, next_review.text
    assert next_review.json()["checkpoint"] == checkpoint["checkpoint"]
    assert provider.calls[-1]["checkpoint"] == checkpoint["checkpoint"]


def ufo_input():
    return {
        "title": "Inspect payment failure",
        "diff": "+try:\n+    charge(order)\n+except Exception:\n+    return None",
        "context": "A complete bug fix PR. No test changes are present.",
        "repo": "tests/isolated",
        "provenance": {
            **{key: str(uuid4()) for key in ("workspace_id", "thread_id", "agent_id", "turn_id")},
            "sdk_commit": UFO_SDK_COMMIT,
        },
    }


def ufo_envelope(payload, experience_id, *, events=None):
    return {
        "experience": {
            **{key: payload[key] for key in ("title", "diff", "context", "repo")},
            "source": "ufo",
            "split": "train",
            "ufo": payload["provenance"],
            "agent_review": deepcopy(REVIEW),
            "experience_id": experience_id,
            "trajectory": events
            or [
                {
                    "type": "tool_result",
                    "tool": "git",
                    "input": "git diff",
                    "message": "Patch observed",
                    "is_error": False,
                    "timestamp": "2026-09-27",
                }
            ],
        }
    }


def test_sample_review_feedback_training_and_three_condition_replay(client, provider):
    initial = client.get("/api/state").json()
    assert initial["stats"] == {"experiences": 0, "corrections": 0, "eligible": 0}
    assert initial["checkpoints"] == []
    assert initial["evaluations"] == []
    assert initial["status"]["training_methods"] == ["sft", "sft+rl"]
    assert all("gold" not in sample for sample in initial["samples"])

    experience_ids = []
    for sample in initial["samples"][:2]:
        job = finish_job(client, client.post("/api/reviews", json=review_input(sample)))
        saved = job["result"]
        assert saved["source"] == "sample"
        assert saved["fictional"] is True
        assert saved["agent_review"]["decision"] == "REJECT"
        assert saved["human_feedback"] is None
        assert [event["type"] for event in job["events"]] == [
            "started",
            "context",
            "sampling",
            "review_saved",
            "completed",
        ]
        experience_ids.append(saved["id"])
        assert client.get("/api/dataset/export").text.count("\n") == len(experience_ids) - 1
        response = client.post(f"/api/experiences/{saved['id']}/feedback", json=FEEDBACK)
        assert response.status_code == 200, response.text
        assert response.json()["human_feedback"]["kind"] == "confirmed_outcome"

    exported = [json.loads(line) for line in client.get("/api/dataset/export").text.splitlines()]
    assert {row["experience_id"] for row in exported} == set(experience_ids)
    assert all(json.loads(row["completion"])["decision"] == "REJECT" for row in exported)
    assert all(FEEDBACK["reason"] not in row["prompt"] for row in exported)

    training = finish_job(client, client.post("/api/training", json={"name": "test-checkpoint"}))
    checkpoint = training["result"]
    assert checkpoint["example_count"] == 2
    assert set(checkpoint["experience_ids"]) == set(experience_ids)
    assert checkpoint["method"] == "sft"
    assert checkpoint["checkpoint"] == "river://test-only/sampler_weights/test-checkpoint"
    assert provider.training_calls[0]["examples"] == exported
    assert provider.training_calls[0]["method"] == "sft"
    assert "accuracy" not in checkpoint["metrics"]
    assert FEEDBACK["reason"] in checkpoint["memory"]

    call_offset = len(provider.calls)
    evaluation = finish_job(
        client, client.post("/api/evaluations", json={"checkpoint": checkpoint["id"]})
    )["result"]
    assert [condition["name"] for condition in evaluation["conditions"]] == [
        "base",
        "memory",
        "learned",
    ]
    assert evaluation["matched_prompts"] is True
    assert evaluation["dataset_hash"] == checkpoint["dataset_hash"]
    base, memory, learned = evaluation["conditions"]
    case_count = len(HELD_OUT_PRS)
    assert all(condition["total"] == case_count for condition in evaluation["conditions"])
    assert all(
        condition["accuracy"] == condition["correct"] / case_count
        for condition in evaluation["conditions"]
    )
    assert [row["prompt_hash"] for row in memory["results"]] == [
        row["prompt_hash"] for row in learned["results"]
    ]
    assert [row["prompt_hash"] for row in base["results"]] != [
        row["prompt_hash"] for row in memory["results"]
    ]
    calls = provider.calls[call_offset:]
    assert len(calls) == 3 * case_count
    assert [call["prompt"] for call in calls[case_count : 2 * case_count]] == [
        call["prompt"] for call in calls[2 * case_count :]
    ]
    assert all(call["checkpoint"] is None for call in calls[: 2 * case_count])
    assert all(call["checkpoint"] == checkpoint["checkpoint"] for call in calls[2 * case_count :])
    final = client.get("/api/state").json()
    assert final["stats"]["experiences"] == 2
    assert len(final["evaluations"]) == 1


def test_export_excludes_unapproved_feedback_and_duplicate_content(client):
    samples = client.get("/api/state").json()["samples"]
    first = {**review_input(samples[0]), **FEEDBACK, "approved": False}
    response = client.post("/api/experiences/manual", json=first)
    assert response.status_code == 201
    assert client.get("/api/dataset/export").text == ""
    first["approved"] = True
    assert client.post("/api/experiences/manual", json=first).status_code == 201
    first["title"] = "Same content, renamed review"
    assert client.post("/api/experiences/manual", json=first).status_code == 201
    assert len(client.get("/api/dataset/export").text.splitlines()) == 1
    response = client.post("/api/training", json={"name": "deduplicated"})
    assert response.status_code == 422
    assert "distinct" in response.json()["detail"]


def test_conflicting_manual_feedback_cannot_break_existing_dataset(client):
    sample = client.get("/api/state").json()["samples"][0]
    body = {**review_input(sample), **FEEDBACK}
    assert client.post("/api/experiences/manual", json=body).status_code == 201
    before = client.get("/api/dataset/export").text
    conflicting = {**body, "decision": "APPROVE", "reason": "Conflicting judgment", "issues": []}
    assert client.post("/api/experiences/manual", json=conflicting).status_code == 422
    assert client.get("/api/dataset/export").text == before
    assert client.get("/api/state").json()["stats"]["eligible"] == 1


def test_conflicting_feedback_update_leaves_original_records_usable(client):
    sample = client.get("/api/state").json()["samples"][0]
    body = {**review_input(sample), **FEEDBACK}
    first = client.post("/api/experiences/manual", json=body).json()
    second = client.post("/api/experiences/manual", json=body).json()
    conflicting = {"decision": "APPROVE", "reason": "Conflicting judgment", "issues": []}
    assert (
        client.post(f"/api/experiences/{second['id']}/feedback", json=conflicting).status_code
        == 422
    )
    state = client.get("/api/state").json()
    assert {row["id"] for row in state["experiences"]} == {first["id"], second["id"]}
    assert all(row["human_feedback"]["decision"] == "REJECT" for row in state["experiences"])
    assert state["stats"]["eligible"] == 1


def test_checkpoint_freezes_memory_before_later_corrections(client, provider):
    checkpoint = trained_checkpoint(client)
    samples = client.get("/api/state").json()["samples"]
    later = {**review_input(samples[2]), **FEEDBACK, "reason": "LATER_FEEDBACK_MARKER"}
    assert client.post("/api/experiences/manual", json=later).status_code == 201
    finish_job(client, client.post("/api/evaluations", json={"checkpoint": checkpoint["id"]}))
    assert all("LATER_FEEDBACK_MARKER" not in call["prompt"] for call in provider.calls)


def test_checkpoint_dataset_export_survives_later_feedback_edits(client):
    checkpoint = trained_checkpoint(client)
    endpoint = f"/api/datasets/{checkpoint['dataset_hash']}/export"
    original = client.get(endpoint)
    assert original.status_code == 200, original.text
    examples = [json.loads(line) for line in original.text.splitlines()]
    assert len(examples) == checkpoint["example_count"]
    assert {row["experience_id"] for row in examples} == set(checkpoint["experience_ids"])
    experience_id = checkpoint["experience_ids"][0]
    edited = {**FEEDBACK, "reason": "FEEDBACK_EDIT_AFTER_CHECKPOINT_SAVED"}
    assert client.post(f"/api/experiences/{experience_id}/feedback", json=edited).status_code == 200
    assert "FEEDBACK_EDIT_AFTER_CHECKPOINT_SAVED" in client.get("/api/dataset/export").text
    frozen = client.get(endpoint)
    assert frozen.status_code == 200
    assert frozen.text == original.text
    assert "FEEDBACK_EDIT_AFTER_CHECKPOINT_SAVED" not in frozen.text


def test_combined_training_forwards_method_and_persists_confirmed_checkpoints(tmp_path):
    provider = CombinedTrainingProvider()
    application = create_app(str(tmp_path / "combined-success.sqlite3"), provider=provider)
    with TestClient(application) as session:
        two_confirmed_examples(session)
        job = finish_job(
            session, session.post("/api/training", json={"name": "combined", "method": "sft+rl"})
        )
        assert provider.training_calls[0]["method"] == "sft+rl"
        assert len(provider.training_calls[0]["examples"]) == 2
        final = job["result"]
        assert final["method"] == "sft+rl"
        assert final["intermediate"] is False
        assert final["training_job_id"] == job["id"]
        assert final["metrics"]["rl_steps"] == 1
        assert final["metrics"]["rl_status"] == "updated"
        checkpoints = session.get("/api/state").json()["checkpoints"]
        assert len(checkpoints) == 2
        interim = next(row for row in checkpoints if row["intermediate"])
        assert interim["method"] == "sft"
        assert interim["checkpoint"] == "river://test-only/sampler_weights/combined-sft"
        assert interim["training_job_id"] == job["id"]
        assert interim["dataset_hash"] == final["dataset_hash"]
        assert interim["memory"] == final["memory"]
        events = [event["type"] for event in job["events"]]
        assert (
            events.index("sft_checkpoint_saved")
            < events.index("rl_step")
            < events.index("completed")
        )
        sample = session.get("/api/state").json()["samples"][0]
        finish_job(
            session,
            session.post(
                "/api/reviews",
                json={
                    **review_input(sample),
                    "condition": "learned",
                    "checkpoint": final["id"],
                },
            ),
        )
        assert provider.calls[-1]["checkpoint"] == final["checkpoint"]
    application.state.store.close()


def test_rl_failure_preserves_confirmed_sft_checkpoint_without_rl_completion(tmp_path):
    provider = CombinedTrainingProvider(fail_rl=True)
    application = create_app(str(tmp_path / "combined-failure.sqlite3"), provider=provider)
    with TestClient(application) as session:
        two_confirmed_examples(session)
        job = finish_job(
            session,
            session.post("/api/training", json={"name": "partial", "method": "sft+rl"}),
            expected="failed",
        )
        assert provider.training_calls[0]["method"] == "sft+rl"
        assert job["result"] is None
        assert "RL backward failed" in job["error"]
        checkpoints = session.get("/api/state").json()["checkpoints"]
        assert len(checkpoints) == 1
        saved = checkpoints[0]
        assert saved["method"] == "sft"
        assert saved["intermediate"] is True
        assert saved["training_job_id"] == job["id"]
        assert saved["checkpoint"] == "river://test-only/sampler_weights/partial-sft"
        assert saved["metrics"]["rl_steps"] == 0
        assert saved["metrics"]["rl_status"] == "not_requested"
        assert [event["type"] for event in job["events"]] == [
            "started",
            "dataset",
            "sft_checkpoint_saved",
            "failed",
        ]
        sample = session.get("/api/state").json()["samples"][0]
        finish_job(
            session,
            session.post(
                "/api/reviews",
                json={
                    **review_input(sample),
                    "condition": "learned",
                    "checkpoint": saved["id"],
                },
            ),
        )
        assert provider.calls[-1]["checkpoint"] == saved["checkpoint"]
    application.state.store.close()


def test_completed_checkpoint_and_feedback_survive_restart(tmp_path):
    path = str(tmp_path / "restart.sqlite3")
    first = create_app(path, provider=FakeProvider())
    with TestClient(first) as session:
        checkpoint = trained_checkpoint(session)
        state_before = session.get("/api/state").json()
    first.state.store.close()
    replacement_provider = FakeProvider()
    restarted = create_app(path, provider=replacement_provider)
    with TestClient(restarted) as session:
        state_after = session.get("/api/state").json()
        assert state_after["experiences"] == state_before["experiences"]
        assert state_after["checkpoints"][0]["id"] == checkpoint["id"]
        assert all(job["status"] == "completed" for job in state_after["jobs"])
        assert replacement_provider.training_calls == []
        assert replacement_provider.calls == []
    restarted.state.store.close()


def test_stale_job_becomes_interrupted_on_restart_without_paid_retry(tmp_path):
    path = str(tmp_path / "interrupted.sqlite3")
    first = create_app(path, provider=FakeProvider())
    stale = first.state.store.create_job("training", {"name": "stale"})
    first.state.store.update_job(stale["id"], status="running")
    first.state.store.append_event(stale["id"], {"type": "training_step", "step": 1})
    first.state.store.close()
    provider = FakeProvider()
    restarted = create_app(path, provider=provider)
    with TestClient(restarted) as session:
        job = session.get(f"/api/jobs/{stale['id']}").json()
        assert job["status"] == "interrupted"
        assert [event["type"] for event in job["events"]] == ["training_step", "interrupted"]
        assert "not automatically retried" in job["events"][-1]["message"]
        assert provider.training_calls == []
        assert session.get("/api/state").json()["checkpoints"] == []
    restarted.state.store.close()


def test_crashed_evaluation_artifact_becomes_interrupted_on_restart(tmp_path):
    path = str(tmp_path / "evaluation-restart.sqlite3")
    first = create_app(path, provider=FakeProvider())
    job = first.state.store.create_job("evaluation", {"checkpoint": "river://test-only/saved"})
    first.state.store.update_job(job["id"], status="running")
    evaluation = first.state.store.save(
        "evaluations",
        {
            "status": "running",
            "checkpoint": "river://test-only/saved",
            "job_id": job["id"],
            "conditions": [],
            "matched_prompts": False,
        },
    )
    first.state.store.close()
    provider = FakeProvider()
    restarted = create_app(path, provider=provider)
    with TestClient(restarted) as session:
        artifact = session.get("/api/state").json()["evaluations"][0]
        assert artifact["id"] == evaluation["id"]
        assert artifact["status"] in {"interrupted", "failed"}
        assert artifact["matched_prompts"] is False
        assert provider.calls == []
    restarted.state.store.close()


def test_missing_credentials_rejects_remote_work_without_fabricating_results(tmp_path):
    application = create_app(str(tmp_path / "offline.sqlite3"), provider=RiverProvider(api_key=""))
    with TestClient(application) as session:
        state = session.get("/api/state").json()
        assert state["status"]["river"]["configured"] is False
        assert state["status"]["river"]["verified"] is False
        assert (
            session.post("/api/reviews", json=review_input(state["samples"][0])).status_code == 503
        )
        two_confirmed_examples(session)
        assert session.post("/api/training", json={"name": "offline"}).status_code == 503
        assert session.post("/api/evaluations", json={"checkpoint": "missing"}).status_code == 503
        state = session.get("/api/state").json()
        assert state["jobs"] == []
        assert state["checkpoints"] == []
        assert state["evaluations"] == []
    application.state.store.close()


def test_training_failure_never_creates_checkpoint(client, provider):
    provider.training_failure = RiverOperationError(
        "River rejected training; check account access."
    )
    two_confirmed_examples(client)
    job = finish_job(
        client, client.post("/api/training", json={"name": "failed"}), expected="failed"
    )
    assert "account access" in job["error"]
    assert job["result"] is None
    assert client.get("/api/state").json()["checkpoints"] == []


def test_malformed_review_fails_without_saving_an_approval(client, provider):
    provider.review_failure = RiverResponseError("River returned invalid JSON.")
    sample = client.get("/api/state").json()["samples"][0]
    job = finish_job(
        client, client.post("/api/reviews", json=review_input(sample)), expected="failed"
    )
    assert "invalid JSON" in job["error"]
    assert client.get("/api/state").json()["experiences"] == []


def test_invalid_evaluation_output_remains_in_denominator(client, provider):
    checkpoint = trained_checkpoint(client)
    provider.review_failure = RiverResponseError("River returned invalid JSON.")
    provider.fail_on_call = 1
    job = finish_job(client, client.post("/api/evaluations", json={"checkpoint": checkpoint["id"]}))
    evaluation = job["result"]
    assert evaluation["status"] == "completed"
    assert all(condition["total"] == len(HELD_OUT_PRS) for condition in evaluation["conditions"])
    failed = evaluation["conditions"][0]["results"][0]
    assert failed["review"] is None
    assert failed["score"]["correct_decision"] is False
    assert failed["score"]["decision_accuracy"] == 0
    assert failed["score"]["invalid_output"] is True
    assert "invalid JSON" in failed["error"]
    assert len(provider.calls) == 3 * len(HELD_OUT_PRS)
    assert client.get("/api/state").json()["evaluations"][0] == evaluation


def test_transport_failure_retains_partial_evaluation_and_failed_job(client, provider):
    checkpoint = trained_checkpoint(client)
    provider.review_failure = RiverOperationError("River request timed out; completion is unknown.")
    provider.fail_on_call = 3
    job = finish_job(
        client,
        client.post("/api/evaluations", json={"checkpoint": checkpoint["id"]}),
        expected="failed",
    )
    assert "timed out" in job["error"]
    assert job["result"] is None
    evaluations = client.get("/api/state").json()["evaluations"]
    assert len(evaluations) == 1
    evaluation = evaluations[0]
    assert evaluation["status"] == "failed"
    assert evaluation["matched_prompts"] is False
    assert "timed out" in evaluation["error"]
    assert evaluation["conditions"][0]["total"] == 2
    assert len(evaluation["conditions"][0]["results"]) == 2
    assert len(provider.calls) == 3


def test_evaluation_refuses_checkpoint_from_different_base_model(client, provider):
    checkpoint = trained_checkpoint(client)
    provider.base_model = "another/model"
    response = client.post("/api/evaluations", json={"checkpoint": checkpoint["id"]})
    assert response.status_code == 409
    assert "base model" in response.json()["detail"]
    assert provider.calls == []


def test_evaluation_fails_if_model_facing_inputs_change(tmp_path):
    class MismatchedProvider(FakeProvider):
        async def review(self, prompt, checkpoint=None):
            result = await super().review(prompt, checkpoint)
            if checkpoint:
                result["input_token_hash"] = "different-rendered-token-input"
            return result

    provider = MismatchedProvider()
    application = create_app(str(tmp_path / "mismatched.sqlite3"), provider=provider)
    with TestClient(application) as session:
        checkpoint = trained_checkpoint(session)
        job = finish_job(
            session,
            session.post("/api/evaluations", json={"checkpoint": checkpoint["id"]}),
            expected="failed",
        )
        assert "token inputs changed" in job["error"]
        evaluation = session.get("/api/state").json()["evaluations"][0]
        assert evaluation["status"] == "failed"
        assert evaluation["matched_prompts"] is False
        assert len(provider.calls) == 2 * len(HELD_OUT_PRS) + 1
    application.state.store.close()


def test_held_out_content_cannot_enter_review_or_manual_training(client, provider):
    payload = review_input(HELD_OUT_PRS[0])
    payload["title"] = "Rename does not make held-out content a new case"
    payload["repo"] = "different/repo"
    for endpoint, body in (
        ("/api/reviews", payload),
        ("/api/experiences/manual", {**payload, **FEEDBACK}),
    ):
        response = client.post(endpoint, json=body)
        assert response.status_code == 422, response.text
        assert "boundary" in response.json()["detail"]
    assert provider.calls == []
    assert client.get("/api/state").json()["experiences"] == []


def test_review_excludes_nested_gold_and_hidden_reasoning_from_provider_prompt(client, provider):
    payload = {
        "title": "A distinct test patch",
        "diff": "+count = len(rows)",
        "context": {
            "facts": "Only use visible changes",
            "gold": "DO_NOT_SEND_GOLD",
            "nested": {"expected_decision": "DO_NOT_SEND_LABEL"},
        },
        "trajectory": [{"type": "reasoning", "message": "DO_NOT_SEND_REASONING"}],
    }
    job = finish_job(client, client.post("/api/reviews", json=payload))
    for marker in ("DO_NOT_SEND_GOLD", "DO_NOT_SEND_LABEL", "DO_NOT_SEND_REASONING"):
        assert marker not in provider.calls[-1]["prompt"]
        assert marker not in json.dumps(job["result"])
    assert "Only use visible changes" in provider.calls[-1]["prompt"]


@pytest.mark.parametrize(
    "field,value",
    [("gold", {"decision": "APPROVE"}), ("decision", "APPROVE"), ("condition", "pretend")],
)
def test_review_rejects_invalid_or_label_fields(client, provider, field, value):
    payload = {"title": "Test", "diff": "+answer = 42", field: value}
    assert client.post("/api/reviews", json=payload).status_code == 422
    assert provider.calls == []


def test_local_boundary_blocks_foreign_origin_host_and_large_body(client, provider):
    payload = {"title": "Test", "diff": "+answer = 42"}
    assert (
        client.post(
            "/api/reviews", json=payload, headers={"Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    assert client.get("/api/state", headers={"Host": "attacker.example"}).status_code == 403
    response = client.post(
        "/api/reviews", content=b"x" * 1_000_001, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert provider.calls == []
    assert client.get("/api/health").headers["X-Content-Type-Options"] == "nosniff"


def test_ufo_review_requires_auth_provenance_and_idempotency(client, provider, monkeypatch):
    payload = ufo_input()
    monkeypatch.setenv("REFLEX_INGEST_TOKEN", "test-ingest-token")
    assert client.post("/api/reviewer", json=payload).status_code == 401
    headers = {"Authorization": "Bearer test-ingest-token"}
    assert client.post("/api/reviewer", json=payload, headers=headers).status_code == 422
    headers["Idempotency-Key"] = "test-turn"
    missing_provenance = {key: value for key, value in payload.items() if key != "provenance"}
    assert client.post("/api/reviewer", json=missing_provenance, headers=headers).status_code == 422
    assert client.post("/api/reviews", json=payload).status_code == 422
    payload["provenance"]["turn_id"] = "not-a-runtime-uuid"
    assert client.post("/api/reviewer", json=payload, headers=headers).status_code == 422
    assert provider.calls == []


def test_ufo_retries_reuse_saved_review_even_after_restart(tmp_path):
    path = str(tmp_path / "ufo-retry.sqlite3")
    provider = FakeProvider()
    application = create_app(path, provider=provider)
    payload = ufo_input()
    headers = {"Idempotency-Key": "stable-ufo-turn"}
    with TestClient(application) as session:
        first = session.post("/api/reviewer", json=payload, headers=headers)
        assert first.status_code == 200, first.text
        first_result = first.json()
        retry = session.post("/api/reviewer", json=payload, headers=headers)
        assert retry.status_code == 200
        assert retry.json() == first_result
        assert len(provider.calls) == 1
        changed = {**payload, "diff": "+new_patch = True"}
        assert session.post("/api/reviewer", json=changed, headers=headers).status_code == 409
        assert len(provider.calls) == 1
    application.state.store.close()
    offline = RiverProvider(api_key="")
    restarted = create_app(path, provider=offline)
    with TestClient(restarted) as session:
        retry = session.post("/api/reviewer", json=payload, headers=headers)
        assert retry.status_code == 200, retry.text
        assert retry.json() == first_result
        assert len(session.get("/api/state").json()["experiences"]) == 1
    restarted.state.store.close()


def test_ufo_failed_request_is_not_automatically_retried(client, provider):
    provider.review_failure = RiverOperationError("Provider completion is unconfirmed.")
    payload = ufo_input()
    headers = {"Idempotency-Key": "uncertain-turn"}
    assert client.post("/api/reviewer", json=payload, headers=headers).status_code == 502
    retry = client.post("/api/reviewer", json=payload, headers=headers)
    assert retry.status_code == 409
    assert "unconfirmed" in retry.json()["detail"]
    assert len(provider.calls) == 1


def test_ufo_import_merges_trajectory_and_preserves_human_feedback(client, provider):
    payload = ufo_input()
    response = client.post(
        "/api/reviewer", json=payload, headers={"Idempotency-Key": "merged-turn"}
    )
    assert response.status_code == 200
    experience_id = response.json()["experience_id"]
    human = {
        "decision": "APPROVE",
        "reason": "The supplied context proves this path is safe.",
        "issues": [],
    }
    assert client.post(f"/api/experiences/{experience_id}/feedback", json=human).status_code == 200
    envelope = ufo_envelope(payload, experience_id)
    response = client.post("/api/experiences/import", json=envelope)
    assert response.status_code == 201, response.text
    assert response.json()["id"] == experience_id
    assert response.json()["human_feedback"]["decision"] == "APPROVE"
    assert response.json()["agent_review"]["decision"] == "REJECT"
    assert response.json()["trajectory"] == envelope["experience"]["trajectory"]
    assert client.post("/api/experiences/import", json=envelope).status_code == 201
    assert len(client.get("/api/state").json()["experiences"]) == 1
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "identity", ["workspace_id", "turn_id", "thread_id", "agent_id", "sdk_commit"]
)
def test_ufo_import_cannot_replace_runtime_identity(client, identity):
    payload = ufo_input()
    response = client.post(
        "/api/reviewer", json=payload, headers={"Idempotency-Key": "identity-turn"}
    )
    experience_id = response.json()["experience_id"]
    envelope = ufo_envelope(deepcopy(payload), experience_id)
    envelope["experience"]["ufo"][identity] = "a" * 40 if identity == "sdk_commit" else str(uuid4())
    response = client.post("/api/experiences/import", json=envelope)
    assert response.status_code == 409, response.text
    assert "provenance" in response.json()["detail"]
    assert client.get("/api/state").json()["experiences"][0]["ufo"] == payload["provenance"]


def test_ufo_import_without_experience_id_is_idempotent_by_runtime_turn(client, provider):
    payload = ufo_input()
    envelope = ufo_envelope(payload, None)
    del envelope["experience"]["experience_id"]
    first = client.post("/api/experiences/import", json=envelope)
    assert first.status_code == 201, first.text
    repeated = client.post("/api/experiences/import", json=envelope)
    assert repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    assert len(client.get("/api/state").json()["experiences"]) == 1
    envelope["experience"]["diff"] = "+changed_patch = 1"
    assert client.post("/api/experiences/import", json=envelope).status_code == 409
    assert provider.calls == []


def test_ufo_import_rejects_different_patch_and_agent_supplied_feedback(client):
    payload = ufo_input()
    response = client.post("/api/reviewer", json=payload, headers={"Idempotency-Key": "patch-turn"})
    experience_id = response.json()["experience_id"]
    envelope = ufo_envelope(payload, experience_id)
    envelope["experience"]["diff"] = "+different_patch = 1"
    assert client.post("/api/experiences/import", json=envelope).status_code == 409
    envelope = ufo_envelope(payload, experience_id)
    envelope["experience"]["human_feedback"] = FEEDBACK
    assert client.post("/api/experiences/import", json=envelope).status_code == 422
    assert client.get("/api/state").json()["stats"]["eligible"] == 0


@pytest.mark.parametrize("payload", [[], None, "not an envelope"])
def test_import_rejects_nonobject_envelope_with_actionable_client_error(client, payload):
    response = client.post(
        "/api/experiences/import",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422, response.text
    assert "object" in response.json()["detail"]


def test_completed_job_event_stream_resumes_without_repeating_seen_events(client):
    sample = client.get("/api/state").json()["samples"][0]
    job = finish_job(client, client.post("/api/reviews", json=review_input(sample)))
    response = client.get(f"/api/jobs/{job['id']}/events", headers={"Last-Event-ID": "2"})
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    events = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert [event["type"] for event in events] == ["sampling", "review_saved", "completed"]
    assert "id: 3\n" in response.text
    assert "id: 1\n" not in response.text


def test_shutdown_interrupts_active_review_without_persisting_partial_experience(tmp_path):
    class WaitingProvider(FakeProvider):
        async def review(self, prompt, checkpoint=None):
            self.calls.append({"prompt": prompt, "checkpoint": checkpoint})
            await asyncio.Event().wait()

    provider = WaitingProvider()
    application = create_app(str(tmp_path / "shutdown.sqlite3"), provider=provider)
    with TestClient(application) as session:
        sample = session.get("/api/state").json()["samples"][0]
        response = session.post("/api/reviews", json=review_input(sample))
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert session.post("/api/reviews", json=review_input(sample)).status_code == 409
    job = application.state.store.get("jobs", job_id)
    assert job["status"] == "interrupted"
    assert application.state.store.list("experiences") == []
    assert len(provider.calls) == 1
    application.state.store.close()


def test_shutdown_preserves_partial_evaluation_with_terminal_status(tmp_path):
    class WaitingEvaluationProvider(FakeProvider):
        async def review(self, prompt, checkpoint=None):
            if self.calls:
                self.calls.append({"prompt": prompt, "checkpoint": checkpoint})
                await asyncio.Event().wait()
            return await super().review(prompt, checkpoint)

    provider = WaitingEvaluationProvider()
    application = create_app(str(tmp_path / "evaluation-shutdown.sqlite3"), provider=provider)
    with TestClient(application) as session:
        checkpoint = trained_checkpoint(session)
        response = session.post("/api/evaluations", json={"checkpoint": checkpoint["id"]})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        deadline = time.monotonic() + 5
        while len(provider.calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(provider.calls) == 2
    job = application.state.store.get("jobs", job_id)
    assert job["status"] == "interrupted"
    evaluation = application.state.store.list("evaluations")[0]
    assert evaluation["status"] in {"interrupted", "failed"}
    assert evaluation["matched_prompts"] is False
    assert evaluation["conditions"][0]["total"] == 1
    assert len(evaluation["conditions"][0]["results"]) == 1
    application.state.store.close()
