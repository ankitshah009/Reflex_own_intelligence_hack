"""Validate the observable experience envelope emitted by the UFO extension.

This is Reflex's wire format, not an undocumented UFO HTTP API. The sender fills
it from the public UFO lifecycle hooks and ToolContext identity.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

UFO_SDK_COMMIT = "63ba388ed449ff46c9d70744119dffc85df0fbf8"
MAX_PAYLOAD_BYTES = 800_000
MAX_EVENTS = 128
FORBIDDEN_LABELS = frozenset(
    {
        "human_decision",
        "human_review",
        "human_feedback",
        "feedback",
        "user_feedback",
        "reward",
        "gold",
        "gold_label",
        "expected_decision",
        "validated",
        "approved_for_training",
    }
)


def _text(value: Any, name: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    if required and not value.strip():
        raise ValueError(f"{name} cannot be empty")
    return value


def _uuid(value: Any, name: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID supplied by UFO ToolContext") from exc


def normalize_ufo_experience(data: dict[str, Any]) -> dict[str, Any]:
    """Accept observations; human approval must happen through Reflex's feedback UI.

    A bearer authenticates the extension, while these checks validate its envelope.
    UUIDs or a commit hash alone do not cryptographically prove an event occurred.
    """
    if not isinstance(data, dict):
        raise ValueError("experience must be a JSON object")
    try:
        size = len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())
    except (TypeError, ValueError) as exc:
        raise ValueError("experience must contain finite JSON values") from exc
    if size > MAX_PAYLOAD_BYTES:
        raise ValueError("UFO experience exceeds 800 KB")
    if FORBIDDEN_LABELS.intersection(data):
        raise ValueError("UFO imports cannot supply human feedback or training approval")
    if data.get("source") != "ufo":
        raise ValueError("source must be ufo")
    if data.get("split", "train") != "train":
        raise ValueError("UFO imports cannot create held-out evaluation labels")
    raw_provenance = data.get("ufo")
    if not isinstance(raw_provenance, dict):
        raise ValueError("ufo runtime provenance is required")
    provenance = {
        key: _uuid(raw_provenance.get(key), f"ufo.{key}")
        for key in ("workspace_id", "turn_id", "thread_id", "agent_id")
    }
    commit = _text(raw_provenance.get("sdk_commit", ""), "ufo.sdk_commit", 40)
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("ufo.sdk_commit must identify a verified source revision")
    provenance["sdk_commit"] = commit
    review = data.get("agent_review")
    if (
        not isinstance(review, dict)
        or not isinstance(review.get("decision"), str)
        or review.get("decision") not in {"APPROVE", "REJECT"}
    ):
        raise ValueError("agent_review must contain an APPROVE or REJECT decision")
    issues = review.get("issues", [])
    if not isinstance(issues, list) or len(issues) > 50:
        raise ValueError("agent_review.issues must be a list of at most 50 issues")
    # Preserve the application's structured review issues, within a fixed size bound.
    if len(json.dumps(issues)) > 32_000:
        raise ValueError("agent_review.issues exceeds 32000 characters")
    raw_events = data.get("trajectory", [])
    if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
        raise ValueError("trajectory must contain at most 128 observable events")
    events = []
    for index, raw in enumerate(raw_events):
        if not isinstance(raw, dict):
            raise ValueError(f"trajectory[{index}] must be an object")
        kind = raw.get("type")
        if not isinstance(kind, str) or kind not in {"instruction", "tool_result", "answer"}:
            raise ValueError("only instructions, tool results, and final answers may be imported")
        event = {
            "type": kind,
            "message": _text(raw.get("message", ""), "event.message", 4096),
            "timestamp": _text(raw.get("timestamp", ""), "event.timestamp", 64),
        }
        if kind == "tool_result":
            event["tool"] = _text(raw.get("tool", ""), "event.tool", 200, required=True)
            event["input"] = _text(raw.get("input", ""), "event.input", 4096)
            if type(raw.get("is_error", False)) is not bool:
                raise ValueError("event.is_error must be a boolean")
            event["is_error"] = raw.get("is_error", False)
        events.append(event)
    result = {
        "source": "ufo",
        "split": "train",
        "title": _text(data.get("title", ""), "title", 300, required=True),
        "repo": _text(data.get("repo", ""), "repo", 500),
        "diff": _text(data.get("diff", ""), "diff", 200_000, required=True),
        "context": _text(data.get("context", ""), "context", 32_000),
        "agent_review": {
            "decision": review["decision"],
            "summary": _text(review.get("summary", ""), "agent_review.summary", 16_000),
            "issues": issues,
        },
        "trajectory": events,
        "ufo": provenance,
    }
    if data.get("experience_id") is not None:
        result["experience_id"] = _text(data["experience_id"], "experience_id", 100, required=True)
    return result
