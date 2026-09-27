"""One trained capability offered to UFO's general agent as a normal tool."""

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


async def review_code_with_reflex(ctx: ToolContext, args: ReviewInput) -> ToolResult:
    if ctx.ext is None:
        raise RuntimeError("Reflex tool needs its UFO ExtensionContext")
    request = args.model_dump(exclude_none=True)
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    old = await ctx.ext.store.get(key(ctx.turn.id))
    record = dict(old) if isinstance(old, dict) else {}
    previous = record.get("request_digest")
    if previous and previous != digest:
        return ToolResult(is_error=True, content=(TextContent(
            text="This turn already reviewed a different request. Start a new turn for each PR review."
        ),))
    result = record.get("review_response")
    if not isinstance(result, dict):
        request.update({"provenance": provenance(ctx.turn),
                        "trajectory": public_events(record)})
        try:
            result = await post("/api/reviewer", request,
                                idempotency_key=f"ufo-review:{ctx.turn.workspace_id}:{ctx.turn.id}")
        except ReflexUnavailable as exc:
            return ToolResult(is_error=True, content=(TextContent(text=str(exc)),))
        if not isinstance(result.get("review"), dict) or not result.get("experience_id"):
            return ToolResult(is_error=True, content=(TextContent(
                text="Reflex returned no persisted review. Check the API before retrying."
            ),))
        # Other tools may have completed while inference was in flight.
        for _ in range(12):
            old = await ctx.ext.store.get(key(ctx.turn.id))
            record = dict(old) if isinstance(old, dict) else {}
            record.update({"request_digest": digest, "review_request": request,
                           "review_response": result})
            if await ctx.ext.store.put_if(key(ctx.turn.id), record, old):
                break
        else:
            raise RuntimeError("Reflex review persisted remotely but its UFO receipt could not be saved")
    return ToolResult(content=(TextContent(text=json.dumps(result, ensure_ascii=False)),))
