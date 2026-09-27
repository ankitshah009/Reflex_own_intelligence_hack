"""Local Reflex API: durable experience, bounded jobs, and honest evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from reflex.core import (
    build_memory,
    build_review_prompt,
    build_sft_examples,
    content_fingerprint,
    normalize_experience,
    redact_secrets,
    score_review,
    utc_now,
    validate_no_leakage,
)
from reflex.fixtures import HELD_OUT_PRS, SAMPLE_PRS
from reflex.integrations.river import RiverProvider, RiverResponseError
from reflex.store import Store

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
logger = logging.getLogger("reflex")
TERMINAL = {"completed", "failed", "interrupted"}


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    diff: str = Field(min_length=1, max_length=200_000)
    context: str | dict[str, Any] = ""
    repo: str = Field(default="local", max_length=500)
    condition: Literal["base", "memory", "learned", "auto"] = "base"
    checkpoint: str | None = None
    provenance: dict[str, Any] | None = None
    trajectory: list[dict[str, Any]] = Field(default_factory=list, max_length=128)


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=20_000)
    issues: list[str] = Field(default_factory=list, max_length=20)
    approved: bool = True


class ManualInput(FeedbackInput):
    title: str = Field(min_length=1, max_length=500)
    diff: str = Field(min_length=1, max_length=200_000)
    context: str | dict[str, Any] = ""
    repo: str = Field(default="local", max_length=500)


class TrainingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="reflex-engineering-v1", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    method: Literal["sft", "sft+rl"] = "sft"


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint: str


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def create_app(db_path: str | None = None, provider: Any = None) -> FastAPI:
    db = Store(db_path or os.getenv("REFLEX_DB_PATH", str(ROOT / "data/reflex.sqlite3")))
    river = provider or RiverProvider()
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # A restart must not silently replay billable training or inference.
        for job in db.list("jobs"):
            if job.get("status") not in TERMINAL:
                db.update_job(
                    job["id"],
                    status="interrupted",
                    error="Server restarted. Review the saved events before starting a new run.",
                )
                db.append_event(
                    job["id"],
                    {
                        "type": "interrupted",
                        "message": "Server restarted; this run was not automatically retried.",
                    },
                )
        for artifact in db.list("evaluations"):
            if artifact.get("status") == "running":
                artifact.update(
                    status="interrupted",
                    error="Server restarted. Partial results are preserved; this evaluation was not retried.",
                )
                db.save("evaluations", artifact)
        yield
        for task in tuple(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Reflex", version="0.1.0", lifespan=lifespan)
    app.state.store = db
    app.state.provider = river

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        # Bind to loopback. Prevent a website from triggering local billable actions.
        allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
        if request.url.hostname not in allowed_hosts:
            return JSONResponse(
                {"detail": "Reflex runs locally. Use localhost or 127.0.0.1."}, status_code=403
            )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            allowed_origins = {
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://testserver",
            }
            if origin and origin not in allowed_origins:
                return JSONResponse(
                    {"detail": "This origin is not allowed to change local Reflex data."},
                    status_code=403,
                )
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 1_000_000:
                    return JSONResponse(
                        {"detail": "Request exceeds 1 MB. Import a smaller trajectory."},
                        status_code=413,
                    )
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ValueError)
    async def validation_error(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(redact_secrets(str(exc)))}, status_code=422)

    def need_river():
        if not river.configured:
            raise HTTPException(
                503, "River is not connected. Set RIVER_API_KEY in .env and restart the API."
            )

    def check_integration_auth(request: Request):
        token = os.getenv("REFLEX_INGEST_TOKEN", "")
        if token and not hmac.compare_digest(
            request.headers.get("authorization", ""), f"Bearer {token}"
        ):
            raise HTTPException(401, "A valid REFLEX_INGEST_TOKEN bearer token is required.")

    def training_experiences():
        return [row for row in db.list("experiences") if row.get("split") == "train"]

    def checkpoint_by_id(key: str | None):
        checkpoints = db.list("checkpoints")
        checkpoint = (
            (checkpoints[0] if checkpoints else None)
            if key is None
            else next((row for row in checkpoints if key in {row["id"], row["checkpoint"]}), None)
        )
        if not checkpoint:
            raise HTTPException(
                404, "Select a completed Reflex checkpoint before using learned judgment."
            )
        return checkpoint

    def guard_held_out(experience: dict[str, Any]):
        validate_no_leakage([experience, *HELD_OUT_PRS])

    def source_for(data: dict[str, Any]):
        fingerprint = content_fingerprint(data)
        return (
            "sample"
            if any(content_fingerprint(row) == fingerprint for row in SAMPLE_PRS)
            else "manual"
        )

    async def emit(job_id: str, event: dict[str, Any]):
        db.append_event(job_id, redact_secrets({"timestamp": utc_now(), **event}))

    def launch(kind: str, payload: dict[str, Any], work):
        if any(row.get("status") in {"queued", "running"} for row in db.list("jobs")):
            raise HTTPException(
                409, "A run is already active. Wait for it to finish before starting another."
            )
        job = db.create_job(kind, payload)

        async def runner():
            db.update_job(job["id"], status="running")
            await emit(job["id"], {"type": "started", "message": f"{kind.capitalize()} started."})
            try:
                result = await work(job["id"])
                db.update_job(job["id"], status="completed", result=result, completed_at=utc_now())
                await emit(
                    job["id"],
                    {
                        "type": "completed",
                        "message": f"{kind.capitalize()} completed.",
                        "result": result,
                    },
                )
            except asyncio.CancelledError:
                db.update_job(
                    job["id"],
                    status="interrupted",
                    error="Server stopped. This run was not retried.",
                )
                await emit(
                    job["id"],
                    {
                        "type": "interrupted",
                        "message": "Server stopped; inspect River Console for any in-flight request.",
                    },
                )
                raise
            except Exception as exc:
                # Provider error text is sanitized; request bodies and secrets are never logged.
                message = (
                    str(redact_secrets(str(exc)))[:1500]
                    or "Run failed. Check provider configuration and River Console."
                )
                db.update_job(job["id"], status="failed", error=message)
                await emit(job["id"], {"type": "failed", "message": message})
                logger.warning("%s job %s failed (%s)", kind, job["id"], type(exc).__name__)

        task = asyncio.create_task(runner())
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"job_id": job["id"]}

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "service": "reflex", "version": "0.1.0"}

    @app.get("/api/state")
    async def state():
        experiences = db.list("experiences")
        examples = build_sft_examples(experiences)
        observed_ufo = any(row.get("source") == "ufo" for row in experiences)
        jobs = db.list("jobs")
        return {
            "experiences": experiences,
            "samples": [
                {k: v for k, v in row.items() if k not in {"gold", "expected_review"}}
                for row in SAMPLE_PRS
            ],
            "checkpoints": db.list("checkpoints"),
            "evaluations": db.list("evaluations"),
            "jobs": jobs,
            "status": {
                "river": {
                    "configured": river.configured,
                    "model": river.base_model,
                    "verified": any(
                        row.get("status") == "completed"
                        and row.get("kind") in {"review", "ufo_review", "training", "evaluation"}
                        for row in jobs
                    ),
                },
                "ufo": {"configured": observed_ufo, "extension_available": True},
                "training_methods": ["sft", "sft+rl"],
                "storage": "local-sqlite",
            },
            "stats": {
                "experiences": len(experiences),
                "corrections": sum(bool(row.get("human_feedback")) for row in experiences),
                "eligible": len(examples),
            },
        }

    def prepare_review(data: ReviewInput):
        raw = data.model_dump(exclude={"condition", "checkpoint", "provenance"})
        raw["source"] = "ufo" if data.provenance else source_for(raw)
        if data.provenance:
            for key in ("workspace_id", "turn_id", "thread_id", "agent_id"):
                try:
                    UUID(str(data.provenance.get(key)))
                except ValueError:
                    raise HTTPException(
                        422, f"UFO provenance requires a valid {key} UUID."
                    ) from None
            raw["ufo"] = data.provenance
        experience = normalize_experience(raw)
        guard_held_out(experience)
        checkpoint = checkpoint_by_id(data.checkpoint) if data.condition == "learned" else None
        memory = (
            build_memory(training_experiences())
            if data.condition in {"memory", "learned"}
            else None
        )
        prompt = build_review_prompt(experience, memory=memory)
        return experience, checkpoint, prompt

    async def execute_review(experience, checkpoint, prompt, condition, on_event):
        await on_event(
            {"type": "context", "message": "Prepared the patch and repository context for review."}
        )
        await on_event({"type": "sampling", "message": "River is reviewing the patch."})
        review = await river.review(
            prompt, checkpoint=checkpoint["checkpoint"] if checkpoint else None
        )
        experience.update(
            {
                "agent_review": review,
                "condition": condition,
                "model": review.get("model", ""),
                "checkpoint": checkpoint["checkpoint"] if checkpoint else None,
                "prompt_hash": digest(prompt),
            }
        )
        experience["trajectory"].append(
            {"type": "review", "message": review["summary"], "timestamp": utc_now()}
        )
        saved = db.save("experiences", experience)
        await on_event(
            {
                "type": "review_saved",
                "message": "Review saved. Confirm or correct the judgment to make it eligible for learning.",
                "experience_id": saved["id"],
            }
        )
        return saved

    @app.post("/api/reviews", status_code=202)
    async def review(data: ReviewInput):
        need_river()
        if data.condition == "auto":
            raise HTTPException(422, "Select a reviewer condition explicitly in the workspace.")
        if data.provenance:
            raise HTTPException(
                422, "UFO provenance is accepted through the authenticated reviewer endpoint."
            )
        experience, checkpoint, prompt = prepare_review(data)
        return launch(
            "review",
            {"title": data.title, "condition": data.condition},
            lambda job_id: execute_review(
                experience, checkpoint, prompt, data.condition, lambda event: emit(job_id, event)
            ),
        )

    @app.post("/api/reviewer")
    async def reviewer(data: ReviewInput, request: Request):
        check_integration_auth(request)
        key = request.headers.get("idempotency-key")
        if not data.provenance or not key or len(key) > 250:
            raise HTTPException(
                422, "UFO reviewer calls require runtime provenance and an Idempotency-Key header."
            )
        request_key = digest(key)
        request_hash = digest(data.model_dump(exclude={"trajectory"}))
        previous_job = next(
            (
                row
                for row in db.list("jobs")
                if row.get("payload", {}).get("idempotency_key") == request_key
            ),
            None,
        )
        if previous_job:
            if previous_job["payload"]["request_hash"] != request_hash:
                raise HTTPException(
                    409,
                    "This UFO turn already submitted a different review. Start a new turn for a new request.",
                )
            previous = next(
                (row for row in db.list("experiences") if row.get("external_id") == request_key),
                None,
            )
            if previous:
                return {
                    "review": previous["agent_review"],
                    "experience_id": previous["id"],
                    "model": previous.get("model"),
                    "checkpoint": previous.get("checkpoint"),
                }
            raise HTTPException(
                409,
                "This UFO review is in progress or its completion is unconfirmed. Inspect Reflex and River before starting a new turn.",
            )
        need_river()
        if any(row.get("status") in {"queued", "running"} for row in db.list("jobs")):
            raise HTTPException(409, "Another run is active. Wait for it to finish.")
        if data.condition == "auto":
            data = data.model_copy(
                update={"condition": "learned" if db.list("checkpoints") else "base"}
            )
        experience, checkpoint, prompt = prepare_review(data)
        job = db.create_job(
            "ufo_review", {"idempotency_key": request_key, "request_hash": request_hash}
        )
        db.update_job(job["id"], status="running")
        experience["external_id"] = request_key

        async def collect(event):
            await emit(job["id"], event)

        try:
            saved = await execute_review(experience, checkpoint, prompt, data.condition, collect)
            result = {
                "review": saved["agent_review"],
                "experience_id": saved["id"],
                "model": saved.get("model"),
                "checkpoint": saved.get("checkpoint"),
            }
            db.update_job(job["id"], status="completed", result=result)
            await emit(job["id"], {"type": "completed", "message": "UFO review saved."})
            return result
        except asyncio.CancelledError:
            db.update_job(
                job["id"],
                status="interrupted",
                error="UFO connection closed; inspect River before retrying.",
            )
            raise
        except Exception as exc:
            message = str(redact_secrets(str(exc)))[:1500]
            db.update_job(job["id"], status="failed", error=message)
            await emit(job["id"], {"type": "failed", "message": message})
            raise HTTPException(502, message) from None

    @app.post("/api/experiences/{experience_id}/feedback")
    async def feedback(experience_id: str, data: FeedbackInput):
        experience = db.get("experiences", experience_id)
        if not experience:
            raise HTTPException(404, "Experience not found.")
        if experience.get("split") != "train":
            raise HTTPException(409, "Held-out evaluation cases cannot become training feedback.")
        kind = (
            "confirmed_outcome"
            if (experience.get("agent_review") or {}).get("decision") == data.decision
            else "correction"
        )
        experience["human_feedback"] = {
            "decision": data.decision,
            "reason": data.reason,
            "issue_tags": data.issues,
            "approved": data.approved,
            "kind": kind,
            "created_at": utc_now(),
        }
        build_sft_examples(
            [experience, *[row for row in db.list("experiences") if row["id"] != experience_id]]
        )
        return db.save("experiences", experience)

    @app.post("/api/experiences/manual", status_code=201)
    async def manual(data: ManualInput):
        experience = data.model_dump(exclude={"decision", "reason", "issues", "approved"})
        experience["source"] = source_for(experience)
        experience["human_feedback"] = {
            "decision": data.decision,
            "reason": data.reason,
            "issue_tags": data.issues,
            "approved": data.approved,
            "kind": "correction",
        }
        experience = normalize_experience(experience)
        guard_held_out(experience)
        build_sft_examples([experience, *db.list("experiences")])
        return db.save("experiences", experience)

    @app.post("/api/experiences/import", status_code=201)
    async def import_experience(request: Request):
        check_integration_auth(request)
        from reflex.integrations.ufo import normalize_ufo_experience

        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(422, "Import body must be a JSON object containing experience.")
        raw = body.get("experience", {})
        data = normalize_ufo_experience(raw)
        guard_held_out(data)
        previous_id = raw.get("experience_id")
        if not previous_id:
            existing = next(
                (
                    row
                    for row in db.list("experiences")
                    if row.get("source") == "ufo"
                    and all(
                        row.get("ufo", {}).get(key) == data["ufo"].get(key)
                        for key in ("turn_id", "workspace_id")
                    )
                ),
                None,
            )
            previous_id = existing["id"] if existing else None
        if previous_id:
            previous = db.get("experiences", previous_id)
            if not previous:
                raise HTTPException(404, "The original UFO review was not found.")
            for key in ("turn_id", "workspace_id", "thread_id", "agent_id", "sdk_commit"):
                if not previous.get("ufo", {}).get(key) or previous["ufo"][key] != data.get(
                    "ufo", {}
                ).get(key):
                    raise HTTPException(
                        409, "UFO trajectory provenance does not match the original review."
                    )
            if content_fingerprint(previous) != content_fingerprint(data):
                raise HTTPException(409, "The imported trajectory contains a different patch.")
            data = {**previous, "trajectory": data["trajectory"], "ufo": data["ufo"]}
        return db.save("experiences", data)

    @app.get("/api/dataset/export")
    async def export_dataset():
        examples = build_sft_examples(db.list("experiences"))
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in examples)
        return StreamingResponse(
            iter([body]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="reflex-experiences.jsonl"'},
        )

    @app.get("/api/datasets/{dataset_id}/export")
    async def export_snapshot(dataset_id: str):
        dataset = db.get("datasets", dataset_id)
        if not dataset:
            raise HTTPException(404, "Training snapshot not found.")
        body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in dataset["examples"])
        return StreamingResponse(
            iter([body]),
            media_type="application/x-ndjson",
            headers={
                "Content-Disposition": 'attachment; filename="reflex-training-snapshot.jsonl"'
            },
        )

    @app.post("/api/training", status_code=202)
    async def training(data: TrainingInput):
        need_river()
        experiences = training_experiences()
        validate_no_leakage([*experiences, *HELD_OUT_PRS])
        examples = build_sft_examples(experiences)
        if len(examples) < 2:
            raise HTTPException(
                422,
                "Confirm at least two distinct training experiences first. Ten or more varied examples are recommended.",
            )
        snapshot = {
            "examples": examples,
            "fingerprint": digest(examples),
            "memory": build_memory(experiences),
        }

        async def run(job_id):
            db.save(
                "datasets",
                {"id": snapshot["fingerprint"], "examples": examples, "memory": snapshot["memory"]},
            )

            def persist_checkpoint(result, name, method, *, intermediate=False):
                return db.save(
                    "checkpoints",
                    {
                        "id": str(uuid4()),
                        "name": name,
                        **result,
                        "created_at": utc_now(),
                        "dataset_hash": snapshot["fingerprint"],
                        "experience_ids": [row["experience_id"] for row in examples],
                        "example_count": len(examples),
                        "memory": snapshot["memory"],
                        "method": method,
                        "intermediate": intermediate,
                        "training_job_id": job_id,
                    },
                )

            async def progress(event):
                if event.get("type") == "sft_checkpoint_saved":
                    saved = persist_checkpoint(
                        {
                            key: value
                            for key, value in event.items()
                            if key not in {"type", "message"}
                        },
                        f"{data.name}-sft",
                        "sft",
                        intermediate=True,
                    )
                    event = {
                        **event,
                        "checkpoint_id": saved["id"],
                        "message": "SFT weights saved. This checkpoint remains available if reward learning fails.",
                    }
                await emit(job_id, event)

            await emit(
                job_id,
                {
                    "type": "dataset",
                    "message": f"Frozen {len(examples)} confirmed examples. Held-out cases are excluded.",
                    "dataset_hash": snapshot["fingerprint"],
                },
            )
            result = await river.train(
                examples,
                name=data.name,
                method=data.method,
                on_event=progress,
            )
            return persist_checkpoint(result, data.name, data.method)

        return launch(
            "training",
            {
                "name": data.name,
                "method": data.method,
                "examples": len(examples),
                "dataset_hash": snapshot["fingerprint"],
            },
            run,
        )

    @app.post("/api/evaluations", status_code=202)
    async def evaluation(data: EvaluationInput):
        need_river()
        checkpoint = checkpoint_by_id(data.checkpoint)
        current_base = river.base_model
        if checkpoint.get("model") != current_base:
            raise HTTPException(
                409, "Set RIVER_BASE_MODEL to the checkpoint's base model before comparing results."
            )
        memory = checkpoint.get("memory", "")
        validate_no_leakage([*training_experiences(), *HELD_OUT_PRS])

        async def run(job_id):
            conditions = []
            memory_prompt_hashes = {}
            model_input_hashes = {}
            completed = 0
            total = len(HELD_OUT_PRS) * 3
            artifact = {
                "id": str(uuid4()),
                "checkpoint": checkpoint["checkpoint"],
                "checkpoint_id": checkpoint["id"],
                "conditions": conditions,
                "created_at": utc_now(),
                "model": current_base,
                "memory_hash": digest(memory),
                "matched_prompts": False,
                "dataset_hash": checkpoint["dataset_hash"],
                "status": "running",
                "eval_set_hash": digest(HELD_OUT_PRS),
                "case_count": len(HELD_OUT_PRS),
                "fixture_notice": "Fictional held-out engineering cases; measured decision accuracy on this small set only.",
            }
            db.save("evaluations", artifact)
            for condition in ("base", "memory", "learned"):
                results = []
                summary = {
                    "name": condition,
                    "correct": 0,
                    "total": 0,
                    "accuracy": 0.0,
                    "results": results,
                }
                conditions.append(summary)
                for case in HELD_OUT_PRS:
                    prompt = build_review_prompt(
                        case, memory=memory if condition != "base" else None
                    )
                    prompt_hash = digest(prompt)
                    if condition == "memory":
                        memory_prompt_hashes[case["id"]] = prompt_hash
                    elif condition == "learned" and memory_prompt_hashes[case["id"]] != prompt_hash:
                        raise RuntimeError(
                            "Evaluation stopped: memory and learned prompts diverged."
                        )
                    try:
                        review = await river.review(
                            prompt,
                            checkpoint=checkpoint["checkpoint"] if condition == "learned" else None,
                        )
                        token_hash = review.get("input_token_hash")
                        if condition == "memory" and token_hash:
                            model_input_hashes[case["id"]] = token_hash
                        if (
                            condition == "learned"
                            and token_hash
                            and model_input_hashes.get(case["id"], token_hash) != token_hash
                        ):
                            raise RuntimeError(
                                "Model-facing token inputs changed between memory and learned conditions."
                            )
                        score = score_review(review, case["gold"])
                        result = {
                            "case_id": case["id"],
                            "title": case["title"],
                            "review": review,
                            "score": score,
                            "prompt_hash": prompt_hash,
                        }
                    except RiverResponseError as exc:
                        # Invalid answers are model failures and remain in the denominator.
                        score = {
                            "correct_decision": False,
                            "decision_accuracy": 0.0,
                            "invalid_output": True,
                        }
                        result = {
                            "case_id": case["id"],
                            "title": case["title"],
                            "review": None,
                            "score": score,
                            "error": str(exc),
                            "prompt_hash": prompt_hash,
                        }
                    except asyncio.CancelledError:
                        artifact.update(
                            status="interrupted",
                            error="Server stopped. Partial results are preserved; no new samples will be submitted.",
                        )
                        db.save("evaluations", artifact)
                        raise
                    except Exception as exc:
                        artifact.update(status="failed", error=str(redact_secrets(str(exc)))[:1500])
                        db.save("evaluations", artifact)
                        raise
                    results.append(result)
                    completed += 1
                    summary.update(
                        correct=sum(bool(row["score"]["correct_decision"]) for row in results),
                        total=len(results),
                    )
                    summary["accuracy"] = summary["correct"] / summary["total"]
                    db.save("evaluations", artifact)
                    await emit(
                        job_id,
                        {
                            "type": "evaluation_case",
                            "message": f"{condition.capitalize()}: {case['title']}",
                            "condition": condition,
                            "completed": completed,
                            "total": total,
                            "correct": score["correct_decision"],
                        },
                    )
            artifact.update(
                status="completed",
                matched_prompts=True,
                prompt_hash=digest(memory_prompt_hashes),
                model_input_hash=digest(model_input_hashes),
                completed_at=utc_now(),
            )
            return db.save("evaluations", artifact)

        return launch(
            "evaluation", {"checkpoint": checkpoint["checkpoint"], "cases": len(HELD_OUT_PRS)}, run
        )

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = db.get("jobs", job_id)
        if not job:
            raise HTTPException(404, "Run not found.")
        return {**job, "events": db.list_events(job_id)}

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request):
        if not db.get("jobs", job_id):
            raise HTTPException(404, "Run not found.")
        try:
            cursor = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            cursor = 0

        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                events = db.list_events(job_id)
                for index, event in enumerate(events[cursor:], start=cursor + 1):
                    yield f"id: {index}\ndata: {json.dumps(event)}\n\n"
                    cursor = index
                job = db.get("jobs", job_id)
                if job and job.get("status") in TERMINAL:
                    break
                yield ": keepalive\n\n"
                await asyncio.sleep(0.6)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
        )

    return app


app = create_app()
