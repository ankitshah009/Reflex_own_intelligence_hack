"""Small async transport to Reflex, with bounded waits and no automatic inference retry."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

import httpx


class ReflexUnavailable(RuntimeError):
    pass


def base_url() -> str:
    value = os.environ.get("REFLEX_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ReflexUnavailable("REFLEX_URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ReflexUnavailable("REFLEX_URL cannot include credentials, a query, or a fragment")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ReflexUnavailable("Use HTTPS for a Reflex service outside this host")
    return value


async def post(path: str, payload: dict[str, Any], *, idempotency_key: str) -> dict[str, Any]:
    headers = {"Idempotency-Key": idempotency_key}
    token = os.environ.get("REFLEX_INGEST_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = httpx.Timeout(120.0, connect=5.0, pool=5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(base_url() + path, json=payload, headers=headers)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ReflexUnavailable(
            "Reflex timed out. Check the Reflex job/experience list before retrying inference."
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        hint = "Check REFLEX_INGEST_TOKEN in both processes." if status in {401, 403} else (
            "Check Reflex's service status and configured River credentials."
        )
        raise ReflexUnavailable(f"Reflex returned HTTP {status}. {hint}") from exc
    except httpx.RequestError as exc:
        raise ReflexUnavailable("Cannot reach Reflex. Start its API and check REFLEX_URL.") from exc
    if len(response.content) > 1_000_000:
        raise ReflexUnavailable("Reflex response exceeded 1 MB")
    try:
        result = response.json()
    except ValueError as exc:
        raise ReflexUnavailable("Reflex returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise ReflexUnavailable("Reflex returned an unexpected response shape")
    return result
