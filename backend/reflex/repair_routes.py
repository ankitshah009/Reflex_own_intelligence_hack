"""Executable repair workflow: observed outcomes, approved data, saved weights."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import time
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from reflex.core import redact_secrets, utc_now
from reflex.integrations.river import RiverResponseError, parse_repair
from reflex.repair_cases import get_case, held_out_cases, public_case, training_cases
from reflex.repair_engine import build_repair_prompt, code_diff, execute_case, isolation_status


class RepairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=200)
    condition: Literal["base", "memory", "learned", "auto"] = "base"
    checkpoint: str | None = None
    code: str | None = Field(default=None, min_length=1, max_length=32_000)
    provenance: dict[str, Any] | None = None
    trajectory: list[dict[str, Any]] = Field(default_factory=list, max_length=128)


class ReproduceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=32_000)
    events: list[dict[str, Any]] | None = Field(default=None, max_length=32)


class UFORepairInput(RepairInput):
    condition: Literal["base", "memory", "learned", "auto"] = "auto"


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    service: str = Field(default="Local handler", max_length=150)
    description: str = Field(min_length=1, max_length=3000)
    source: str = Field(min_length=1, max_length=32_000)
    initial_state: dict[str, Any]
    events: list[dict[str, Any]] = Field(min_length=1, max_length=32)
    expected_state: dict[str, Any]
    expected_results: list[Any] = Field(min_length=1, max_length=32)


class RepairFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repair_id: str
    code: str = Field(min_length=1, max_length=32_000)
    reason: str = Field(min_length=1, max_length=5000)
    approved: bool = True


class RepairTraining(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="reflex-repair-v1", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class RepairEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint: str


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def source_fingerprint(source: str) -> str:
    try:
        normalized = ast.dump(ast.parse(source), include_attributes=False)
    except SyntaxError:
        normalized = source.strip()
    return fingerprint(normalized)


def mount_repair_routes(app: FastAPI, db, river, launch, emit, need_river, check_auth) -> None:
    def guard_storable(value: Any, description: str):
        if redact_secrets(value) != value:
            raise HTTPException(
                422,
                f"{description} contains credential-like content that would be changed by redaction. "
                "Remove it before execution or saving; verified code must remain exact.",
            )

    def guard_report(code: str, report: dict[str, Any]):
        expected = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if report.get("code_hash") != expected:
            raise HTTPException(
                422,
                "The execution report does not match this exact handler source. "
                "Verify and accept the repair again before exporting or training.",
            )

    def load_case(case_id: str):
        case = db.get("repair_cases", case_id) or get_case(case_id)
        if case is None:
            raise HTTPException(404, "Repair case not found. Choose a case or create one first.")
        guard_storable(case, "Repair case")
        return case

    def guard_source(source: str):
        if source_fingerprint(source) in {
            source_fingerprint(case["source"]) for case in held_out_cases()
        }:
            raise HTTPException(
                422, "This handler belongs to the held-out suite and cannot enter training."
            )

    def checkpoint_for(identifier: str | None):
        rows = db.list("repair_checkpoints")
        row = (
            next((item for item in rows if identifier in {item["id"], item["checkpoint"]}), None)
            if identifier
            else next(iter(rows), None)
        )
        if row is None:
            raise HTTPException(
                404, "Train and save a repair checkpoint before selecting learned weights."
            )
        if row.get("model") != river.base_model:
            raise HTTPException(
                409,
                "The repair checkpoint uses a different base model. Restore its RIVER_BASE_MODEL before sampling.",
            )
        return row

    def dataset():
        examples, seen = [], {}
        for repair in db.list("repairs"):
            feedback = repair.get("human_feedback") or {}
            feedback_source = "operator_accepted"
            if not feedback.get("approved"):
                feedback = repair.get("machine_feedback") or {}
                feedback_source = "river_generated_execution_verified"
                if feedback.get("approved"):
                    job_id = feedback.get("curriculum_job_id")
                    job = db.get("jobs", job_id) if isinstance(job_id, str) else None
                    report = repair.get("accepted_report") or {}
                    isolation = report.get("isolation") or {}
                    if (
                        feedback.get("source") != feedback_source
                        or job is None
                        or job.get("kind") != "repair_curriculum"
                        or job_id != repair.get("job_id")
                        or feedback.get("code") != repair.get("agent_code")
                        or feedback.get("code") != repair.get("code")
                        or repair.get("baseline_report", {}).get("status") != "failed"
                        or not isinstance(isolation, dict)
                        or isolation.get("enforced") is not True
                    ):
                        raise HTTPException(
                            422, "Generated repair provenance is invalid. Generate and verify the repair again before training."
                        )
            if (
                not feedback.get("approved")
                or repair.get("accepted_report", {}).get("status") != "passed"
            ):
                continue
            case = load_case(repair["case_id"])
            guard_source(case["source"])
            identity = source_fingerprint(case["source"])
            code = feedback["code"]
            guard_storable(code, "Accepted handler source")
            guard_report(code, repair["accepted_report"])
            if identity in seen:
                if seen[identity] != code:
                    raise HTTPException(
                        422,
                        "Conflicting accepted repairs target the same handler. Unapprove one before training.",
                    )
                continue
            seen[identity] = code
            examples.append(
                {
                    "experience_id": repair["id"],
                    "feedback_source": feedback_source,
                    "case_id": case["id"],
                    "source_fingerprint": identity,
                    "prompt": build_repair_prompt(case),
                    "completion": json.dumps(
                        {"summary": feedback["reason"], "code": code}, ensure_ascii=False
                    ),
                }
            )
        guard_storable(examples, "Training examples")
        return examples

    def memory_for(examples):
        parts = []
        for example in examples[:8]:
            answer = json.loads(example["completion"])
            parts.append(
                "Previously accepted repair:\n" + answer["summary"] + "\n" + answer["code"]
            )
        return "\n\n".join(parts)[:12_000]

    def frozen_dataset(checkpoint):
        dataset_hash = checkpoint.get("dataset_hash")
        snapshot = db.get("datasets", dataset_hash) if isinstance(dataset_hash, str) else None
        error = "The repair checkpoint's frozen dataset is missing or invalid. Restore its original snapshot before evaluation."
        if (
            checkpoint.get("task_kind") != "repair"
            or not isinstance(snapshot, dict)
            or snapshot.get("task_kind") != "repair"
            or snapshot.get("id") != dataset_hash
        ):
            raise HTTPException(409, error)
        examples = snapshot.get("examples")
        if (
            not isinstance(examples, list)
            or not 2 <= len(examples) <= 32
            or fingerprint(examples) != dataset_hash
            or checkpoint.get("example_count") != len(examples)
        ):
            raise HTTPException(409, error)
        identities = set()
        for example in examples:
            if not isinstance(example, dict) or any(
                not isinstance(example.get(key), str) or not example[key].strip()
                for key in (
                    "experience_id", "case_id", "source_fingerprint", "prompt", "completion"
                )
            ):
                raise HTTPException(409, error)
            identity = example["source_fingerprint"]
            if (
                len(identity) != 64
                or any(character not in "0123456789abcdef" for character in identity)
                or identity in identities
            ):
                raise HTTPException(409, error)
            identities.add(identity)
            try:
                parse_repair(example["completion"], checkpoint["model"])
            except RiverResponseError:
                raise HTTPException(409, error) from None
        memory = snapshot.get("memory")
        if (
            redact_secrets(examples) != examples
            or not isinstance(memory, str)
            or memory != memory_for(examples)
            or memory != checkpoint.get("memory")
            or checkpoint.get("experience_ids") != [item["experience_id"] for item in examples]
        ):
            raise HTTPException(409, error)
        return examples, memory

    @app.get("/api/repairs/state")
    async def repair_state():
        repairs = db.list("repairs")
        checkpoints = db.list("repair_checkpoints")
        jobs = [job for job in db.list("jobs") if job["kind"].startswith(("repair", "ufo_repair"))]
        training_error = None
        try:
            eligible = dataset()
        except HTTPException as error:
            eligible = []
            training_error = str(error.detail)
        return {
            "cases": [public_case(case) for case in [*db.list("repair_cases"), *training_cases()]],
            "repairs": repairs,
            "checkpoints": checkpoints,
            "evaluations": db.list("repair_evaluations"),
            "jobs": jobs,
            "training_error": training_error,
            "provider": {
                "configured": river.configured,
                "model": river.base_model,
                "verified": any(
                    job["status"] == "completed"
                    and job.get("payload", {}).get("origin") != "manual"
                    for job in jobs
                ),
            },
            "stats": {
                "attempts": len(repairs),
                "eligible": len(eligible),
                "machine_verified": sum(
                    row.get("feedback_source") == "river_generated_execution_verified"
                    for row in eligible
                ),
                "accepted": sum(
                    bool(row.get("human_feedback", {}).get("approved")) for row in repairs
                ),
                "checkpoints": len(checkpoints),
            },
        }

    @app.post("/api/repairs/cases", status_code=201)
    async def create_case(data: CaseInput):
        guard_storable(data.model_dump(), "Custom repair case")
        if len(data.events) != len(data.expected_results):
            raise HTTPException(422, "Provide one expected response for each event.")
        guard_source(data.source)
        case = {
            "id": f"custom-{uuid4()}",
            "title": data.title,
            "service": data.service,
            "description": data.description,
            "filename": "handler.py",
            "source": data.source,
            "initial_state": data.initial_state,
            "reproduction": data.events,
            "actions": [
                {"id": f"event-{index + 1}", "label": f"Send event {index + 1}", "payload": event}
                for index, event in enumerate(data.events)
            ],
            "expected_behavior": data.description,
            "source_kind": "manual",
            "language": "python",
            "_checks": [
                {
                    "name": "Reported customer flow",
                    "initial_state": data.initial_state,
                    "events": data.events,
                    "expected_state": data.expected_state,
                    "expected_results": data.expected_results,
                }
            ],
        }
        return public_case(db.save("repair_cases", case))

    @app.post("/api/repairs/reproduce")
    async def reproduce(data: ReproduceInput):
        case = load_case(data.case_id)
        code = data.code if data.code is not None else case["source"]
        guard_storable(code, "Handler source")
        return await asyncio.to_thread(
            execute_case, case, code, data.events
        )

    async def perform_repair(data: RepairInput, job_id: str):
        case = load_case(data.case_id)
        guard_source(case["source"])
        condition = data.condition
        if condition == "auto":
            condition = "learned" if db.list("repair_checkpoints") else "base"
        checkpoint = checkpoint_for(data.checkpoint) if condition == "learned" else None
        memory = (
            checkpoint["memory"]
            if checkpoint
            else memory_for(dataset())
            if condition == "memory"
            else ""
        )
        prompt = build_repair_prompt(case, memory=memory)
        await emit(
            job_id,
            {"type": "context", "message": f"Loaded {case['filename']} and the reported failure."},
        )
        started = time.monotonic()
        baseline = await asyncio.to_thread(execute_case, case, case["source"])
        await emit(
            job_id,
            {
                "type": "reproduced",
                "message": f"Original handler: {baseline['passed']}/{baseline['total']} checks passed.",
                "report": baseline,
            },
        )
        if baseline.get("status") == "error":
            raise ValueError(
                "The original handler could not be executed. Resolve its reported execution error before submitting a model request."
            )
        if data.code is None:
            await emit(
                job_id,
                {"type": "sampling", "message": "River is generating a replacement handler."},
            )
            answer = await river.repair(
                prompt, checkpoint=checkpoint["checkpoint"] if checkpoint else None
            )
        else:
            answer = {
                "code": data.code,
                "summary": "Developer-supplied candidate repair.",
                "model": "manual",
            }
        guard_storable(answer["code"], "Candidate handler source")
        await emit(
            job_id,
            {"type": "verifying", "message": "Executing the candidate against behavioral checks."},
        )
        report = await asyncio.to_thread(execute_case, case, answer["code"])
        guard_report(answer["code"], report)
        row = db.save(
            "repairs",
            {
                "id": str(uuid4()),
                "case_id": case["id"],
                "title": case["title"],
                "source": case["source"],
                "code": answer["code"],
                "summary": answer["summary"],
                "agent_code": answer["code"],
                "agent_report": report,
                "diff": code_diff(case["source"], answer["code"]),
                "report": report,
                "baseline_report": baseline,
                "condition": condition,
                "origin": "manual" if data.code is not None else "river",
                "model": answer["model"],
                "checkpoint": checkpoint["checkpoint"] if checkpoint else None,
                "prompt_hash": fingerprint(prompt),
                "input_token_hash": answer.get("input_token_hash"),
                "tokenizer_revision": answer.get("tokenizer_revision"),
                "generation": answer.get("generation"),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "job_id": job_id,
                "ufo": data.provenance,
                "trajectory": data.trajectory,
            },
        )
        await emit(
            job_id,
            {
                "type": "repair_saved",
                "message": f"Candidate saved: {report['passed']}/{report['total']} checks passed. Inspect before accepting.",
                "repair_id": row["id"],
            },
        )
        return row

    @app.post("/api/repairs/run", status_code=202)
    async def run_repair(data: RepairInput):
        if data.provenance or data.trajectory:
            raise HTTPException(
                422, "Runtime provenance is accepted only through the UFO endpoint."
            )
        if data.condition == "auto":
            raise HTTPException(422, "Choose a model condition explicitly in the workspace.")
        load_case(data.case_id)
        if data.code is not None:
            guard_storable(data.code, "Candidate handler source")
        if data.code is None:
            need_river()
        if data.condition == "learned":
            checkpoint_for(data.checkpoint)
        return launch(
            "repair",
            {
                "case_id": data.case_id,
                "condition": data.condition,
                "origin": "manual" if data.code is not None else "river",
            },
            lambda job_id: perform_repair(data, job_id),
        )

    @app.post("/api/repairs/feedback")
    async def repair_feedback(data: RepairFeedback):
        row = db.get("repairs", data.repair_id)
        if row is None:
            raise HTTPException(404, "Repair not found.")
        case = load_case(row["case_id"])
        guard_source(case["source"])
        guard_storable(data.code, "Accepted handler source")
        report = await asyncio.to_thread(execute_case, case, data.code)
        guard_report(data.code, report)
        if data.approved and report.get("status") != "passed":
            raise HTTPException(
                422,
                "This repair does not pass its behavioral checks. Correct the code and verify it before accepting.",
            )
        # UFO can finish importing this turn while its handler checks run.
        # Merge only feedback fields into the newest observable trajectory.
        row = db.get("repairs", data.repair_id)
        if row is None:
            raise HTTPException(404, "Repair not found.")
        row.update(
            code=data.code,
            diff=code_diff(case["source"], data.code),
            report=report,
            accepted_report=report,
            human_feedback={
                "approved": data.approved,
                "reason": data.reason,
                "code": data.code,
                "confirmed_at": utc_now(),
            },
        )
        return db.save("repairs", row)

    @app.get("/api/repairs/export")
    async def export_repairs():
        content = "\n".join(json.dumps(example, ensure_ascii=False) for example in dataset())
        return Response(
            content + ("\n" if content else ""),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="reflex-repairs.jsonl"'},
        )

    @app.post("/api/repairs/train", status_code=202)
    async def train_repairs(data: RepairTraining):
        need_river()
        examples = dataset()
        if not 2 <= len(examples) <= 32:
            raise HTTPException(
                422,
                "Accept 2–32 distinct passing repairs before training. Use varied failures and keep held-out cases separate.",
            )
        if any(
            row.get("name") == data.name
            for kind in ("checkpoints", "repair_checkpoints")
            for row in db.list(kind)
        ):
            raise HTTPException(
                409, "Choose a new checkpoint name; saved checkpoints are immutable."
            )
        memory = memory_for(examples)
        dataset_hash = fingerprint(examples)

        async def train(job_id):
            db.save(
                "datasets",
                {"id": dataset_hash, "examples": examples, "memory": memory, "task_kind": "repair"},
            )
            await emit(
                job_id,
                {
                    "type": "dataset",
                    "message": f"Frozen {len(examples)} accepted repairs for SFT.",
                    "dataset_hash": dataset_hash,
                },
            )
            result = await river.train(
                examples, name=data.name, method="sft", on_event=lambda event: emit(job_id, event)
            )
            return db.save(
                "repair_checkpoints",
                {
                    "id": str(uuid4()),
                    **result,
                    "name": data.name,
                    "method": "sft",
                    "task_kind": "repair",
                    "dataset_hash": dataset_hash,
                    "memory": memory,
                    "example_count": len(examples),
                    "experience_ids": [example["experience_id"] for example in examples],
                    "training_job_id": job_id,
                },
            )

        return launch(
            "repair_training",
            {"name": data.name, "examples": len(examples), "dataset_hash": dataset_hash},
            train,
        )

    @app.post("/api/repairs/evaluate", status_code=202)
    async def evaluate_repairs(data: RepairEvaluation):
        need_river()
        checkpoint = checkpoint_for(data.checkpoint)
        cases = held_out_cases()
        examples, memory = frozen_dataset(checkpoint)
        for example in examples:
            if example["source_fingerprint"] in {
                source_fingerprint(case["source"]) for case in cases
            }:
                raise HTTPException(422, "Held-out handler overlap detected in training data.")

        async def evaluate(job_id):
            artifact = {
                "id": str(uuid4()),
                "status": "running",
                "task_kind": "repair",
                "checkpoint": checkpoint["checkpoint"],
                "checkpoint_id": checkpoint["id"],
                "model": river.base_model,
                "dataset_hash": checkpoint["dataset_hash"],
                "eval_set_hash": fingerprint(cases),
                "memory_hash": fingerprint(memory),
                "case_count": len(cases),
                "conditions": [],
                "matched_prompts": False,
                "job_id": job_id,
                "fixture_notice": "Synthetic held-out event handlers. This is a bounded repair benchmark, not production performance.",
            }
            db.save("repair_evaluations", artifact)
            prompt_hashes, token_hashes = {}, {}
            try:
                isolation = await asyncio.to_thread(isolation_status)
                if not isolation.get("enforced"):
                    raise ValueError(
                        "Isolated repair execution is unavailable. No evaluation samples were requested."
                    )
                for condition in ("base", "memory", "learned"):
                    summary = {
                        "name": condition,
                        "passed": 0,
                        "total": 0,
                        "success_rate": 0.0,
                        "results": [],
                    }
                    artifact["conditions"].append(summary)
                    for case in cases:
                        prompt = build_repair_prompt(
                            case, memory=memory if condition != "base" else ""
                        )
                        prompt_hash = fingerprint(prompt)
                        if condition == "memory":
                            prompt_hashes[case["id"]] = prompt_hash
                        if condition == "learned" and prompt_hashes[case["id"]] != prompt_hash:
                            raise ValueError(
                                "Memory and learned repair prompts diverged; comparison stopped."
                            )
                        if condition == "learned" and case["id"] not in token_hashes:
                            raise ValueError("Memory input-token provenance is missing; learned comparison stopped.")
                        started = time.monotonic()
                        row = {
                            "case_id": case["id"],
                            "title": case["title"],
                            "prompt_hash": prompt_hash,
                        }
                        try:
                            answer = await river.repair(
                                prompt,
                                checkpoint=checkpoint["checkpoint"]
                                if condition == "learned"
                                else None,
                            )
                            token_hash = answer.get("input_token_hash")
                            if not isinstance(token_hash, str) or not token_hash:
                                raise ValueError(
                                    "The model did not return input-token provenance; comparison stopped."
                                )
                            if condition == "memory" and token_hash:
                                token_hashes[case["id"]] = token_hash
                            if (
                                condition == "learned"
                                and token_hash
                                and token_hashes[case["id"]] != token_hash
                            ):
                                raise ValueError(
                                    "Model input tokens changed between memory and learned repairs."
                                )
                            guard_storable(answer["code"], "Candidate handler source")
                            report = await asyncio.to_thread(execute_case, case, answer["code"])
                            guard_report(answer["code"], report)
                            row.update(
                                report=report,
                                code=answer["code"],
                                summary=answer["summary"],
                                input_token_hash=token_hash,
                            )
                        except RiverResponseError as error:
                            token_hash = getattr(error, "input_token_hash", None)
                            if condition == "memory" and isinstance(token_hash, str) and token_hash:
                                token_hashes[case["id"]] = token_hash
                            if condition == "learned" and token_hashes[case["id"]] != token_hash:
                                raise ValueError("Malformed learned output has no matching input-token provenance.") from None
                            row.update(
                                report={
                                    "status": "failed",
                                    "passed": 0,
                                    "total": 0,
                                    "checks": [],
                                    "preview": {"state": {}, "results": []},
                                },
                                error=str(error),
                                invalid_output=True,
                                input_token_hash=token_hash,
                            )
                        row["duration_ms"] = round((time.monotonic() - started) * 1000)
                        summary["results"].append(row)
                        summary["total"] += 1
                        summary["passed"] += int(row["report"]["status"] == "passed")
                        summary["success_rate"] = summary["passed"] / summary["total"]
                        db.save("repair_evaluations", artifact)
                        await emit(
                            job_id,
                            {
                                "type": "evaluation_case",
                                "message": f"{condition.capitalize()}: {case['title']} — {row['report']['status']}",
                                "condition": condition,
                                "completed": sum(item["total"] for item in artifact["conditions"]),
                                "total": len(cases) * 3,
                            },
                        )
            except BaseException as error:
                artifact.update(
                    status="interrupted" if isinstance(error, asyncio.CancelledError) else "failed",
                    error=str(redact_secrets(str(error)))[:1500]
                    or "Evaluation interrupted; partial results preserved.",
                )
                db.save("repair_evaluations", artifact)
                raise
            artifact.update(
                status="completed",
                matched_prompts=True,
                prompt_hash=fingerprint(prompt_hashes),
                model_input_hash=fingerprint(token_hashes),
                completed_at=utc_now(),
            )
            return db.save("repair_evaluations", artifact)

        return launch(
            "repair_evaluation",
            {"checkpoint": checkpoint["checkpoint"], "cases": len(cases)},
            evaluate,
        )

    def validate_provenance(value):
        if not isinstance(value, dict):
            raise HTTPException(422, "UFO runtime provenance is required.")
        for key in ("workspace_id", "turn_id", "thread_id", "agent_id"):
            try:
                UUID(str(value.get(key)))
            except ValueError:
                raise HTTPException(422, f"UFO provenance requires a valid {key} UUID.") from None
        from reflex.integrations.ufo import UFO_SDK_COMMIT

        if value.get("sdk_commit") != UFO_SDK_COMMIT:
            raise HTTPException(422, "The UFO SDK revision does not match this integration.")

    @app.post("/api/repairer")
    async def ufo_repair(data: UFORepairInput, request: Request):
        check_auth(request)
        validate_provenance(data.provenance)
        if data.code is not None:
            raise HTTPException(422, "UFO repair calls cannot supply developer-approved code.")
        key = request.headers.get("idempotency-key")
        if not key or len(key) > 250:
            raise HTTPException(422, "UFO repair calls require an Idempotency-Key header.")
        payload_hash = fingerprint(data.model_dump(exclude={"trajectory"}))
        job = next(
            (
                row
                for row in db.list("jobs")
                if row.get("payload", {}).get("idempotency_key") == key
            ),
            None,
        )
        if job:
            if job["payload"].get("request_hash") != payload_hash or job["kind"] != "ufo_repair":
                raise HTTPException(409, "This idempotency key belongs to another request.")
            if job["status"] != "completed":
                raise HTTPException(
                    409,
                    "This repair request already exists. Inspect its job before requesting another model call.",
                )
            row = job["result"]
        else:
            need_river()
            load_case(data.case_id)
            submitted = launch(
                "ufo_repair",
                {"idempotency_key": key, "request_hash": payload_hash, "case_id": data.case_id},
                lambda job_id: perform_repair(data, job_id),
            )
            while True:
                job = db.get("jobs", submitted["job_id"])
                if job["status"] in {"failed", "interrupted"}:
                    raise HTTPException(
                        502,
                        job.get("error") or "Repair failed; inspect the saved job before retrying.",
                    )
                if job["status"] == "completed":
                    break
                await asyncio.sleep(0.1)
            row = job["result"]
        return {
            "experience_id": row["id"],
            "repair": row,
            "model": row["model"],
            "checkpoint": row["checkpoint"],
        }

    @app.post("/api/repairs/import")
    async def import_repair(request: Request):
        check_auth(request)
        data = await request.json()
        value = data.get("experience") if isinstance(data, dict) else None
        if not isinstance(value, dict) or set(value) - {
            "experience_id",
            "case_id",
            "source",
            "ufo",
            "trajectory",
        }:
            raise HTTPException(
                422,
                "Import only observable repair provenance and trajectory; feedback must come from the developer.",
            )
        validate_provenance(value.get("ufo"))
        row = db.get("repairs", str(value.get("experience_id", "")))
        if row is None:
            raise HTTPException(404, "The original repair experience was not found.")
        if (
            value.get("source") != "ufo"
            or row.get("ufo") != value["ufo"]
            or row["case_id"] != value.get("case_id")
        ):
            raise HTTPException(
                409, "This trajectory does not match the saved repair and UFO turn."
            )
        trajectory = value.get("trajectory")
        if not isinstance(trajectory, list) or len(trajectory) > 128:
            raise HTTPException(422, "Provide at most 128 observable events.")
        safe = []
        for event in trajectory:
            if (
                not isinstance(event, dict)
                or not isinstance(event.get("type"), str)
                or event.get("type")
                not in {
                    "instruction",
                    "tool_result",
                    "answer",
                }
            ):
                raise HTTPException(
                    422,
                    "Only observable instruction, tool_result, and answer events may be imported.",
                )
            if any(
                not isinstance(event[key], bool if key == "is_error" else str)
                for key in {"tool", "input", "message", "is_error", "timestamp"}.intersection(event)
            ):
                raise HTTPException(
                    422, "Observable event fields must be strings, with a boolean is_error flag."
                )
            safe.append(
                {
                    key: redact_secrets(value[:4096] if isinstance(value, str) else value)
                    for key, value in event.items()
                    if key in {"type", "tool", "input", "message", "is_error", "timestamp"}
                }
            )
        row["trajectory"] = safe
        return db.save("repairs", row)
