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
    tools = {tool.name: tool for tool in reflex.tools}
    assert set(tools) == {"review_code_with_reflex", "repair_code_with_reflex"}
    assert all(tool.schema().name == name for name, tool in tools.items())
    store = EdgeStore()
    ext = ExtensionContext(store=store, credentials=None)
    agent = Agent(prompt="Use Reflex for this engineering task", model="fixture-model-no-cloud")
    chain = HookChain(hooks={spec.event: (BoundHook(spec, ext),) for spec in reflex.hooks},
                      audience=ext.audience)
    calls = []
    original_client = httpx.AsyncClient

    async def run_specialist(kind):
        tool = tools[f"{kind}_code_with_reflex"]
        turn = Turn(id=uuid4(), workspace_id=uuid4(), conversation_id=uuid4(), agent_id=uuid4(),
                    seq=1, status="running", inbound=f"Run the Reflex {kind}",
                    created_at=datetime.now(UTC))
        ctx = ToolContext(sandbox=None, blob=None, turn=turn, agent=agent, spawn=None,
                          speaker_member_id=None, audience=ext.audience,
                          artifact_token_secret="local-verification-only", ext=ext)
        experience_id = f"sdk-{kind}-fixture"
        request_endpoint = "/api/reviewer" if kind == "review" else "/api/repairer"
        export_endpoint = "/api/experiences/import" if kind == "review" else "/api/repairs/import"

        def respond(request):
            payload = json.loads(request.content)
            calls.append((request.url.path, payload))
            if request.url.path == request_endpoint:
                assert payload["provenance"]["turn_id"] == str(turn.id)
                assert request.headers["Idempotency-Key"] == (
                    f"ufo-{kind}:{turn.workspace_id}:{turn.id}"
                )
                result = {"decision": "REJECT", "summary": "Fixture response", "issues": []}
                if kind == "repair":
                    assert payload["case_id"] == "sdk-handler-case"
                    assert set(payload) == {"case_id", "condition", "provenance", "trajectory"}
                    result = {
                        "code": "def handler(event):\n    return event['value']\n",
                        "summary": "Fixture candidate", "diff": "+return event['value']",
                        "report": {"passed": True, "source": "HTTP fixture"},
                    }
                return httpx.Response(200, json={
                    "experience_id": experience_id, kind: result,
                    "model": "fixture-model-no-cloud", "checkpoint": None,
                })
            assert request.url.path == export_endpoint
            experience = payload["experience"]
            assert experience["experience_id"] == experience_id
            assert [event["type"] for event in experience["trajectory"]] == [
                "instruction", "tool_result", "tool_result", "answer"
            ]
            assert "human_feedback" not in experience
            if kind == "repair":
                assert experience["case_id"] == "sdk-handler-case"
                assert set(experience) == {
                    "experience_id", "case_id", "source", "ufo", "trajectory"
                }
            return httpx.Response(201, json={"id": experience_id})

        def edge_client(**kwargs):
            return original_client(**kwargs, transport=httpx.MockTransport(respond))

        async def fire(event, payload):
            result = await chain.fire(event, payload, turn, agent, None)
            assert result.denied is None and result.failed_closed is None

        with patch.dict(os.environ, {"REFLEX_URL": "http://127.0.0.1:8000"}), patch(
            "ufo_ext_reflex.client.httpx.AsyncClient", edge_client
        ):
            await fire("user_prompt_submit", UserPromptSubmit(text=turn.inbound))
            await fire("post_tool_use", PostToolUse(
                tool_name="read", tool_input=ReadInput(path="handler.py"),
                output="def handler(event): return None"
            ))
            args = tool.input_model(case_id="sdk-handler-case") if kind == "repair" else (
                tool.input_model(title="Review handler", diff="+return None")
            )
            result = await tool.handler(ctx, args)
            assert not result.is_error
            assert await tool.handler(ctx, args) == result
            other = tools["review_code_with_reflex" if kind == "repair" else "repair_code_with_reflex"]
            other_args = other.input_model(title="Other", diff="+pass") if kind == "repair" else (
                other.input_model(case_id="other-case")
            )
            assert (await other.handler(ctx, other_args)).is_error
            await fire("post_tool_use", PostToolUse(
                tool_name=tool.name, tool_input=args, output=result.content[0].text
            ))
            await fire("stop", Stop(answer=f"Completed fixture {kind}"))
            await fire("stop", Stop(answer=f"Completed fixture {kind}"))
            receipt = json.loads((await tool.handler(ctx, args)).content[0].text)
            assert receipt["exported"] and receipt["request_kind"] == kind
            assert receipt["experience_id"] == experience_id

    await run_specialist("review")
    await run_specialist("repair")
    assert len(calls) == 4
    assert len(store.rows) == 2 and all(record["exported"] for record in store.rows.values())
    print(json.dumps({
        "status": "passed",
        "runtime": "ufo-ai/ufo-core@63ba388ed449ff46c9d70744119dffc85df0fbf8",
        "pack": "reflex-demo", "tools": sorted(tools),
        "configuration": "ufo.example.toml validated by installed UFO",
        "hooks": [spec.event for spec in reflex.hooks],
        "http_calls": [path for path, _ in calls],
        "cloud_calls": 0,
        "io_fixtures": ["HTTP responses", "workspace store"],
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
