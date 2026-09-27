from __future__ import annotations

import ast
import hashlib
import json
import unittest
from collections import Counter
from unittest.mock import patch

from reflex.curriculum import generate_curriculum
from reflex.repair_cases import held_out_cases, public_case, training_cases
from reflex.repair_engine import build_repair_prompt, execute_case, isolation_status


def fingerprint(source: str) -> str:
    return hashlib.sha256(ast.dump(ast.parse(source), include_attributes=False).encode()).hexdigest()


class CurriculumContractTests(unittest.TestCase):
    def test_default_is_24_explicit_synthetic_training_variants_four_per_family(self):
        cases = generate_curriculum()
        self.assertEqual(len(cases), 24)
        self.assertEqual(len({case["id"] for case in cases}), 24)
        counts = Counter(case["_generation"]["family"] for case in cases)
        self.assertEqual(len(counts), 6)
        self.assertEqual(set(counts.values()), {4})
        for case in cases:
            self.assertTrue(case["id"].startswith("generated-"))
            self.assertEqual(case["source_kind"], "generated")
            self.assertEqual(case["_split"], "train")
            self.assertIn("not an independent production incident", case["description"])
            self.assertEqual(case["_generation"]["kind"], "synthetic_training_variant")

    def test_seed_is_deterministic_prefix_stable_and_changes_scenarios(self):
        first = generate_curriculum(seed=42)
        self.assertEqual(first, generate_curriculum(seed=42))
        self.assertEqual(first[:6], generate_curriculum(count=6, seed=42))
        self.assertNotEqual(first, generate_curriculum(seed=43))
        self.assertNotEqual(first[0]["reproduction"], generate_curriculum(seed=43)[0]["reproduction"])

    def test_generated_source_asts_are_unique_and_exclude_original_sources(self):
        generated = {fingerprint(case["source"]) for case in generate_curriculum()}
        # Compare held-out source identities only; labels, references and execution
        # outcomes never enter generation or curriculum selection.
        reserved = {fingerprint(case["source"]) for case in training_cases() + held_out_cases()}
        self.assertEqual(len(generated), 24)
        self.assertFalse(generated & reserved)
        for case in generate_curriculum():
            self.assertEqual(fingerprint(case["source"]), case["_generation"]["source_ast_hash"])

    def test_public_projection_and_prompt_exclude_private_gold(self):
        for case in generate_curriculum():
            case["_checks"][0]["expected_state"]["private_marker"] = "CURRICULUM_PRIVATE_917"
            case["_reference_code"] += "# CURRICULUM_PRIVATE_917"
            visible = public_case(case)
            self.assertNotIn("_checks", visible)
            self.assertNotIn("_reference_code", visible)
            self.assertNotIn("_generation", visible)
            self.assertNotIn("CURRICULUM_PRIVATE_917", build_repair_prompt(case))
            self.assertEqual(visible["source_kind"], "generated")

    def test_expected_outputs_do_not_depend_on_reference_implementation(self):
        expected = generate_curriculum(count=1)[0]["_checks"]
        templates = training_cases()
        templates[0]["_reference_code"] = "def apply(state, event):\n    return {}\n"
        with patch("reflex.curriculum.training_cases", return_value=templates):
            generated = generate_curriculum(count=1)[0]
        self.assertEqual(generated["_checks"], expected)
        self.assertIn("return {}", generated["_reference_code"])

    def test_results_are_defensive_copies_and_finite_json(self):
        cases = generate_curriculum()
        cases[0]["initial_state"]["inventory"].clear()
        fresh = generate_curriculum()
        self.assertTrue(fresh[0]["initial_state"]["inventory"])
        json.dumps(fresh, allow_nan=False)

    def test_count_and_seed_bounds_are_explicit(self):
        for count in (0, -1, 25, True, 1.5, "24"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                generate_curriculum(count=count)
        for seed in (-1, True, 2**32, 1.5, "42"):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                generate_curriculum(seed=seed)
        self.assertEqual(len(generate_curriculum(count=1, seed=0)), 1)


class ExecutedCurriculumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boundary = isolation_status()
        if not boundary["enforced"]:
            raise unittest.SkipTest("Real sandbox unavailable: " + boundary["detail"])

    def test_all_24_variants_reproduce_a_bug_and_reference_repairs_pass(self):
        for case in generate_curriculum():
            with self.subTest(case=case["id"]):
                broken = execute_case(case, case["source"])
                repaired = execute_case(case, case["_reference_code"])
                self.assertEqual(broken["status"], "failed", broken)
                self.assertLess(broken["passed"], broken["total"])
                self.assertEqual(repaired["status"], "passed", repaired)
                self.assertEqual(repaired["passed"], repaired["total"])
                self.assertEqual(repaired["total"], 4)
                self.assertTrue(repaired["isolation"]["enforced"])


if __name__ == "__main__":
    unittest.main()
