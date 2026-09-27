"""Call the installed UFO repair tool against the real local Reflex API.

Offline check: .cache/ufo-env/bin/python integrations/ufo/run_live_repair.py
One live call: .cache/ufo-env/bin/python integrations/ufo/run_live_repair.py --run

This is a programmatic SDK invocation, not a full UFO agent conversation. It uses
real tool discovery, SDK values, lifecycle hooks, HTTP, and durable local storage.
No River key is read here: model access belongs to the running Reflex API.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "programmatic SDK invocation"


def write_json(path: Path, value: dict) -> None:
    """Atomic replacement keeps a killed process from truncating its receipt."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class JsonStore:
    """Workspace-store protocol backed by a locked, durable local JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _transaction(self, action, *, write=False):
        with self.path.with_suffix(".lock").open("a") as lock:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            rows = json.loads(self.path.read_text()) if self.path.exists() else {}
            result = action(rows)
            if write:
                write_json(self.path, rows)
            return result

    async def get(self, key):
        return self._transaction(lambda rows: rows.get(key))

    async def put_if(self, key, value, expected):
        def update(rows):
            if rows.get(key) != expected:
                return False
            rows[key] = value
            return True

        return self._transaction(update, write=True)

    async def put(self, key, value):
        self._transaction(lambda rows: rows.update({key: value}), write=True)

    async def delete(self, key):
        self._transaction(lambda rows: rows.pop(key, None), write=True)


def load_runtime():
    from ufo.config import load_config
    from ufo.host.ext.loader import load_manifests

    config = load_config(Path(__file__).with_name("ufo.example.toml"))
    manifests = load_manifests(pack=config.pack.name)
    manifest = next(item for item in manifests if item.name == "reflex")
    tool = next(item for item in manifest.tools if item.name == "repair_code_with_reflex")
    tool.schema()
    return manifest, tool


async def read_state(url: str) -> dict:
    import httpx

    headers = {}
    if token := os.environ.get("REFLEX_INGEST_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.get(url + "/api/repairs/state", headers=headers)
    if response.status_code != 200:
        raise RuntimeError(f"Local Reflex state returned HTTP {response.status_code}.")
    return response.json()


def validate_repair(response: dict, checkpoint: str) -> dict:
    row = response.get("repair", {})
    report = row.get("report", {})
    if response.get("checkpoint") != checkpoint or row.get("condition") != "learned":
        raise RuntimeError("The tool response did not use the selected learned checkpoint.")
    code = row.get("code")
    if (
        not isinstance(code, str)
        or report.get("code_hash") != hashlib.sha256(code.encode()).hexdigest()
    ):
        raise RuntimeError("The execution report does not match the returned candidate.")
    if not report.get("isolation", {}).get("enforced"):
        raise RuntimeError("The candidate report does not confirm enforced isolation.")
    return row


async def run_live(case_id: str, run_id: UUID, checkpoint: str | None) -> dict:
    from ufo.runtime.ext.hooks import BoundHook, HookChain
    from ufo.sdk.context import Agent, ExtensionContext, Turn
    from ufo.sdk.manifest import PostToolUse, Stop, UserPromptSubmit
    from ufo.sdk.tools import ToolContext
    from ufo_ext_reflex.capture import SDK_COMMIT, key, provenance
    from ufo_ext_reflex.client import base_url

    manifest, tool = load_runtime()
    url = base_url()
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("This live verifier requires a local Reflex API.")
    directory = ROOT / ".cache" / "ufo-live" / str(run_id)
    receipt_path = directory / "receipt.json"
    if receipt_path.exists():
        return json.loads(receipt_path.read_text())
    invocation_path = directory / "invocation.json"
    if invocation_path.exists():
        raise RuntimeError(
            "This invocation already started. Inspect its saved state and Reflex job; "
            "no inference request was retried."
        )
    state = await read_state(url)
    if any(job.get("status") in {"queued", "running"} for job in state["jobs"]):
        raise RuntimeError("Reflex has an active job. Wait before starting the UFO invocation.")
    checkpoints = state["checkpoints"]
    selected = (
        next((item for item in checkpoints if checkpoint in {item["id"], item["checkpoint"]}), None)
        if checkpoint
        else next(iter(checkpoints), None)
    )
    if selected is None:
        raise RuntimeError("A saved repair checkpoint is required; base fallback is disabled here.")
    selected_uri = selected["checkpoint"]
    instruction = (
        f"Programmatic SDK invocation: call repair_code_with_reflex for {case_id} using "
        "condition auto and the selected saved checkpoint. Record its actual execution "
        "report. This is not an interactive UFO conversation or a human approval."
    )
    turn = Turn(
        id=run_id,
        workspace_id=uuid4(),
        conversation_id=uuid4(),
        agent_id=uuid4(),
        seq=1,
        status="running",
        inbound=instruction,
        created_at=datetime.now(UTC),
    )
    invocation = {
        "source": SOURCE,
        "status": "reserved",
        "ufo": provenance(turn),
        "case_id": case_id,
        "condition": "auto",
        "checkpoint": selected_uri,
        "started_at": datetime.now(UTC).isoformat(),
    }
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation prevents two processes using one turn ID from racing.
    with invocation_path.open("x", encoding="utf-8") as stream:
        os.chmod(invocation_path, 0o600)
        json.dump(invocation, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    store = JsonStore(directory / "store.json")
    ext = ExtensionContext(store=store, credentials=None)
    agent = Agent(prompt=instruction, model="programmatic-sdk-no-orchestrator-model")
    chain = HookChain(
        hooks={spec.event: (BoundHook(spec, ext),) for spec in manifest.hooks},
        audience=ext.audience,
    )
    context = ToolContext(
        sandbox=None,
        blob=None,
        turn=turn,
        agent=agent,
        spawn=None,
        speaker_member_id=None,
        audience=ext.audience,
        artifact_token_secret=secrets.token_urlsafe(32),
        ext=ext,
    )

    async def fire(event, payload):
        result = await chain.fire(event, payload, turn, agent, None)
        if result.denied is not None or result.failed_closed is not None:
            raise RuntimeError(f"The actual UFO {event} hook did not complete.")

    await fire("user_prompt_submit", UserPromptSubmit(text=instruction))
    args = tool.input_model(case_id=case_id, condition="auto", checkpoint=selected_uri)
    result = await tool.handler(context, args)
    if result.is_error:
        raise RuntimeError(result.content[0].text[:500])
    response = json.loads(result.content[0].text)
    write_json(directory / "response.json", response)
    row = validate_repair(response, selected_uri)
    await fire(
        "post_tool_use",
        PostToolUse(
            tool_name=tool.name,
            tool_input=args,
            output=result.content[0].text,
        ),
    )
    report = row["report"]
    await fire(
        "stop",
        Stop(
            answer=(
                f"Programmatic SDK invocation completed. Repair {row['id']} used {selected_uri}. "
                f"Actual checks: {report['passed']}/{report['total']}, status {report['status']}. "
                "No full UFO chat conversation or human approval is claimed."
            )
        ),
    )
    stored = await store.get(key(turn.id))
    if not stored or not stored.get("exported"):
        raise RuntimeError("The tool ran, but the observable trajectory was not exported.")
    final_state = await read_state(url)
    imported = next(item for item in final_state["repairs"] if item["id"] == row["id"])
    if imported.get("ufo") != provenance(turn) or [
        item["type"] for item in imported.get("trajectory", [])
    ] != ["instruction", "tool_result", "answer"]:
        raise RuntimeError("The saved Reflex trajectory does not match this SDK invocation.")
    receipt = {
        **invocation,
        "status": "completed",
        "completed_at": datetime.now(UTC).isoformat(),
        "runtime": f"ufo-ai/ufo-core@{SDK_COMMIT}",
        "tool": tool.name,
        "tool_runtime_uuid": str(turn.id),
        "experience_id": row["id"],
        "job_id": row["job_id"],
        "model": response["model"],
        "report": report,
        "baseline_report": row["baseline_report"],
        "code_hash": report["code_hash"],
        "input_token_hash": row.get("input_token_hash"),
        "trajectory": imported["trajectory"],
        "trajectory_imported": True,
        "human_feedback_submitted": False,
        "full_agent_conversation": False,
        "receipt_path": str(receipt_path),
    }
    write_json(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Make one real learned repair call.")
    parser.add_argument("--case-id", default="repair-stock-replay")
    parser.add_argument("--checkpoint", help="Saved repair checkpoint ID or River URI.")
    parser.add_argument(
        "--run-id", type=UUID, default=None, help="Stable UUID; never auto-retried."
    )
    args = parser.parse_args()
    try:
        if not args.run:
            manifest, tool = load_runtime()
            result = {
                "status": "ready",
                "source": SOURCE,
                "tool": tool.name,
                "hooks": [item.event for item in manifest.hooks],
                "cloud_calls": 0,
                "next": "Run with --run after the current Reflex job finishes.",
            }
        else:
            receipt = asyncio.run(run_live(args.case_id, args.run_id or uuid4(), args.checkpoint))
            result = {
                name: receipt[name]
                for name in (
                    "status",
                    "source",
                    "experience_id",
                    "checkpoint",
                    "tool_runtime_uuid",
                    "trajectory_imported",
                    "full_agent_conversation",
                    "receipt_path",
                )
            }
            result["checks"] = f"{receipt['report']['passed']}/{receipt['report']['total']}"
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:
        # Provider responses and environment values are never dumped on failure.
        message = str(error) if isinstance(error, RuntimeError) else "Inspect the saved local run."
        print(
            json.dumps({"status": "failed", "error_type": type(error).__name__, "error": message})
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
