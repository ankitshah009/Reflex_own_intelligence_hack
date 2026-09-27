"""Small transactional SQLite store for the complete Reflex learning loop."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .core import LeakageError, ValidationError, normalize_experience, redact_secrets, utc_now


KINDS = {
    "experiences",
    "jobs",
    "checkpoints",
    "evaluations",
    "datasets",
    "repairs",
    "repair_cases",
    "repair_checkpoints",
    "repair_evaluations",
}
_ALIASES = {
    "experience": "experiences",
    "job": "jobs",
    "checkpoint": "checkpoints",
    "evaluation": "evaluations",
    "dataset": "datasets",
}


class Store:
    """Thread-safe writes, persistent event ordering, and split leakage checks.

    Each mutation holds a BEGIN IMMEDIATE transaction. This makes the leakage
    check and corresponding experience write atomic, even across processes.
    """

    def __init__(self, path: str | Path = "data/reflex.sqlite3") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path, timeout=10, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 10000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS experiences (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                split TEXT NOT NULL CHECK(split IN ('train', 'eval')),
                content_fingerprint TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS experiences_fingerprint ON experiences(content_fingerprint);
            CREATE INDEX IF NOT EXISTS experiences_split_created ON experiences(split, created_at);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, data TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS checkpoints (
                id TEXT PRIMARY KEY, data TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY, data TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY, data TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_job_id ON events(job_id, id);
        """)
        for kind in ("repairs", "repair_cases", "repair_checkpoints", "repair_evaluations"):
            self._connection.execute(
                f"CREATE TABLE IF NOT EXISTS {kind} (id TEXT PRIMARY KEY, data TEXT NOT NULL, "
                "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )

    @staticmethod
    def _kind(kind: str) -> str:
        kind = _ALIASES.get(kind, kind)
        if kind not in KINDS:
            raise ValidationError(
                f"Unknown entity kind {kind!r}; expected one of {', '.join(sorted(KINDS))}"
            )
        return kind

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def save(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        """Insert or replace an entity; dataset snapshots are immutable."""
        kind = self._kind(kind)
        if not isinstance(data, dict):
            raise ValidationError("entity data must be an object")
        item = normalize_experience(data) if kind == "experiences" else redact_secrets(dict(data))
        item["id"] = str(item.get("id") or uuid4())
        item["created_at"] = item.get("created_at") or utc_now()
        item["updated_at"] = utc_now()
        with self._write() as connection:
            existing = connection.execute(
                f"SELECT data, created_at FROM {kind} WHERE id = ?", (item["id"],)
            ).fetchone()
            if kind == "datasets" and existing:
                persisted = json.loads(existing["data"])
                candidate = redact_secrets(dict(data))
                candidate["id"] = item["id"]
                candidate.setdefault("created_at", persisted["created_at"])
                candidate.setdefault("updated_at", persisted["updated_at"])
                if self._json(candidate) != self._json(persisted):
                    raise ValidationError(
                        "Dataset snapshots are immutable; save changed training content under a new dataset hash"
                    )
                return persisted
            if existing:
                item["created_at"] = existing["created_at"]
            if kind == "experiences":
                collision = connection.execute(
                    "SELECT id FROM experiences WHERE content_fingerprint = ? AND split != ? AND id != ? LIMIT 1",
                    (item["content_fingerprint"], item["split"], item["id"]),
                ).fetchone()
                if collision:
                    raise LeakageError(
                        "This PR content already exists in the other dataset split; use a genuinely held-out PR"
                    )
                old = connection.execute(
                    "SELECT split FROM experiences WHERE id = ?", (item["id"],)
                ).fetchone()
                if old and old["split"] != item["split"]:
                    raise LeakageError(
                        "An experience's train/eval split is immutable; create a genuinely new PR instead"
                    )
                connection.execute(
                    "INSERT INTO experiences(id,data,created_at,updated_at,split,content_fingerprint) VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at,"
                    "split=excluded.split,content_fingerprint=excluded.content_fingerprint",
                    (
                        item["id"],
                        self._json(item),
                        item["created_at"],
                        item["updated_at"],
                        item["split"],
                        item["content_fingerprint"],
                    ),
                )
            else:
                connection.execute(
                    f"INSERT INTO {kind}(id,data,created_at,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                    (item["id"], self._json(item), item["created_at"], item["updated_at"]),
                )
        return item

    upsert = save

    @staticmethod
    def _json(data: Any) -> str:
        try:
            return json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                "Data must contain JSON-compatible values and finite numbers"
            ) from exc

    def get(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        kind = self._kind(kind)
        with self._lock:
            row = self._connection.execute(
                f"SELECT data FROM {kind} WHERE id = ?", (str(entity_id),)
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def list(
        self, kind: str, *, limit: int = 1000, split: str | None = None
    ) -> list[dict[str, Any]]:
        kind = self._kind(kind)
        if not isinstance(limit, int) or limit < 1 or limit > 100_000:
            raise ValidationError("limit must be between 1 and 100000")
        query = f"SELECT data FROM {kind}"
        parameters: list[Any] = []
        if split is not None:
            if kind != "experiences" or split not in {"train", "eval"}:
                raise ValidationError("split may only filter experiences using train or eval")
            query += " WHERE split = ?"
            parameters.append(split)
        query += " ORDER BY created_at DESC, id ASC LIMIT ?"
        parameters.append(limit)
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def delete(self, kind: str, entity_id: str) -> bool:
        kind = self._kind(kind)
        if kind == "datasets":
            raise ValidationError(
                "Dataset snapshots cannot be deleted because checkpoints depend on their training lineage"
            )
        with self._write() as connection:
            cursor = connection.execute(f"DELETE FROM {kind} WHERE id = ?", (str(entity_id),))
        return cursor.rowcount > 0

    def create_job(self, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.save(
            "jobs",
            {
                "id": str(uuid4()),
                "kind": kind,
                "status": "queued",
                "progress": 0,
                "payload": payload or {},
                "result": None,
                "error": None,
            },
        )

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        """Atomically merge updates so concurrently written fields survive."""
        with self._write() as connection:
            row = connection.execute("SELECT data FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                raise ValidationError(f"Job {job_id} does not exist")
            item = json.loads(row["data"])
            updates.pop("id", None)
            updates.pop("created_at", None)
            item.update(redact_secrets(updates))
            item["updated_at"] = utc_now()
            connection.execute(
                "UPDATE jobs SET data = ?, updated_at = ? WHERE id = ?",
                (self._json(item), item["updated_at"], job_id),
            )
        return item

    def append_event(
        self, job_id: str, event: dict[str, Any] | str, data: Any = None
    ) -> dict[str, Any]:
        event = {"type": event, "data": data} if isinstance(event, str) else dict(event)
        event = redact_secrets(event)
        event["job_id"] = job_id
        event["created_at"] = utc_now()
        event.setdefault("type", "progress")
        with self._write() as connection:
            if not connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone():
                raise ValidationError(f"Job {job_id} does not exist")
            cursor = connection.execute(
                "INSERT INTO events(job_id,data,created_at) VALUES(?,?,?)",
                (job_id, self._json(event), event["created_at"]),
            )
            event["id"] = cursor.lastrowid
            event["sequence"] = cursor.lastrowid
            connection.execute(
                "UPDATE events SET data = ? WHERE id = ?", (self._json(event), event["id"])
            )
        return event

    def list_events(
        self, job_id: str, after_id: int = 0, *, limit: int = 1000
    ) -> list[dict[str, Any]]:
        if not isinstance(after_id, int) or after_id < 0:
            raise ValidationError("after_id must be a non-negative integer")
        if not isinstance(limit, int) or not 1 <= limit <= 100_000:
            raise ValidationError("limit must be between 1 and 100000")
        with self._lock:
            rows = self._connection.execute(
                "SELECT data FROM events WHERE job_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (job_id, after_id, limit),
            ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
