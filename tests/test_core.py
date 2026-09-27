from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from reflex.core import (
    ISSUE_TAGS,
    LeakageError,
    ValidationError,
    build_memory,
    build_review_prompt,
    build_sft_examples,
    content_fingerprint,
    normalize_experience,
    normalize_feedback,
    redact_secrets,
    score_review,
    validate_no_leakage,
)
from reflex.fixtures import HELD_OUT_PRS, SAMPLE_PRS, sample_experiences
from reflex.fixtures import _pr


def corrected_experience() -> dict:
    experience = copy.deepcopy(SAMPLE_PRS[0])
    experience["human_feedback"] = {
        "decision": "REJECT",
        "reason": "Handle the documented payment exception and add a regression test.",
        "issue_tags": ["broad_exception", "missing_regression_test"],
        "approved": True,
    }
    return experience


class ExperienceCoreTests(unittest.TestCase):
    def test_unreviewed_samples_never_train(self):
        self.assertEqual(build_sft_examples(SAMPLE_PRS), [])
        self.assertTrue(all(item["fictional"] for item in SAMPLE_PRS))
        self.assertTrue(all(item["trajectory"] == [] for item in SAMPLE_PRS))
        self.assertTrue(all(item["human_feedback"] is None for item in SAMPLE_PRS))
        self.assertTrue(all("gold" not in item for item in sample_experiences()))

    def test_explicit_approved_feedback_is_required_and_boolean(self):
        experience = corrected_experience()
        for approval in (False, None, "true", 1):
            experience["human_feedback"]["approved"] = approval
            self.assertEqual(build_sft_examples([experience]), [])
        experience["human_feedback"]["approved"] = True
        result = build_sft_examples([experience])
        self.assertEqual(len(result), 1)
        self.assertEqual(json.loads(result[0]["completion"])["decision"], "REJECT")
        self.assertEqual(result[0]["prompt"], build_review_prompt(experience))

    def test_eval_feedback_cannot_train_or_enter_memory(self):
        experience = corrected_experience()
        experience["split"] = "eval"
        self.assertEqual(build_sft_examples([experience]), [])
        self.assertEqual(build_memory([experience]), "")

    def test_conflicting_duplicate_corrections_require_reconciliation(self):
        original = corrected_experience()
        duplicate = copy.deepcopy(original)
        duplicate["id"] = "duplicate"
        self.assertEqual(len(build_sft_examples([original, duplicate])), 1)
        duplicate["human_feedback"] = {"decision": "APPROVE", "reason": "Accepted", "issue_tags": [], "approved": True}
        with self.assertRaises(ValidationError):
            build_sft_examples([original, duplicate])

    def test_prompt_stable_across_model_and_feedback_and_hidden_labels(self):
        experience = corrected_experience()
        original = build_review_prompt(experience, memory="Keep failures visible.")
        modified = copy.deepcopy(experience)
        modified.update({"id": "new-id", "model": "trained-v1", "checkpoint": "checkpoint-1", "gold": "DO_NOT_LEAK"})
        modified["context"]["expected_decision"] = "DO_NOT_LEAK"
        modified["context"]["nested"] = {"gold": "DO_NOT_LEAK"}
        # An empty nested object itself changes context, so compare equal ordinary context.
        modified["context"].pop("nested")
        modified["human_feedback"]["reason"] = "DO_NOT_LEAK"
        modified["agent_review"] = {"decision": "APPROVE", "summary": "DO_NOT_LEAK", "issues": []}
        self.assertEqual(original, build_review_prompt(modified, memory="Keep failures visible."))
        self.assertNotIn("DO_NOT_LEAK", original)
        self.assertNotEqual(original, build_review_prompt(experience))

    def test_gold_never_enters_held_out_prompt(self):
        example = copy.deepcopy(HELD_OUT_PRS[0])
        example["gold"]["secret_marker"] = "HIDDEN_ANSWER_MARKER"
        example["context"]["nested"] = {"gold": "HIDDEN_ANSWER_MARKER", "description": "visible context"}
        prompt = build_review_prompt(example)
        self.assertNotIn("HIDDEN_ANSWER_MARKER", prompt)
        self.assertIn("visible context", prompt)

    def test_reject_feedback_requires_tags_and_approve_rejects_tags(self):
        with self.assertRaises(ValidationError):
            normalize_feedback({"decision": "REJECT", "reason": "Bad", "issue_tags": []})
        with self.assertRaises(ValidationError):
            normalize_feedback({"decision": "APPROVE", "reason": "Good", "issue_tags": ["broad_exception"]})
        with self.assertRaises(ValidationError):
            normalize_feedback({"decision": "REJECT", "reason": "Bad", "issue_tags": ["broad_exception"], "issues": [{"tag": "sql_injection"}]})

    def test_whitespace_filename_and_hunk_changes_do_not_evade_leak_guard(self):
        original = corrected_experience()
        duplicate = copy.deepcopy(original)
        duplicate.update({"id": "different-id", "title": "Retitled", "repo": "another-repo", "split": "eval"})
        duplicate["diff"] = duplicate["diff"].replace("payments.py", "renamed.py").replace("@@ -8,1 +8,4 @@", "@@ -90,1 +90,4 @@").replace("receipt =", "receipt    =")
        self.assertEqual(content_fingerprint(original), content_fingerprint(duplicate))
        with self.assertRaises(LeakageError):
            build_sft_examples([original, duplicate])

    def test_sample_and_held_out_sets_have_unique_content_and_balanced_labels(self):
        validate_no_leakage(SAMPLE_PRS + HELD_OUT_PRS)
        self.assertEqual(len(SAMPLE_PRS), 26)
        self.assertEqual(len(HELD_OUT_PRS), 12)
        self.assertEqual(sum(item["gold"]["decision"] == "APPROVE" for item in HELD_OUT_PRS), 6)
        self.assertEqual(len({content_fingerprint(item) for item in SAMPLE_PRS + HELD_OUT_PRS}), 38)
        for example in HELD_OUT_PRS:
            self.assertTrue(set(example["gold"]["issue_tags"]).issubset(ISSUE_TAGS))

    def test_fixture_metadata_is_stable_across_wall_clock_changes(self):
        with patch("reflex.core.utc_now", return_value="2026-01-01T00:00:00Z"):
            first = _pr("stable", "Stable fixture", "+return public_result")
        with patch("reflex.core.utc_now", return_value="2026-12-31T23:59:59Z"):
            second = _pr("stable", "Stable fixture", "+return public_result")
        self.assertEqual(first, second)

    def test_metadata_only_diff_is_rejected(self):
        with self.assertRaises(ValidationError):
            content_fingerprint({"diff": "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@"})

    def test_redacts_nested_credentials_and_preserves_safe_variable_references(self):
        token = "sk-proj-" + "a" * 40
        original = {
            "api_key": "sensitive-value",
            "nested": [{"message": f"Authorization: Bearer {token}"}],
            "diff": '+PASSWORD = "fictional-password"\n+client = VendorClient(api_key=credential)',
        }
        cleaned = redact_secrets(original)
        self.assertNotIn(token, json.dumps(cleaned))
        self.assertNotIn("sensitive-value", json.dumps(cleaned))
        self.assertNotIn("fictional-password", json.dumps(cleaned))
        self.assertIn("api_key=credential)", cleaned["diff"])
        self.assertEqual(redact_secrets(cleaned), cleaned)

    def test_hidden_reasoning_is_removed_and_provenance_survives(self):
        experience = copy.deepcopy(SAMPLE_PRS[1])
        experience.update({"model": "reviewer-v1", "checkpoint": "checkpoint-3", "condition": "learned", "prompt_hash": "abc", "external_id": "turn-1"})
        experience["ufo"] = {"workspace_id": "workspace-1", "turn_id": "turn-1", "sdk_commit": "sha", "secret": "remove-me"}
        experience["trajectory"] = [
            {"type": "reasoning", "content": "PRIVATE_THOUGHT"},
            {"type": "thinking_delta", "content": "PRIVATE_THOUGHT"},
            {"type": "tool_call", "name": "read_file", "reasoning": "PRIVATE_THOUGHT", "result": "file read"},
        ]
        normalized = normalize_experience(experience)
        self.assertNotIn("PRIVATE_THOUGHT", json.dumps(normalized))
        self.assertEqual(len(normalized["trajectory"]), 1)
        self.assertEqual(normalized["checkpoint"], "checkpoint-3")
        self.assertEqual(normalized["ufo"]["turn_id"], "turn-1")
        self.assertNotIn("secret", normalized["ufo"])


