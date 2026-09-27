from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import time
import unittest
from unittest.mock import patch

from reflex.repair_cases import get_case, held_out_cases, public_case, training_cases
from reflex.repair_engine import (
    RepairExecutionError,
    _profile,
    _run,
    _validate_code,
    build_repair_prompt,
    code_diff,
    execute_case,
    isolation_status,
)


class RepairContractTests(unittest.TestCase):
    def test_public_cases_never_include_private_checks_reference_or_heldout_catalog(self):
        for case in training_cases() + held_out_cases():
            visible = public_case(case)
            self.assertNotIn("_checks", visible)
            self.assertNotIn("_reference_code", visible)
            self.assertTrue(all(not key.startswith("_") for key in visible))
            self.assertEqual(visible["source_kind"], "sample")
        self.assertIsNone(get_case(held_out_cases()[0]["id"]))
        self.assertIsNotNone(get_case(held_out_cases()[0]["id"], include_held_out=True))

    def test_prompt_uses_public_fields_and_identical_memory_for_any_condition(self):
        case = training_cases()[0]
        case["_checks"][0]["expected_state"]["private_marker"] = "HIDDEN_ANSWER_916"
        case["_reference_code"] += "# HIDDEN_ANSWER_916"
        original = build_repair_prompt(case, memory="Record operation identity before mutation.")
        case["condition"] = "learned"
        case["checkpoint"] = "specialist-v1"
        self.assertEqual(original, build_repair_prompt(case, memory="Record operation identity before mutation."))
        self.assertNotIn("HIDDEN_ANSWER_916", original)
        self.assertNotIn("expected_state", original)

    def test_train_and_heldout_sources_are_distinct_even_after_ast_normalization(self):
        train = training_cases()
        heldout = held_out_cases()
        self.assertGreaterEqual(len(train), 6)
        self.assertGreaterEqual(len(heldout), 4)
        fingerprints = [ast.dump(ast.parse(case["source"]), include_attributes=False) for case in train + heldout]
        self.assertEqual(len(fingerprints), len(set(fingerprints)))

    def test_lookup_returns_defensive_copies(self):
        case = training_cases()[0]
        case["initial_state"]["inventory"]["widget"] = -900
        self.assertEqual(get_case(case["id"])["initial_state"]["inventory"]["widget"], 12)

    def test_candidate_cannot_import_reflect_access_frames_or_override_harness_output(self):
        attacks = [
            'import os\ndef apply(state, event):\n    return {}',
            'def apply(state, event):\n    return open("/etc/passwd").read()',
            'def apply(state, event):\n    return globals()',
            'def apply(state, event):\n    print("fake success")\n    return {}',
            'def apply(state, event):\n    return event.__class__',
            'def apply(state, event):\n    return "{x.__class__}".format(x=event)',
            'def apply(state, event):\n    g = (g.gi_frame.f_back for n in [0])\n    frame = list(g)[0]\n    host = frame.f_back.f_globals\n    return {}',
            'def apply(state, event):\n    return apply.__globals__',
            'def apply(state, event):\n    return event.kill(1, 9)',
        ]
        for code in attacks:
            with self.subTest(code=code), self.assertRaises(RepairExecutionError):
                _validate_code(code)
            with patch("reflex.repair_engine._run") as worker:
                report = execute_case(training_cases()[0], code)
                worker.assert_not_called()
                self.assertEqual(report["status"], "error")
                self.assertEqual(report["code_hash"], hashlib.sha256(code.encode()).hexdigest())

    def test_isolation_unavailable_fails_closed_without_candidate_execution(self):
        unavailable = {"kind": "macos-seatbelt", "enforced": False, "detail": "unavailable for this test"}
        with patch("reflex.repair_engine.isolation_status", return_value=unavailable), patch("reflex.repair_engine._run") as worker:
            report = execute_case(training_cases()[0], training_cases()[0]["_reference_code"])
            worker.assert_not_called()
        self.assertEqual(report["status"], "error")
        self.assertFalse(report["isolation"]["enforced"])

    def test_large_event_batches_rejected_before_execution(self):
        case = training_cases()[0]
        with patch("reflex.repair_engine._run") as worker:
            result = execute_case(case, case["source"], events=[{}] * 33)
            worker.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertIn("32", result["checks"][0]["detail"])

    def test_diff_is_a_real_backend_unified_diff(self):
        result = code_diff("def apply(state, event):\n    return {}\n", "def apply(state, event):\n    return event\n")
        self.assertIn("--- a/handler.py", result)
        self.assertIn("+++ b/handler.py", result)
        self.assertIn("-    return {}", result)
        self.assertIn("+    return event", result)


class RealSandboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.boundary = isolation_status()
        if not cls.boundary["enforced"]:
            raise unittest.SkipTest("Actual sandbox unavailable: " + cls.boundary["detail"])

    def test_os_boundary_actually_denies_host_reads_writes_and_network(self):
        self.assertEqual(_run({"probe": True}), {"read_denied": True, "alternate_read_denied": True, "write_denied": True, "network_denied": True, "signal_denied": True})
        _, profile = _profile()
        self.assertIn("(deny signal)", profile)
        self.assertIn("(deny process-fork)", profile)

    def test_every_baseline_reproduces_failure_and_every_reference_passes(self):
        for case in training_cases() + held_out_cases():
            with self.subTest(case=case["id"]):
                broken = execute_case(case, case["source"])
                fixed = execute_case(case, case["_reference_code"])
                self.assertEqual(broken["status"], "failed", broken)
                self.assertLess(broken["passed"], broken["total"])
                self.assertEqual(fixed["status"], "passed", fixed)
                self.assertEqual(fixed["passed"], 4)
                self.assertTrue(fixed["isolation"]["enforced"])

    def test_checkout_preview_shows_actual_duplicate_and_repaired_business_effects(self):
        case = training_cases()[0]
        broken = execute_case(case, case["source"])
        fixed = execute_case(case, case["_reference_code"])
        self.assertEqual(len(broken["preview"]["state"]["orders"]), 2)
        self.assertEqual(len(fixed["preview"]["state"]["orders"]), 1)
        self.assertEqual(broken["preview"]["state"]["inventory"]["widget"], 8)
        self.assertEqual(fixed["preview"]["state"]["inventory"]["widget"], 10)

    def test_manual_case_works_without_fixture_identity_and_key_order_is_irrelevant(self):
        case = {"id": "my-own-case", "initial_state": {"count": 0}, "reproduction": [{"amount": 2}], "_checks": [{"name": "increments", "initial_state": {"count": 0}, "events": [{"amount": 2}, {"amount": 3}], "expected_state": {"count": 5}, "expected_results": [{"ok": True, "count": 2}, {"ok": True, "count": 5}]}]}
        code = 'def apply(state, event):\n    state["count"] += event["amount"]\n    return {"count": state["count"], "ok": True}\n'
        result = execute_case(case, code)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["preview"]["state"], {"count": 2})
        self.assertEqual(result["code_hash"], hashlib.sha256(code.encode()).hexdigest())

    def test_child_environment_does_not_inherit_credentials(self):
        case = training_cases()[0]
        with patch.dict(os.environ, {"REPAIR_TEST_CREDENTIAL": "do-not-forward"}), patch("reflex.repair_engine.subprocess.Popen", wraps=subprocess.Popen) as popen:
            result = execute_case(case, case["_reference_code"])
        self.assertEqual(result["status"], "passed", result)
        for call in popen.call_args_list:
            self.assertNotIn("REPAIR_TEST_CREDENTIAL", call.kwargs["env"])

    def test_infinite_handler_is_terminated_within_bounded_time(self):
        code = "def apply(state, event):\n    while True:\n        pass\n"
        start = time.monotonic()
        result = execute_case(training_cases()[0], code)
        self.assertEqual(result["status"], "error")
        self.assertLess(time.monotonic() - start, 4.5)
        self.assertTrue(any(word in result["checks"][0]["detail"] for word in ("signal", "execution limit")))

    def test_excessive_result_is_failed_without_unbounded_output(self):
        code = 'def apply(state, event):\n    return {"payload": "x" * 70000}\n'
        result = execute_case(training_cases()[0], code)
        self.assertEqual(result["status"], "failed", result)
        self.assertEqual(result["passed"], 0)
        self.assertLess(len(json.dumps(result)), 10_000)
        self.assertTrue(all("64 KiB" in check["detail"] for check in result["checks"]))

    def test_unavailable_memory_observation_fails_closed_and_terminates_candidate(self):
        code = "def apply(state, event):\n    while True:\n        pass\n"
        unavailable = subprocess.CompletedProcess(args=["ps"], returncode=1, stdout="", stderr="unavailable")
        with patch("reflex.repair_engine.subprocess.run", return_value=unavailable):
            result = execute_case(training_cases()[0], code)
        self.assertEqual(result["status"], "error")
        self.assertIn("memory monitoring is unavailable", result["checks"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
