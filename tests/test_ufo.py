"""Contract checks for the UFO ingress boundary and HTTP transport."""

from __future__ import annotations

import json
import sys
import importlib.util
import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from reflex.integrations.ufo import UFO_SDK_COMMIT, normalize_ufo_experience

sys.path.insert(0, str(Path(__file__).parents[1] / "integrations" / "ufo"))
from ufo_ext_reflex import client  # noqa: E402


@pytest.fixture
def envelope():
    return {
        "source": "ufo",
        "split": "train",
        "title": "Handle a failed payment",
        "diff": "+except Exception:\n+    pass",
        "repo": "example/payments",
        "context": "Bug fix",
        "ufo": {
            **{name: str(uuid4()) for name in ("turn_id", "workspace_id", "thread_id", "agent_id")},
            "sdk_commit": UFO_SDK_COMMIT,
        },
        "agent_review": {
            "decision": "REJECT",
            "summary": "Payment failure is swallowed",
            "issues": ["catch_all"],
        },
        "trajectory": [
            {
                "type": "tool_result",
                "tool": "read",
                "input": '{"path":"app.py"}',
                "message": "except Exception: pass",
                "is_error": False,
                "timestamp": "2026-09-27T12:00:00+00:00",
            }
        ],
    }


def test_observed_experience_preserves_provenance_and_review(envelope):
    normalized = normalize_ufo_experience(envelope)
    assert normalized["ufo"] == envelope["ufo"]
    assert normalized["trajectory"][0]["tool"] == "read"
    assert normalized["agent_review"]["decision"] == "REJECT"
    assert "human_feedback" not in normalized


@pytest.mark.parametrize("value", [[], {}, None])
def test_malformed_decision_is_client_error(envelope, value):
    envelope["agent_review"]["decision"] = value
    with pytest.raises(ValueError, match="decision"):
        normalize_ufo_experience(envelope)


@pytest.mark.parametrize("value", [[], {}, None])
def test_malformed_event_type_is_client_error(envelope, value):
    envelope["trajectory"][0]["type"] = value
    with pytest.raises(ValueError, match="final answers"):
        normalize_ufo_experience(envelope)


@pytest.mark.parametrize(
    "label", ["human_feedback", "human_decision", "reward", "gold_label", "validated"]
)
def test_agent_cannot_supply_human_training_labels(envelope, label):
    envelope[label] = {"approved": True, "decision": "APPROVE"}
    with pytest.raises(ValueError, match="human feedback"):
        normalize_ufo_experience(envelope)


def test_held_out_and_unknown_runtime_id_are_rejected(envelope):
    envelope["split"] = "eval"
    with pytest.raises(ValueError, match="held-out"):
        normalize_ufo_experience(envelope)
    envelope["split"] = "train"
    envelope["ufo"]["turn_id"] = "made-up-turn"
    with pytest.raises(ValueError, match="UUID"):
        normalize_ufo_experience(envelope)


def test_reasoning_blocks_and_unbounded_output_are_rejected(envelope):
    envelope["trajectory"][0]["type"] = "reasoning"
    with pytest.raises(ValueError, match="final answers"):
        normalize_ufo_experience(envelope)
    envelope["trajectory"][0]["type"] = "tool_result"
    envelope["trajectory"][0]["message"] = "x" * 4097
    with pytest.raises(ValueError, match="4096"):
        normalize_ufo_experience(envelope)


def test_nonfinite_data_rejected(envelope):
    envelope["agent_review"]["issues"] = [float("nan")]
    with pytest.raises(ValueError, match="finite JSON"):
        normalize_ufo_experience(envelope)


def test_transport_accepts_loopback_and_requires_tls_remotely(monkeypatch):
    monkeypatch.delenv("REFLEX_URL", raising=False)
    assert client.base_url() == "http://127.0.0.1:8000"
    monkeypatch.setenv("REFLEX_URL", "http://reflex.example.com")
    with pytest.raises(client.ReflexUnavailable, match="HTTPS"):
        client.base_url()
    monkeypatch.setenv("REFLEX_URL", "https://user:secret@reflex.example.com")
    with pytest.raises(client.ReflexUnavailable, match="credentials"):
        client.base_url()


