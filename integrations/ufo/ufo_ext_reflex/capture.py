"""Observe public UFO hooks, without collecting internal reasoning blocks."""

from __future__ import annotations

import hashlib
import json
import re
import asyncio
from datetime import UTC, datetime
from typing import Any

from ufo.sdk.manifest import (
    HookContext,
    HookOutcome,
    PostToolUse,
    PostToolUseFailure,
    Stop,
    UserPromptSubmit,
)

from ufo_ext_reflex.client import post

SDK_COMMIT = "63ba388ed449ff46c9d70744119dffc85df0fbf8"
MAX_EVENTS = 128
SECRET_FIELD = re.compile(r"(?i)(?:secret|password|authorization|api[_-]?key|access[_-]?token)")
SECRET_TEXT = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|(?:api[_-]?key|password|secret)\s*[:=]\s*)"
    r"[\"']?[^\s\"',;]+"
)
PRIVATE_FIELDS = {"reasoning", "thinking", "chain_of_thought", "reasoning_content"}


def bounded_text(value: str) -> str:
    value = SECRET_TEXT.sub(r"\1[REDACTED]", value)
    return value if len(value) <= 4096 else value[:4068] + "\n[output truncated]"


def safe_arguments(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SECRET_FIELD.search(str(key)) else safe_arguments(item)
            for key, item in value.items()
            if str(key).lower() not in PRIVATE_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [safe_arguments(item) for item in value[:100]]
    if isinstance(value, str):
        return bounded_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[unsupported value]"


def key(turn_id: Any) -> str:
    return f"reflex:turn:{turn_id}"


def provenance(turn: Any) -> dict[str, str]:
    return {
        "workspace_id": str(turn.workspace_id),
        "turn_id": str(turn.id),
        "thread_id": str(turn.conversation_id),
        "agent_id": str(turn.agent_id),
        "sdk_commit": SDK_COMMIT,
    }


async def append_event(ext: Any, turn_id: Any, event: dict[str, Any]) -> None:
    """CAS preserves concurrent tool results; content fingerprints deduplicate replay."""
    fingerprint = hashlib.sha256(
        json.dumps(event, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    event = dict(event, timestamp=datetime.now(UTC).isoformat(), _fingerprint=fingerprint)
    for _ in range(12):
        old = await ext.store.get(key(turn_id))
        record = dict(old) if isinstance(old, dict) else {}
        events = list(record.get("events", []))
        if any(item.get("_fingerprint") == fingerprint for item in events):
            return
        events.append(event)
        if len(events) > MAX_EVENTS:
            # Keep the opening instruction and the most recent observed actions.
            events = [events[0], *events[-(MAX_EVENTS - 1):]]
            record["events_truncated"] = True
        record["events"] = events
        if await ext.store.put_if(key(turn_id), record, old):
            return
    raise RuntimeError("Reflex could not persist concurrent UFO events; retry the turn")


def public_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [{key: value for key, value in event.items() if not key.startswith("_")}
            for event in record.get("events", [])]


async def observe(ctx: HookContext) -> HookOutcome:
    if ctx.turn is None:
        return None
    match ctx.payload:
        case UserPromptSubmit(text=text):
            await append_event(ctx.ext, ctx.turn.id, {
                "type": "instruction", "message": bounded_text(text),
            })
        case PostToolUse(tool_name=name, tool_input=args, output=output):
            await append_event(ctx.ext, ctx.turn.id, {
                "type": "tool_result", "tool": name,
                "input": bounded_text(json.dumps(safe_arguments(args.model_dump(mode="json")))),
                "message": bounded_text(output), "is_error": False,
            })
        case PostToolUseFailure(tool_name=name, tool_input=args, output=output):
            await append_event(ctx.ext, ctx.turn.id, {
                "type": "tool_result", "tool": name,
                "input": bounded_text(json.dumps(safe_arguments(args.model_dump(mode="json")))),
                "message": bounded_text(output), "is_error": True,
            })
        case Stop(answer=answer):
            await append_event(ctx.ext, ctx.turn.id, {
                "type": "answer", "message": bounded_text(answer),
            })
            record = await ctx.ext.store.get(key(ctx.turn.id))
            if not isinstance(record, dict) or "review_request" not in record:
                # Only reviews belong to this corpus; unrelated turns are not exported.
                await ctx.ext.store.delete(key(ctx.turn.id))
                return None
            response = record.get("review_response")
            if not isinstance(response, dict):
                return None
            request = record["review_request"]
            experience = {
                name: request.get(name, "") for name in ("title", "diff", "context", "repo")
            }
            experience.update({
                "source": "ufo", "split": "train", "ufo": provenance(ctx.turn),
                "agent_review": response["review"], "trajectory": public_events(record),
                "experience_id": response["experience_id"],
            })
            # UFO gives hooks five seconds. Export is a local persistence call;
            # leave time for the final receipt write inside that runtime budget.
            async with asyncio.timeout(3.0):
                await post("/api/experiences/import", {"experience": experience},
                           idempotency_key=f"ufo-export:{ctx.turn.workspace_id}:{ctx.turn.id}")
            # Keep a small receipt, not a second indefinite copy of repository content.
            await ctx.ext.store.put(key(ctx.turn.id), {
                "exported": True, "experience_id": response["experience_id"],
            })
    return None
