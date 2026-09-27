"""Specialist capabilities offered to UFO's general agent as ordinary tools."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from ufo.sdk.tools import TextContent, ToolContext, ToolResult

from ufo_ext_reflex.capture import key, provenance, public_events
from ufo_ext_reflex.client import ReflexUnavailable, post


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    diff: str = Field(min_length=1, max_length=200_000)
    context: str = Field(default="", max_length=32_000)
    repo: str = Field(default="", max_length=500)
    condition: Literal["auto", "base", "memory", "learned"] = "auto"
    checkpoint: str | None = Field(default=None, max_length=500)


class RepairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")
    condition: Literal["auto", "base", "memory", "learned"] = "auto"
    checkpoint: str | None = Field(default=None, max_length=500)


def _failure(message: str) -> ToolResult:
    return ToolResult(is_error=True, content=(TextContent(text=message),))


def _request_kind(record: dict) -> str | None:
    """Read older review receipts as well as records written by either specialist."""
    declared = record.get("request_kind")
    if declared is not None:
        return declared
    if "review_request" in record:
        return "review"
    if "repair_request" in record:
        return "repair"
    return None


async def _specialist_request(
    ctx: ToolContext, args: ReviewInput | RepairInput, kind: Literal["review", "repair"]
) -> ToolResult:
    if ctx.ext is None:
        raise RuntimeError("Reflex tool needs its UFO ExtensionContext")
    request = args.model_dump(exclude_none=True)
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    request_field, response_field = f"{kind}_request", f"{kind}_response"
    # Reserve before HTTP: two different cases or specialists cannot race to save
    # incompatible receipts. Replays of the same request use the server's durable key.
    for _ in range(12):
        old = await ctx.ext.store.get(key(ctx.turn.id))
        record = dict(old) if isinstance(old, dict) else {}
        previous_kind, previous_digest = _request_kind(record), record.get("request_digest")
        if (previous_kind is not None and previous_kind != kind) or (
            previous_digest is not None and previous_digest != digest
        ):
            return _failure(
                "This turn already used a different Reflex specialist request. "
                "Start a new turn for another case, condition, review, or repair."
            )
        if record.get("exported"):
            if previous_digest is None:
                return _failure("This turn already completed a Reflex request. Start a new turn.")
            return ToolResult(content=(TextContent(text=json.dumps(record, ensure_ascii=False)),))
        result = record.get(response_field)
        if isinstance(result, dict):
            return ToolResult(content=(TextContent(text=json.dumps(result, ensure_ascii=False)),))
        wire_request = record.get(request_field)
        if not isinstance(wire_request, dict):
            wire_request = {
                **request, "provenance": provenance(ctx.turn), "trajectory": public_events(record)
            }
        record.update({"request_kind": kind, "request_digest": digest, request_field: wire_request})
        if await ctx.ext.store.put_if(key(ctx.turn.id), record, old):
            break
    else:
        raise RuntimeError("Reflex could not reserve this UFO turn; retry the request")
    try:
        result = await post(
            "/api/reviewer" if kind == "review" else "/api/repairer", wire_request,
            idempotency_key=f"ufo-{kind}:{ctx.turn.workspace_id}:{ctx.turn.id}",
        )
    except ReflexUnavailable as exc:
        return _failure(str(exc))
    experience_id = result.get("experience_id")
    if not isinstance(result.get(kind), dict) or not isinstance(experience_id, str) or not experience_id:
        return _failure(f"Reflex returned no persisted {kind}. Check the API before retrying.")
    if kind == "repair" and not isinstance(result["repair"].get("code"), str):
        return _failure("Reflex returned a repair without handler code. Check the API before retrying.")
    # Other tools may have completed while inference was in flight.
    for _ in range(12):
        old = await ctx.ext.store.get(key(ctx.turn.id))
        record = dict(old) if isinstance(old, dict) else {}
        if _request_kind(record) != kind or record.get("request_digest") != digest:
            raise RuntimeError("Reflex's reserved request changed before its result was saved")
        record[response_field] = result
        if await ctx.ext.store.put_if(key(ctx.turn.id), record, old):
            break
    else:
        raise RuntimeError(f"Reflex {kind} persisted remotely but its UFO receipt could not be saved")
    return ToolResult(content=(TextContent(text=json.dumps(result, ensure_ascii=False)),))


async def review_code_with_reflex(ctx: ToolContext, args: ReviewInput) -> ToolResult:
    return await _specialist_request(ctx, args, "review")


async def repair_code_with_reflex(ctx: ToolContext, args: RepairInput) -> ToolResult:
    return await _specialist_request(ctx, args, "repair")