@pytest.mark.asyncio
async def test_http_transport_sends_token_and_idempotency_without_redirect(monkeypatch):
    original = httpx.AsyncClient
    observed = []

    def respond(request):
        observed.append(request)
        return httpx.Response(200, json={"experience_id": "review-1"})

    def make_client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["timeout"].connect == 5.0
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(client.httpx, "AsyncClient", make_client)
    monkeypatch.setenv("REFLEX_INGEST_TOKEN", "test-credential")
    monkeypatch.setenv("REFLEX_URL", "http://127.0.0.1:8000")
    result = await client.post("/api/reviewer", {"title": "Review"}, idempotency_key="turn-1")
    assert result["experience_id"] == "review-1"
    assert observed[0].headers["Authorization"] == "Bearer test-credential"
    assert observed[0].headers["Idempotency-Key"] == "turn-1"
    assert json.loads(observed[0].content) == {"title": "Review"}


@pytest.mark.asyncio
async def test_error_body_cannot_leak_upstream_secret(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        client.httpx,
        "AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="upstream provider echoed secret")
            ),
        ),
    )
    with pytest.raises(client.ReflexUnavailable) as raised:
        await client.post("/api/reviewer", {}, idempotency_key="turn-2")
    assert "REFLEX_INGEST_TOKEN" in str(raised.value)
    assert "echoed secret" not in str(raised.value)


