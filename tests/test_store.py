from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from reflex.core import LeakageError, ValidationError
from reflex.fixtures import SAMPLE_PRS
from reflex.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".reflex-test-", dir=Path(__file__).resolve().parents[1])
        self.path = Path(self.directory.name) / "reflex.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_experience_job_events_checkpoint_and_evaluation_survive_reopen(self):
        experience = self.store.save("experiences", SAMPLE_PRS[0])
        job = self.store.create_job("training", {"experience_ids": [experience["id"]]})
        first = self.store.append_event(job["id"], {"type": "training_started", "message": "Starting confirmed training"})
        second = self.store.append_event(job["id"], "checkpoint_saved", {"checkpoint": "reflex-v1"})
        self.store.update_job(job["id"], status="completed", progress=100)
        checkpoint = self.store.save("checkpoints", {"id": "reflex-v1", "status": "ready", "job_id": job["id"]})
        evaluation = self.store.save("evaluations", {"checkpoint_id": checkpoint["id"], "status": "pending"})
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get("experiences", experience["id"])["diff"], experience["diff"])
        self.assertEqual(self.store.get("jobs", job["id"])["status"], "completed")
        self.assertEqual(self.store.get("checkpoints", "reflex-v1")["job_id"], job["id"])
        self.assertIsNotNone(self.store.get("evaluations", evaluation["id"]))
        self.assertEqual(self.store.list_events(job["id"], first["id"]), [second])
        self.assertTrue(experience["created_at"].endswith("Z"))

    def test_save_preserves_created_at(self):
        original = self.store.save("experiences", SAMPLE_PRS[1])
        updated = self.store.save("experiences", {**original, "created_at": "wrong", "title": "Changed title"})
        self.assertEqual(updated["created_at"], original["created_at"])
        self.assertEqual(self.store.get("experiences", original["id"])["title"], "Changed title")

    def test_cross_split_duplicate_is_refused_without_partial_write(self):
        original = self.store.save("experiences", SAMPLE_PRS[0])
        duplicate = {**original, "id": "held-out-copy", "split": "eval"}
        with self.assertRaises(LeakageError):
            self.store.save("experiences", duplicate)
        self.assertIsNone(self.store.get("experiences", "held-out-copy"))
        self.assertEqual(len(self.store.list("experiences")), 1)

    def test_dataset_split_cannot_be_changed_after_storage(self):
        original = self.store.save("experiences", SAMPLE_PRS[2])
        with self.assertRaises(LeakageError):
            self.store.save("experiences", {**original, "split": "eval"})
        self.assertEqual(self.store.get("experiences", original["id"])["split"], "train")

    def test_concurrent_connections_cannot_race_past_split_guard(self):
        second_store = Store(self.path)
        try:
            def write(store, identifier, split):
                try:
                    store.save("experiences", {**SAMPLE_PRS[3], "id": identifier, "split": split})
                    return "saved"
                except LeakageError:
                    return "blocked"
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(write, self.store, "train-copy", "train"), executor.submit(write, second_store, "eval-copy", "eval")]
                self.assertCountEqual([future.result() for future in futures], ["saved", "blocked"])
        finally:
            second_store.close()

    def test_event_order_is_durable_and_updates_are_not_lost(self):
        job = self.store.create_job("evaluation")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(self.store.update_job, job["id"], **{f"worker_{i}": i}) for i in range(12)]
            for future in futures:
                future.result()
        result = self.store.get("jobs", job["id"])
        self.assertTrue(all(result[f"worker_{i}"] == i for i in range(12)))
        for i in range(3):
            self.store.append_event(job["id"], {"type": "progress", "count": i})
        events = self.store.list_events(job["id"])
        self.assertEqual([event["count"] for event in events], [0, 1, 2])
        self.assertEqual([event["id"] for event in events], sorted(event["id"] for event in events))

    def test_secret_redaction_happens_before_persistence_and_labels_are_removed(self):
        experience = copy.deepcopy(SAMPLE_PRS[4])
        experience["context"]["api_key"] = "super-sensitive-credential"
        experience["gold"] = {"decision": "REJECT"}
        saved = self.store.save("experiences", experience)
        self.assertNotIn("super-sensitive-credential", json.dumps(self.store.get("experiences", saved["id"])))
        self.assertNotIn("gold", saved)
        job = self.store.create_job("training", {"authorization": "private-token"})
        self.assertNotIn("private-token", json.dumps(self.store.get("jobs", job["id"])))

    def test_invalid_entity_and_missing_job_fail_actionably(self):
        with self.assertRaises(ValidationError):
            self.store.list("jobs; DROP TABLE experiences")
        with self.assertRaises(ValidationError):
            self.store.append_event("missing-job", {"type": "progress"})
        with self.assertRaises(ValidationError):
            self.store.update_job("missing-job", status="running")
        self.assertIsNone(self.store.get("jobs", "missing-job"))

    def test_non_json_write_rolls_back(self):
        with self.assertRaises(ValidationError):
            self.store.save("evaluations", {"id": "invalid", "score": float("nan")})
        self.assertIsNone(self.store.get("evaluations", "invalid"))
        self.assertIsNotNone(self.store.save("evaluations", {"id": "valid", "score": 0.5}))

    def test_memory_database_and_context_manager_work(self):
        with Store(":memory:") as memory:
            memory.save("experience", SAMPLE_PRS[5])
            self.assertEqual(len(memory.list("experiences", split="train")), 1)
            self.assertTrue(memory.delete("experience", SAMPLE_PRS[5]["id"]))
            self.assertFalse(memory.delete("experience", SAMPLE_PRS[5]["id"]))

    def test_dataset_snapshot_survives_reopen_and_repeated_save_is_identical(self):
        snapshot = {"id": "dataset-hash", "examples": [{"prompt": "review patch", "completion": "REJECT"}], "memory": "Require regression tests."}
        with patch("reflex.store.utc_now", return_value="2026-09-27T00:00:00.000Z"):
            saved = self.store.save("datasets", snapshot)
        with patch("reflex.store.utc_now", return_value="2027-01-01T00:00:00.000Z"):
            self.assertEqual(self.store.save("datasets", snapshot), saved)
            self.assertEqual(self.store.upsert("dataset", saved), saved)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get("datasets", snapshot["id"]), saved)
        self.assertEqual(self.store.list("datasets"), [saved])

    def test_dataset_content_metadata_and_deletion_are_immutable(self):
        saved = self.store.save("datasets", {"id": "fixed-dataset", "examples": [{"completion": "APPROVE"}], "memory": "original"})
        changes = [
            {"examples": [{"completion": "REJECT"}]},
            {"memory": "changed"},
            {"created_at": "2027-01-01T00:00:00.000Z"},
            {"updated_at": "2027-01-01T00:00:00.000Z"},
            {"additional_metadata": "changed"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaisesRegex(ValidationError, "immutable"):
                self.store.save("datasets", {**saved, **change})
            self.assertEqual(self.store.get("datasets", saved["id"]), saved)
        with self.assertRaisesRegex(ValidationError, "cannot be deleted"):
            self.store.delete("dataset", saved["id"])

    def test_concurrent_dataset_writes_cannot_replace_a_snapshot(self):
        other = Store(self.path)
        try:
            def write(store, label):
                try:
                    store.save("datasets", {"id": "shared-dataset", "examples": [{"completion": label}], "memory": "fixed"})
                    return "saved"
                except ValidationError:
                    return "blocked"
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(write, self.store, "APPROVE"), executor.submit(write, other, "REJECT")]
                self.assertCountEqual([future.result() for future in futures], ["saved", "blocked"])
            self.assertEqual(len(self.store.list("datasets")), 1)
        finally:
            other.close()

    def test_existing_database_acquires_dataset_table_without_losing_records(self):
        experience = self.store.save("experiences", SAMPLE_PRS[6])
        self.store.close()
        # Recreate the pre-snapshot schema state to exercise the additive migration.
        with sqlite3.connect(self.path) as connection:
            connection.execute("DROP TABLE datasets")
        self.store = Store(self.path)
        saved = self.store.save("datasets", {"id": "migrated", "examples": [], "memory": ""})
        self.assertEqual(self.store.get("datasets", "migrated"), saved)
        self.assertEqual(self.store.get("experiences", experience["id"]), experience)


if __name__ == "__main__":
    unittest.main()
