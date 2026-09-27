"""Exercise installed UFO discovery, real SDK values, and HookChain without cloud calls.

Run in an environment containing the pinned ufo distribution and ufo-ext-reflex.
Only HTTP and durable storage are replaced at the I/O boundary.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from pydantic import BaseModel
from ufo.config import load_config
from ufo.host.ext.loader import load_manifests
from ufo.runtime.ext.hooks import BoundHook, HookChain
from ufo.sdk.context import Agent, ExtensionContext, Turn
from ufo.sdk.manifest import PostToolUse, Stop, UserPromptSubmit
from ufo.sdk.tools import ToolContext


class EdgeStore:
    def __init__(self):
        self.rows = {}

    async def get(self, key):
        return self.rows.get(key)

    async def put_if(self, key, value, expected):
        if self.rows.get(key) != expected:
            return False
        self.rows[key] = value
        return True

    async def put(self, key, value):
        self.rows[key] = value

    async def delete(self, key):
        self.rows.pop(key, None)


class ReadInput(BaseModel):
    path: str


async def main():
    config = load_config(Path(__file__).with_name("ufo.example.toml"))
    assert config.pack.name == "reflex-demo"
    assert config.database.owner_url == config.database.url
    assert config.blob.backend == "filesystem"
    assert config.serve.host == "127.0.0.1"
    assert config.research.search_provider is None
    manifests = load_manifests(pack="reflex-demo")
    reflex = next(item for item in manifests if item.name == "reflex")
    tool = next(item for item in reflex.tools if item.name == "review_code_with_reflex")
    assert tool.schema().name == "review_code_with_reflex"
    store = EdgeStore()
    ext = ExtensionContext(store=store, credentials=None)
    turn = Turn(id=uuid4(), workspace_id=uuid4(), conversation_id=uuid4(), agent_id=uuid4(),
                seq=1, status="running", inbound="Review this PR", created_at=datetime.now(UTC))
    agent = Agent(prompt="Use Reflex to review this PR", model="fixture-model-no-cloud")
    ctx = ToolContext(sandbox=None, blob=None, turn=turn, agent=agent, spawn=None,
                      speaker_member_id=None, audience=ext.audience,
                      artifact_token_secret="local-verification-only", ext=ext)
    chain = HookChain(hooks={spec.event: (BoundHook(spec, ext),) for spec in reflex.hooks},
                      audience=ext.audience)
    calls = []

    def respond(request):
        payload = json.loads(request.content)
        calls.append((request.url.path, payload))
        if request.url.path == "/api/reviewer":
            assert payload["provenance"]["turn_id"] == str(turn.id)
            return httpx.Response(200, json={
                "experience_id": "sdk-contract-fixture",
                "review": {"decision": "REJECT", "summary": "Fixture response", "issues": []},
                "model": "fixture-model-no-cloud", "checkpoint": None,
            })
        assert request.url.path == "/api/experiences/import"
        experience = payload["experience"]
        assert experience["experience_id"] == "sdk-contract-fixture"
        assert [event["type"] for event in experience["trajectory"]] == [
            "instruction", "tool_result", "tool_result", "answer"
        ]
        assert "human_feedback" not in experience
        return httpx.Response(201, json={"id": "sdk-contract-fixture"})

    original_client = httpx.AsyncClient

    def edge_client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(respond))

    async def fire(event, payload):
        result = await chain.fire(event, payload, turn, agent, None)
        assert result.denied is None and result.failed_closed is None

    with patch.dict(os.environ, {"REFLEX_URL": "http://127.0.0.1:8000"}), patch(
        "ufo_ext_reflex.client.httpx.AsyncClient", edge_client
    ):
        await fire("user_prompt_submit", UserPromptSubmit(text="Review this PR"))
        await fire("post_tool_use", PostToolUse(
            tool_name="read", tool_input=ReadInput(path="payments.py"),
            output="try: payment.process()\nexcept Exception: pass"
        ))
        args = tool.input_model(title="Review payment handling", diff="+except Exception: pass")
        result = await tool.handler(ctx, args)
        assert not result.is_error
        await fire("post_tool_use", PostToolUse(
            tool_name=tool.name, tool_input=args, output=result.content[0].text
        ))
        await fire("stop", Stop(answer="REJECT: fixture review"))
    assert len(calls) == 2
    assert next(iter(store.rows.values())) == {
        "exported": True, "experience_id": "sdk-contract-fixture"
    }
    print(json.dumps({
        "status": "passed",
        "runtime": "ufo-ai/ufo-core@63ba388ed449ff46c9d70744119dffc85df0fbf8",
        "pack": "reflex-demo", "tool": tool.name,
        "configuration": "ufo.example.toml validated by installed UFO",
        "hooks": [spec.event for spec in reflex.hooks],
        "http_calls": [path for path, _ in calls],
        "cloud_calls": 0,
        "io_fixtures": ["HTTP responses", "workspace store"],
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