@pytest.fixture
def capture_module(monkeypatch):
    """Mock the external SDK import boundary, using its verified public event shape.

    These unit checks exercise our capture logic, not a claim that UFO has booted.
    """
    sdk = ModuleType("ufo.sdk.manifest")

    @dataclass
    class UserPromptSubmit:
        text: str

    @dataclass
    class PostToolUse:
        tool_name: str
        tool_input: object
        output: str

    @dataclass
    class PostToolUseFailure:
        tool_name: str
        tool_input: object
        output: str

    @dataclass
    class Stop:
        answer: str

    for item in (UserPromptSubmit, PostToolUse, PostToolUseFailure, Stop):
        setattr(sdk, item.__name__, item)
    sdk.HookContext = object
    sdk.HookOutcome = object
    monkeypatch.setitem(sys.modules, "ufo.sdk.manifest", sdk)
    path = Path(__file__).parents[1] / "integrations/ufo/ufo_ext_reflex/capture.py"
    spec = importlib.util.spec_from_file_location("reflex_capture_contract_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, sdk


class MemoryScopedStore:
    """In-memory edge double for UFO's workspace-scoped compare-and-swap store."""

    def __init__(self):
        self.records = {}

    async def get(self, key):
        return self.records.get(key)

    async def put_if(self, key, value, expected):
        if self.records.get(key) != expected:
            return False
        self.records[key] = value
        return True

    async def put(self, key, value):
        self.records[key] = value

    async def delete(self, key):
        self.records.pop(key, None)


@pytest.mark.asyncio
async def test_capture_caps_events_and_deduplicates_replay(capture_module):
    module, _ = capture_module
    ext = SimpleNamespace(store=MemoryScopedStore())
    await module.append_event(ext, "turn", {"type": "instruction", "message": "Review this PR"})
    for index in range(140):
        await module.append_event(ext, "turn", {"type": "tool_result", "message": str(index)})
    await module.append_event(ext, "turn", {"type": "tool_result", "message": "139"})
    saved = await ext.store.get(module.key("turn"))
    assert len(saved["events"]) == 128
    assert saved["events_truncated"] is True
    assert saved["events"][0]["type"] == "instruction"
    assert module.public_events(saved)[-1]["message"] == "139"
    assert "_fingerprint" not in module.public_events(saved)[0]


def test_capture_omits_private_reasoning_and_redacts_credentials(capture_module):
    module, _ = capture_module
    result = module.safe_arguments(
        {
            "path": "app.py",
            "api_key": "do-not-store",
            "reasoning": "private",
            "nested": {"password": "private"},
        }
    )
    assert result == {
        "path": "app.py",
        "api_key": "[REDACTED]",
        "nested": {"password": "[REDACTED]"},
    }
    assert "do-not-store" not in module.bounded_text("Authorization: Bearer do-not-store")
    assert len(module.bounded_text("x" * 20_000)) <= 4096


@pytest.mark.asyncio
async def test_stop_exports_only_actual_review_and_keeps_matching_id(
    capture_module, monkeypatch, envelope
):
    module, sdk = capture_module
    ext = SimpleNamespace(store=MemoryScopedStore())
    identity = envelope["ufo"]
    turn = SimpleNamespace(
        id=identity["turn_id"],
        workspace_id=identity["workspace_id"],
        conversation_id=identity["thread_id"],
        agent_id=identity["agent_id"],
    )
    saved = {
        "review_request": envelope,
        "review_response": {"review": envelope["agent_review"], "experience_id": "original"},
        "events": [],
    }
    await ext.store.put(module.key(turn.id), saved)
    exported = []

    async def post(path, payload, **kwargs):
        exported.append((path, payload, kwargs))
        return {"id": "original"}

    monkeypatch.setattr(module, "post", post)
    await module.observe(SimpleNamespace(turn=turn, ext=ext, payload=sdk.Stop(answer="REJECT")))
    experience = exported[0][1]["experience"]
    assert experience["experience_id"] == "original"
    assert experience["trajectory"][-1]["type"] == "answer"
    assert normalize_ufo_experience(experience)["ufo"]["turn_id"] == str(turn.id)
    assert await ext.store.get(module.key(turn.id)) == {
        "exported": True,
        "experience_id": "original",
    }


@pytest.mark.asyncio
async def test_non_review_turn_is_not_exported(capture_module):
    module, sdk = capture_module
    ext = SimpleNamespace(store=MemoryScopedStore())
    turn = SimpleNamespace(id=uuid4())
    await module.observe(SimpleNamespace(turn=turn, ext=ext, payload=sdk.Stop(answer="Hello")))
    assert ext.store.records == {}


@pytest.fixture
def tool_module(capture_module, monkeypatch):
    capture, _ = capture_module
    sdk = ModuleType("ufo.sdk.tools")

    @dataclass
    class TextContent:
        text: str

    @dataclass
    class ToolResult:
        content: tuple
        is_error: bool = False

    sdk.TextContent = TextContent
    sdk.ToolResult = ToolResult
    sdk.ToolContext = object
    monkeypatch.setitem(sys.modules, "ufo.sdk.tools", sdk)
    monkeypatch.setitem(sys.modules, "ufo_ext_reflex.capture", capture)
    path = Path(__file__).parents[1] / "integrations/ufo/ufo_ext_reflex/tools.py"
    spec = importlib.util.spec_from_file_location("reflex_tool_contract_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "reflex_tool_contract_test", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_reviewer_matches_api_contract_and_reuses_durable_receipt(tool_module, monkeypatch):
    module = tool_module
    sent = []

    async def post(path, payload, **kwargs):
        sent.append((path, payload))
        return {
            "review": {"decision": "APPROVE", "summary": "Checked", "issues": []},
            "experience_id": "review-1",
            "model": "real-provider-model",
        }

    monkeypatch.setattr(module, "post", post)
    ext = SimpleNamespace(store=MemoryScopedStore())
    turn = SimpleNamespace(
        id=uuid4(), workspace_id=uuid4(), conversation_id=uuid4(), agent_id=uuid4()
    )
    ctx = SimpleNamespace(ext=ext, turn=turn)
    args = module.ReviewInput(title="Review patch", diff="+return value")
    first = await module.review_code_with_reflex(ctx, args)
    second = await module.review_code_with_reflex(ctx, args)
    assert first == second
    assert len(sent) == 1
    assert sent[0][0] == "/api/reviewer"
    assert sent[0][1]["condition"] == "auto"
    assert sent[0][1]["provenance"]["turn_id"] == str(turn.id)
    assert set(sent[0][1]) == {
        "title",
        "diff",
        "context",
        "repo",
        "condition",
        "provenance",
        "trajectory",
    }
    changed = await module.review_code_with_reflex(
        ctx, module.ReviewInput(title="Other", diff="+pass")
    )
    assert changed.is_error is True
    assert len(sent) == 1


def _tool_context():
    return SimpleNamespace(
        ext=SimpleNamespace(store=MemoryScopedStore()),
        turn=SimpleNamespace(id=uuid4(), workspace_id=uuid4(), conversation_id=uuid4(), agent_id=uuid4()),
    )


def _repair_response():
    return {
        "experience_id": "repair-1",
        "repair": {"code": "def handler(event):\n    return event['value']\n",
                   "summary": "Restore returned value", "diff": "+return event['value']",
                   "report": {"passed": True}},
        "model": "fixture-model", "checkpoint": None,
    }


@pytest.mark.asyncio
async def test_repairer_sends_saved_case_identity_and_reuses_result(tool_module, monkeypatch):
    ctx = _tool_context()
    requests = []

    async def post(path, payload, **kwargs):
        requests.append((path, payload, kwargs))
        return _repair_response()

    monkeypatch.setattr(tool_module, "post", post)
    args = tool_module.RepairInput(case_id="handler-case-1")
    first = await tool_module.repair_code_with_reflex(ctx, args)
    second = await tool_module.repair_code_with_reflex(ctx, args)
    assert first == second and not first.is_error
    assert len(requests) == 1
    path, request, headers = requests[0]
    assert path == "/api/repairer"
    assert set(request) == {"case_id", "condition", "provenance", "trajectory"}
    assert request["case_id"] == "handler-case-1" and request["condition"] == "auto"
    assert request["provenance"]["turn_id"] == str(ctx.turn.id)
    assert headers["idempotency_key"] == f"ufo-repair:{ctx.turn.workspace_id}:{ctx.turn.id}"
    assert json.loads(first.content[0].text)["repair"]["report"] == {"passed": True}
    changed = await tool_module.repair_code_with_reflex(
        ctx, tool_module.RepairInput(case_id="handler-case-2")
    )
    assert changed.is_error and len(requests) == 1


@pytest.mark.asyncio
async def test_repair_stop_exports_observations_and_preserves_turn_guard(
    tool_module, capture_module, monkeypatch
):
    capture, sdk = capture_module
    ctx = _tool_context()
    requests = []

    async def post(path, payload, **kwargs):
        requests.append((path, payload, kwargs))
        return _repair_response() if path == "/api/repairer" else {"id": "repair-1"}

    monkeypatch.setattr(tool_module, "post", post)
    monkeypatch.setattr(capture, "post", post)
    args = tool_module.RepairInput(case_id="case-1", condition="learned", checkpoint="checkpoint-1")
    await tool_module.repair_code_with_reflex(ctx, args)
    stopped = SimpleNamespace(turn=ctx.turn, ext=ctx.ext, payload=sdk.Stop(answer="Candidate ready"))
    await capture.observe(stopped)
    await capture.observe(stopped)
    assert len(requests) == 2
    path, payload, kwargs = requests[1]
    assert path == "/api/repairs/import"
    assert kwargs["idempotency_key"] == f"ufo-repair-export:{ctx.turn.workspace_id}:{ctx.turn.id}"
    experience = payload["experience"]
    assert set(experience) == {"experience_id", "case_id", "source", "ufo", "trajectory"}
    assert experience["case_id"] == "case-1" and experience["experience_id"] == "repair-1"
    assert experience["ufo"] == requests[0][1]["provenance"]
    assert experience["trajectory"][-1]["type"] == "answer"
    assert requests[0][1]["checkpoint"] == "checkpoint-1"
    receipt = await ctx.ext.store.get(capture.key(ctx.turn.id))
    assert receipt["request_kind"] == "repair" and receipt["case_id"] == "case-1"
    replayed = await tool_module.repair_code_with_reflex(ctx, args)
    assert json.loads(replayed.content[0].text)["exported"] is True
    different = await tool_module.repair_code_with_reflex(ctx, tool_module.RepairInput(case_id="case-2"))
    review = await tool_module.review_code_with_reflex(
        ctx, tool_module.ReviewInput(title="Review", diff="+pass")
    )
    assert different.is_error and review.is_error and len(requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("first_kind", ["review", "repair"])
async def test_specialist_reservation_prevents_mixed_concurrent_requests(
    tool_module, monkeypatch, first_kind
):
    ctx = _tool_context()
    started, finish = asyncio.Event(), asyncio.Event()
    paths = []

    async def post(path, payload, **kwargs):
        paths.append(path)
        started.set()
        await finish.wait()
        return _repair_response() if path == "/api/repairer" else {
            "experience_id": "review-1", "review": {"decision": "APPROVE", "issues": []}
        }

    monkeypatch.setattr(tool_module, "post", post)
    operations = {
        "review": (tool_module.review_code_with_reflex, tool_module.ReviewInput(title="PR", diff="+pass")),
        "repair": (tool_module.repair_code_with_reflex, tool_module.RepairInput(case_id="case-1")),
    }
    first_handler, first_args = operations[first_kind]
    second_handler, second_args = operations["review" if first_kind == "repair" else "repair"]
    in_flight = asyncio.create_task(first_handler(ctx, first_args))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        second = await second_handler(ctx, second_args)
        assert second.is_error
    finally:
        finish.set()
    assert not (await in_flight).is_error
    assert len(paths) == 1


@pytest.mark.asyncio
async def test_failed_repair_can_retry_same_request_but_cannot_change_case(
    tool_module, capture_module, monkeypatch
):
    capture, _ = capture_module
    ctx = _tool_context()
    requests = []

    async def post(path, payload, **kwargs):
        requests.append((path, payload, kwargs))
        if len(requests) == 1:
            raise client.ReflexUnavailable("Reflex timed out; check its job list")
        return _repair_response()

    monkeypatch.setattr(tool_module, "post", post)
    args = tool_module.RepairInput(case_id="case-1")
    assert (await tool_module.repair_code_with_reflex(ctx, args)).is_error
    changed = await tool_module.repair_code_with_reflex(ctx, tool_module.RepairInput(case_id="case-2"))
    assert changed.is_error and len(requests) == 1
    await capture.append_event(ctx.ext, ctx.turn.id, {"type": "tool_result", "message": "Retry"})
    assert not (await tool_module.repair_code_with_reflex(ctx, args)).is_error
    assert requests[0] == requests[1]


@pytest.mark.asyncio
async def test_failed_repair_export_keeps_result_for_delivery_retry(
    tool_module, capture_module, monkeypatch
):
    capture, sdk = capture_module
    ctx = _tool_context()
    attempts = []

    async def tool_post(*args, **kwargs):
        return _repair_response()

    async def export_post(path, payload, **kwargs):
        attempts.append(payload)
        if len(attempts) == 1:
            raise client.ReflexUnavailable("Cannot reach Reflex")
        return {"id": "repair-1"}

    monkeypatch.setattr(tool_module, "post", tool_post)
    monkeypatch.setattr(capture, "post", export_post)
    await tool_module.repair_code_with_reflex(ctx, tool_module.RepairInput(case_id="case-1"))
    stopped = SimpleNamespace(turn=ctx.turn, ext=ctx.ext, payload=sdk.Stop(answer="Candidate ready"))
    with pytest.raises(client.ReflexUnavailable):
        await capture.observe(stopped)
    saved = await ctx.ext.store.get(capture.key(ctx.turn.id))
    assert "repair_response" in saved and not saved.get("exported")
    await capture.observe(stopped)
    assert attempts[0] == attempts[1]


@pytest.mark.parametrize("invalid", [{"case_id": ""}, {"case_id": " "},
    {"case_id": "case-1", "human_feedback": {"approved": True}},
    {"case_id": "case-1", "condition": "human-approved"}])
def test_repair_input_cannot_supply_labels_or_empty_case(tool_module, invalid):
    with pytest.raises(ValidationError):
        tool_module.RepairInput(**invalid)
