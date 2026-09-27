"""Bounded River-generated repairs with execution-verified training provenance."""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from reflex.core import redact_secrets, utc_now
from reflex.curriculum import generate_curriculum
from reflex.integrations.river import RiverResponseError
from reflex.repair_cases import held_out_cases
from reflex.repair_engine import (
    build_repair_prompt,
    code_diff,
    execute_case,
    isolation_status,
)
from reflex.repair_routes import source_fingerprint


class CurriculumInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=24, ge=1, le=24)
    concurrency: int = Field(default=3, ge=1, le=4)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value: Any) -> bool:
    """Persisting a checked program must never change its source bytes."""
    return redact_secrets(value) == value


def _error_report(code: str, detail: str) -> dict[str, Any]:
    return {
        "status": "error",
        "passed": 0,
        "total": 0,
        "checks": [],
        "preview": {"state": {}, "results": [], "error": detail},
        "duration_ms": 0,
        "code_hash": _sha256(code),
        "error": detail,
    }


def mount_curriculum_routes(app, db, river, launch, emit, need_river):
    @app.get("/api/curriculum/state")
    async def curriculum_state():
        jobs = [job for job in db.list("jobs") if job.get("kind") == "repair_curriculum"]
        attempts = [
            row for row in db.list("repairs") if row.get("curriculum_job_id")
        ]
        verified = sum(
            1
            for row in attempts
            if row.get("machine_feedback", {}).get("approved") is True
        )
        return {
            "jobs": jobs,
            "stats": {
                "attempts": len(attempts),
                "verified": verified,
                "failed": len(attempts) - verified,
            },
            "limits": {"max_count": 24, "max_concurrency": 4},
            "provenance": "Synthetic variants of six repair families; River-generated fixes verified by executable checks.",
        }

    @app.post("/api/curriculum/generate", status_code=202)
    async def generate(data: CurriculumInput):
        need_river()
        cases = generate_curriculum(count=data.count, seed=data.seed)
        if len(cases) != data.count:
            raise HTTPException(422, "Curriculum returned an unexpected case count.")

        held_out_fingerprints = {
            source_fingerprint(case["source"]) for case in held_out_cases()
        }
        seen_fingerprints: set[str] = set()
        seen_ids: set[str] = set()
        for case in cases:
            fingerprint = source_fingerprint(case["source"])
            if fingerprint in held_out_fingerprints:
                raise HTTPException(422, "Curriculum overlaps a held-out source.")
            if fingerprint in seen_fingerprints or case["id"] in seen_ids:
                raise HTTPException(422, "Curriculum contains a duplicate source or case ID.")
            if case.get("_split") not in (None, "train"):
                raise HTTPException(422, "Only training cases belong in the curriculum.")
            if not _clean(case):
                raise HTTPException(
                    422,
                    "Curriculum contains credential-like literals; remove them before generating repairs.",
                )
            seen_fingerprints.add(fingerprint)
            seen_ids.add(case["id"])

        async def work(job_id: str):
            isolation = await asyncio.to_thread(isolation_status)
            if isolation.get("enforced") is not True:
                raise RuntimeError(
                    "Repair isolation is unavailable. No River generation requests were submitted."
                )

            counters = {"completed": 0, "verified": 0, "failed": 0, "submitted": 0}
            stop = asyncio.Event()
            pending = iter(cases)
            transport_errors: list[str] = []
            await emit(
                job_id,
                {
                    "type": "curriculum_started",
                    "count": len(cases),
                    "concurrency": data.concurrency,
                    "seed": data.seed,
                    "provenance": "river_generated_execution_verified",
                },
            )

            async def attempt(case: dict[str, Any]):
                started = time.monotonic()
                db.save("repair_cases", deepcopy(case))
                prompt = build_repair_prompt(case)
                repair_id = str(uuid.uuid4())
                row: dict[str, Any] = {
                    "id": repair_id,
                    "case_id": case["id"],
                    "title": case["title"],
                    "source": case["source"],
                    "code": "",
                    "summary": "",
                    "agent_code": "",
                    "condition": "base",
                    "origin": "river",
                    "model": getattr(river, "base_model", None),
                    "checkpoint": None,
                    "prompt_hash": _sha256(prompt),
                    "input_token_hash": None,
                    "tokenizer_revision": None,
                    "generation": None,
                    "provider_submitted": False,
                    "job_id": job_id,
                    "curriculum_job_id": job_id,
                    "ufo": None,
                    "trajectory": [],
                    "provenance": {
                        "source": "river_generated_execution_verified",
                        "case_kind": "synthetic_variant",
                        "seed": data.seed,
                    },
                }
                baseline = await asyncio.to_thread(execute_case, case, case["source"])
                row["baseline_report"] = baseline
                report = _error_report("", "No candidate was generated.")
                if baseline.get("status") != "failed":
                    report = _error_report(
                        "", "Original source must fail its checks before generating a repair."
                    )
                elif baseline.get("code_hash") != _sha256(case["source"]):
                    report = _error_report("", "Baseline report does not match the source hash.")
                elif stop.is_set():
                    report = _error_report("", "Generation stopped after a provider failure.")
                else:
                    counters["submitted"] += 1
                    row["provider_submitted"] = True
                    await emit(
                        job_id,
                        {
                            "type": "curriculum_case_started",
                            "case_id": case["id"],
                            "title": case["title"],
                            **counters,
                            "total": len(cases),
                        },
                    )
                    try:
                        answer = await river.repair(prompt)
                    except RiverResponseError as exc:
                        report = _error_report("", "River returned an invalid repair response.")
                        row["input_token_hash"] = getattr(exc, "input_token_hash", None)
                        row["tokenizer_revision"] = getattr(exc, "tokenizer_revision", None)
                        row["generation"] = getattr(exc, "generation", None)
                    except asyncio.CancelledError:
                        report = _error_report(
                            "", "Curriculum cancelled while a provider request was in flight."
                        )
                        row.update(
                            report=report,
                            agent_report=report,
                            diff="",
                            duration_ms=round((time.monotonic() - started) * 1000),
                        )
                        db.save("repairs", row)
                        raise
                    except Exception:
                        stop.set()
                        transport_errors.append(case["id"])
                        report = _error_report(
                            "", "River request failed. New generation requests have been stopped."
                        )
                    else:
                        if not isinstance(answer, dict):
                            answer = {}
                        code = answer.get("code")
                        summary = answer.get("summary")
                        row.update(
                            model=answer.get("model", row["model"]),
                            input_token_hash=answer.get("input_token_hash"),
                            tokenizer_revision=answer.get("tokenizer_revision"),
                            generation=answer.get("generation"),
                        )
                        if (
                            not isinstance(code, str)
                            or not code.strip()
                            or len(code) > 32_000
                            or not isinstance(summary, str)
                            or not summary.strip()
                        ):
                            report = _error_report("", "River returned an invalid repair response.")
                        elif not _clean(code):
                            report = _error_report(
                                "", "Generated source contains credential-like literals and was rejected."
                            )
                        else:
                            row.update(code=code, agent_code=code, summary=redact_secrets(summary))
                            report = await asyncio.to_thread(execute_case, case, code)
                            if report.get("code_hash") != _sha256(code):
                                report = _error_report(
                                    code, "Execution report does not match the generated source hash."
                                )
                            elif (
                                report.get("status") == "passed"
                                and isinstance(report.get("total"), int)
                                and report["total"] > 0
                                and report.get("passed") == report["total"]
                                and report.get("isolation", {}).get("enforced") is True
                            ):
                                row["accepted_report"] = report
                                row["machine_feedback"] = {
                                    "approved": True,
                                    "code": code,
                                    "reason": row["summary"],
                                    "source": "river_generated_execution_verified",
                                    "curriculum_job_id": job_id,
                                    "code_hash": report["code_hash"],
                                    "created_at": utc_now(),
                                }

                row.update(
                    report=report,
                    agent_report=report,
                    diff=code_diff(case["source"], row["code"]) if row["code"] else "",
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                saved = db.save("repairs", row)
                verified = saved.get("machine_feedback", {}).get("approved") is True
                counters["completed"] += 1
                counters["verified" if verified else "failed"] += 1
                await emit(
                    job_id,
                    {
                        "type": "curriculum_case_completed",
                        "case_id": case["id"],
                        "repair_id": repair_id,
                        "status": report["status"],
                        "training_eligible": verified,
                        "passed": report.get("passed", 0),
                        "checks": report.get("total", 0),
                        **counters,
                        "total": len(cases),
                    },
                )

            async def worker():
                while not stop.is_set():
                    case = next(pending, None)
                    if case is None:
                        return
                    try:
                        await attempt(case)
                    except BaseException:
                        stop.set()
                        raise

            workers = [
                asyncio.create_task(worker())
                for _ in range(min(data.concurrency, len(cases)))
            ]
            try:
                outcomes = await asyncio.gather(*workers, return_exceptions=True)
            except asyncio.CancelledError:
                stop.set()
                for worker_task in workers:
                    worker_task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                raise
            for outcome in outcomes:
                if isinstance(outcome, BaseException):
                    raise outcome
            result = {**counters, "requested": len(cases), "seed": data.seed}
            if transport_errors:
                await emit(job_id, {"type": "curriculum_stopped", **result})
                raise RuntimeError(
                    "River generation stopped after a provider transport failure; completed attempts were retained. "
                    "Review the saved job before explicitly starting another generation run."
                )
            await emit(job_id, {"type": "curriculum_completed", **result})
            return result

        return launch("repair_curriculum", data.model_dump(), work)