class RewardTests(unittest.TestCase):
    def test_perfect_review_scores_full_reward(self):
        gold = {"decision": "REJECT", "issue_tags": ["sql_injection"], "critical_issue_tags": ["sql_injection"]}
        result = score_review({"decision": "REJECT", "issues": ["sql_injection"], "summary": "Unsafe interpolation."}, gold)
        self.assertEqual(result["reward"], 2.0)
        self.assertEqual(result["normalized_reward"], 1.0)

    def test_missed_critical_issue_is_penalized_even_with_correct_decision(self):
        gold = {"decision": "REJECT", "issue_tags": ["sql_injection", "missing_timeout"], "critical_issue_tags": ["sql_injection"]}
        result = score_review({"decision": "REJECT", "issues": ["missing_timeout"]}, gold)
        self.assertEqual(result["reward"], 0.75)
        self.assertEqual(result["missed_critical_issue_tags"], ["sql_injection"])
        self.assertEqual(result["issue_recall"], 0.5)

    def test_arbitrary_synonyms_do_not_count_as_correct_issue_identification(self):
        gold = {"decision": "REJECT", "issue_tags": ["sql_injection"]}
        result = score_review({"decision": "REJECT", "issues": ["unsafe_database"]}, gold)
        self.assertEqual(result["issue_recall"], 0)
        self.assertEqual(result["unnecessary_issue_tags"], ["unsafe_database"])
        self.assertLess(result["reward"], 1.0)

    def test_clean_approval_gets_full_credit_but_extra_comments_cost_reward(self):
        gold = {"decision": "APPROVE", "issue_tags": []}
        self.assertEqual(score_review({"decision": "APPROVE", "issues": []}, gold)["reward"], 2)
        with self.assertRaises(ValidationError):
            score_review({"decision": "APPROVE", "issues": ["style"]}, gold)
        self.assertLess(score_review({"decision": "REJECT", "issues": ["style"]}, gold)["reward"], 2)

    def test_malformed_decision_does_not_default_to_approve(self):
        with self.assertRaises(ValidationError):
            score_review({"summary": "Looks okay"}, {"decision": "APPROVE", "issue_tags": []})
        with self.assertRaises(ValidationError):
            score_review({"decision": "MAYBE"}, {"decision": "APPROVE", "issue_tags": []})


if __name__ == "__main__":
    unittest.main()
