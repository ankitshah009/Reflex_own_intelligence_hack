"""Provider boundary tests: no River requests or tokenizer downloads."""

import asyncio
from contextlib import contextmanager
import json
import os
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from reflex.integrations.river import (
    ProviderNotConfigured,
    RiverOperationError,
    RiverProvider,
    RiverResponseError,
    _configure_tokenizer_http,
    _load_tokenizer,
    make_rl_datum,
    make_sft_datum,
    parse_review,
)


class TokenizerNetworkTests(unittest.TestCase):
    def tearDown(self):
        _configure_tokenizer_http.cache_clear()
        _load_tokenizer.cache_clear()

    def test_hub_clients_keep_offline_guard_and_finite_timeout_after_recreation(self):
        def hook(request):
            return None

        original = SimpleNamespace(event_hooks={"request": [hook], "response": []})
        _configure_tokenizer_http.cache_clear()
        with (
            patch("huggingface_hub.get_session", return_value=original),
            patch("huggingface_hub.set_client_factory") as configure,
        ):
            _configure_tokenizer_http()
        factory = configure.call_args.args[0]
        for _ in range(2):
            with factory() as client:
                self.assertEqual(client.timeout.connect, 10)
                self.assertEqual(client.timeout.read, 30)
                self.assertEqual(client.timeout.write, 30)
                self.assertEqual(client.timeout.pool, 10)
                self.assertIn(hook, client.event_hooks["request"])
                self.assertTrue(client.follow_redirects)

                import httpx

                with patch.object(
                    httpx.HTTPTransport,
                    "handle_request",
                    side_effect=lambda request: httpx.Response(200, content=b"ok"),
                ):
                    for timeout in (None, 180, 2):
                        response = client.get("https://example.invalid", timeout=timeout)
                        expected = (
                            {"connect": 10.0, "read": 30.0, "write": 30.0, "pool": 10.0}
                            if timeout != 2
                            else dict.fromkeys(("connect", "read", "write", "pool"), 2)
                        )
                        self.assertEqual(response.request.extensions["timeout"], expected)

    def test_warm_tokenizer_loads_cached_revision_without_network(self):
        revision = "a" * 40
        tokenizer = SimpleNamespace(init_kwargs={})
        auto = SimpleNamespace(from_pretrained=Mock(return_value=tokenizer))
        with (
            patch.dict(sys.modules, {"transformers": SimpleNamespace(AutoTokenizer=auto)}),
            patch("reflex.integrations.river._configure_tokenizer_http"),
            patch("huggingface_hub.snapshot_download", return_value=f"/cache/{revision}") as fetch,
        ):
            self.assertIs(_load_tokenizer("Qwen/Qwen3.5-9B"), tokenizer)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(fetch.call_args.kwargs["local_files_only"])
        auto.from_pretrained.assert_called_once_with(
            f"/cache/{revision}", local_files_only=True, trust_remote_code=False
        )
        self.assertEqual(tokenizer.init_kwargs["_commit_hash"], revision)

    def test_cold_cache_downloads_tokenizer_files_then_loads_offline(self):
        tokenizer = SimpleNamespace(init_kwargs={})
        auto = SimpleNamespace(from_pretrained=Mock(return_value=tokenizer))
        with (
            patch.dict(sys.modules, {"transformers": SimpleNamespace(AutoTokenizer=auto)}),
            patch("reflex.integrations.river._configure_tokenizer_http"),
            patch(
                "huggingface_hub.snapshot_download",
                side_effect=[FileNotFoundError(), "/cache/local"],
            ) as fetch,
        ):
            self.assertIs(_load_tokenizer("Qwen/Qwen3.5-9B"), tokenizer)
        options = fetch.call_args_list[1].kwargs
        self.assertEqual(options["etag_timeout"], 10)
        self.assertEqual(options["max_workers"], 2)
        self.assertIn("tokenizer.json", options["allow_patterns"])
        self.assertFalse(
            any(
                "safetensors" in pattern or ".bin" in pattern
                for pattern in options["allow_patterns"]
            )
        )
        auto.from_pretrained.assert_called_once_with(
            "/cache/local", local_files_only=True, trust_remote_code=False
        )

    def test_incomplete_cache_fetches_missing_tokenizer_files(self):
        tokenizer = SimpleNamespace(init_kwargs={})
        auto = SimpleNamespace(from_pretrained=Mock(side_effect=[OSError(), tokenizer]))
        with (
            patch.dict(sys.modules, {"transformers": SimpleNamespace(AutoTokenizer=auto)}),
            patch("reflex.integrations.river._configure_tokenizer_http"),
            patch("huggingface_hub.snapshot_download", return_value="/cache/local") as fetch,
        ):
            self.assertIs(_load_tokenizer("Qwen/Qwen3.5-9B"), tokenizer)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(auto.from_pretrained.call_count, 2)
        self.assertTrue(
            all(call.kwargs["local_files_only"] for call in auto.from_pretrained.call_args_list)
        )

    def test_tokenizer_failure_reports_pre_river_stage_without_leaking_error_text(self):
        auto = SimpleNamespace(
            from_pretrained=Mock(side_effect=TimeoutError("private endpoint data"))
        )
        _load_tokenizer.cache_clear()
        with (
            patch.dict(sys.modules, {"transformers": SimpleNamespace(AutoTokenizer=auto)}),
            patch("reflex.integrations.river._configure_tokenizer_http"),
            patch(
                "huggingface_hub.snapshot_download",
                side_effect=TimeoutError("private endpoint data"),
            ),
        ):
            with self.assertRaises(RiverOperationError) as caught:
                _load_tokenizer("Qwen/Qwen3.5-9B")
        self.assertIn("Tokenizer setup failed", str(caught.exception))
        self.assertIn("No River request was submitted", str(caught.exception))
        self.assertNotIn("private endpoint", str(caught.exception))


REVIEW = json.dumps(
    {
        "decision": "REJECT",
        "summary": "Failure is swallowed.",
        "issues": [{"tag": "catch_all", "severity": "high", "message": "Catch a specific error."}],
    }
)


class Tokenizer:
    eos_token_id = 999
    init_kwargs = {"_commit_hash": "fixture-tokenizer-revision"}

    def __call__(self, text, *, add_special_tokens):
        return {"input_ids": [ord(character) for character in text]}

    def apply_chat_template(self, messages, **kwargs):
        assert kwargs == {
            "tokenize": False,
            "add_generation_prompt": True,
            "enable_thinking": False,
        }
        return f"<user>{messages[0]['content']}</user><assistant>"


class RiverBoundary:
    """Test double for SDK I/O only; real masking and parsing execute."""

    def __init__(
        self,
        *,
        fail_backward=False,
        fail_save=False,
        fail_sample=False,
        rl_outputs=None,
        wrong_policy=False,
        inexact=False,
        fail_rl_backward=False,
        missing_policy=False,
    ):
        self.calls = []
        self.closed = 0
        self.exited = 0
        self.model_id = "test-model"
        self.fail_backward = fail_backward
        self.fail_save = fail_save
        self.fail_sample = fail_sample
        self.rl_outputs = rl_outputs or [
            REVIEW,
            json.dumps({"decision": "APPROVE", "summary": "No issue", "issues": []}),
        ]
        self.wrong_policy = wrong_policy
        self.inexact = inexact
        self.fail_rl_backward = fail_rl_backward
        self.missing_policy = missing_policy
        self.policy = SimpleNamespace(id="policy-0", parent_id=None, step=0)
        self.backward_options = []

    def Client(self, **kwargs):
        self.calls.append(("client", kwargs))
        return self

    @staticmethod
    def LoraConfig(**kwargs):
        return kwargs

    def close(self):
        self.closed += 1

    @contextmanager
    def session(self, **kwargs):
        self.calls.append(("session", kwargs))
        try:
            yield self
        finally:
            self.exited += 1

    def create_model(self, **kwargs):
        self.calls.append(("create_model", kwargs))
        return self

    def sample(self, **kwargs):
        self.calls.append(("sample", kwargs))
        if self.fail_sample:
            raise RuntimeError("private-token must never be exposed")
        if kwargs["num_samples"] > 1:
            return [
                [
                    SimpleNamespace(
                        text=text,
                        tokens=[101, 102],
                        logprobs=[-0.5, -0.6],
                        stop_reason="stop",
                        token_data_is_exact=not self.inexact,
                        policy_version=SimpleNamespace(id="wrong-policy")
                        if self.wrong_policy
                        else self.policy,
                    )
                    for text in self.rl_outputs
                ]
            ]
        return [[SimpleNamespace(text=REVIEW)]]

    def forward_backward(self, batch, **kwargs):
        self.calls.append(("forward_backward", batch))
        self.backward_options.append(kwargs)
        if self.fail_backward or (self.fail_rl_backward and kwargs["loss_fn"] == "cispo"):
            raise RuntimeError("private-token must never be exposed")
        return SimpleNamespace(metrics={"loss": 1.2})

    def optim_step(self, **kwargs):
        self.calls.append(("optim_step", kwargs))
        self.policy = SimpleNamespace(
            id=f"policy-{self.policy.step + 1}", parent_id=self.policy.id, step=self.policy.step + 1
        )
        return SimpleNamespace(
            policy_version=None if self.missing_policy else self.policy, metrics={}
        )

    def save_weights(self, name, **kwargs):
        self.calls.append(("save_weights", {"name": name, **kwargs}))
        if self.fail_save:
            raise TimeoutError("save never confirmed")
        return SimpleNamespace(path=f"river://run/sampler_weights/{name}")


class RiverTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"RIVER_TRAIN_MAX_STEPS": "2"})
        self.env.start()
        self.tokenizer = patch(
            "reflex.integrations.river._load_tokenizer", return_value=Tokenizer()
        )
        self.tokenizer.start()

    def tearDown(self):
        self.tokenizer.stop()
        self.env.stop()

    def provider(self, boundary):
        provider = RiverProvider(api_key="test-key", base_model="test-model")
        provider._sdk = lambda: boundary
        return provider

    def test_missing_credentials_fail_without_import_or_network(self):
        provider = RiverProvider(api_key="")
        self.assertFalse(provider.configured)
        with patch("reflex.integrations.river.importlib.import_module") as imported:
            with self.assertRaisesRegex(ProviderNotConfigured, "RIVER_API_KEY"):
                asyncio.run(provider.review("review this"))
            imported.assert_not_called()

    def test_completion_mask_starts_on_preceding_prompt_token(self):
        datum = make_sft_datum(Tokenizer(), "abc", "XY")
        self.assertEqual(datum["input_ids"], [97, 98, 99, 88, 89])
        self.assertEqual(datum["target_tokens"], [98, 99, 88, 89, 999])
        self.assertEqual(datum["weights"], [0, 0, 1, 1, 1])

    def test_oversized_examples_are_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, "never silently truncated"):
            make_sft_datum(Tokenizer(), "prompt", "correction", max_tokens=4)

    def test_json_fences_and_closed_thinking_are_parsed(self):
        raw = f"<think>internal draft</think>\n```json\n{REVIEW}\n```"
        parsed = parse_review(raw, "checkpoint")
        self.assertEqual(parsed["decision"], "REJECT")
        self.assertEqual(parsed["raw"], REVIEW)
        self.assertNotIn("internal draft", json.dumps(parsed))

    def test_invalid_or_incomplete_output_never_becomes_approval(self):
        invalid = [
            "looks good",
            "<think>unfinished",
            '{"decision":"APPROVE"}',
            '{"decision":[]}',
            '{"decision":"APPROVE","summary":"ok","issues":[{}]}',
            '{"decision":"APPROVE","summary":"ok","issues":[{"tag":"a","message":"b","severity":{}}]}',
        ]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(RiverResponseError):
                parse_review(raw, "model")

    def test_decision_and_issue_list_must_agree(self):
        approval_with_issues = json.loads(REVIEW)
        approval_with_issues["decision"] = "APPROVE"
        rejection_without_issue = {"decision": "REJECT", "summary": "Reject", "issues": []}
        for value in (approval_with_issues, rejection_without_issue):
            with self.subTest(value=value), self.assertRaises(RiverResponseError):
                parse_review(json.dumps(value), "model")
        approval = {"decision": "APPROVE", "summary": "No blocking issue", "issues": []}
        self.assertEqual(parse_review(json.dumps(approval), "model")["decision"], "APPROVE")

    def test_contradictory_training_target_is_rejected_before_remote_work(self):
        boundary = RiverBoundary()
        correction = {"decision": "REJECT", "summary": "Unsupported rejection", "issues": []}
        with self.assertRaises(RiverResponseError):
            asyncio.run(
                self.provider(boundary).train(
                    [{"prompt": "abc", "completion": json.dumps(correction)}], name="invalid"
                )
            )
        self.assertEqual(boundary.calls, [])

    def test_base_and_checkpoint_use_identical_input_and_generation_settings(self):
        boundary = RiverBoundary()
        provider = self.provider(boundary)
        asyncio.run(provider.review("same held-out prompt"))
        checkpoint = "river://run/sampler_weights/learned"
        result = asyncio.run(provider.review("same held-out prompt", checkpoint))
        calls = [kwargs for name, kwargs in boundary.calls if name == "sample"]
        self.assertEqual(calls[0]["prompt_token_ids"], calls[1]["prompt_token_ids"])
        self.assertEqual(calls[0]["temperature"], calls[1]["temperature"])
        self.assertEqual(calls[0]["seed"], calls[1]["seed"])
        self.assertEqual(calls[1]["checkpoint"], checkpoint)
        self.assertEqual(result["model"], checkpoint)
        self.assertEqual(len(result["input_token_hash"]), 64)
        self.assertEqual(result["tokenizer_revision"], "fixture-tokenizer-revision")
        self.assertEqual(boundary.closed, 2)
        self.assertEqual(boundary.exited, 2)

    def test_training_only_reports_confirmed_steps_and_saved_checkpoint(self):
        boundary = RiverBoundary()
        events = []

        async def receive(event):
            events.append(event)

        examples = [
            {"prompt": "abc", "completion": REVIEW},
            {"prompt": "xyz", "completion": REVIEW},
        ]
        result = asyncio.run(
            self.provider(boundary).train(examples, name="learned", on_event=receive)
        )
        self.assertEqual(result["checkpoint"], "river://run/sampler_weights/learned")
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["metrics"]["losses"], [1.2, 1.2])
        self.assertNotIn("accuracy", result["metrics"])
        self.assertEqual(
            [event["type"] for event in events],
            [
                "preparing",
                "training_started",
                "training_step",
                "training_step",
                "saving",
                "checkpoint_saved",
            ],
        )
        batches = [value for name, value in boundary.calls if name == "forward_backward"]
        self.assertTrue(all(len(batch) == 2 for batch in batches))
        self.assertEqual(boundary.closed, 1)
        self.assertEqual(boundary.exited, 1)
        self.assertEqual(sum(name == "save_weights" for name, _ in boundary.calls), 1)

    def test_backward_failure_does_not_update_or_save_and_releases_session(self):
        boundary = RiverBoundary(fail_backward=True)
        with self.assertRaises(RiverOperationError) as caught:
            asyncio.run(
                self.provider(boundary).train(
                    [{"prompt": "abc", "completion": REVIEW}], name="failed"
                )
            )
        self.assertNotIn("private-token", str(caught.exception))
        self.assertFalse(any(name in {"optim_step", "save_weights"} for name, _ in boundary.calls))
        self.assertEqual(boundary.closed, 1)
        self.assertEqual(boundary.exited, 1)

    def test_save_timeout_does_not_emit_checkpoint_or_retry_training(self):
        boundary = RiverBoundary(fail_save=True)
        events = []

        async def receive(event):
            events.append(event)

        with self.assertRaises(RiverOperationError):
            asyncio.run(
                self.provider(boundary).train(
                    [{"prompt": "abc", "completion": REVIEW}], name="failed", on_event=receive
                )
            )
        self.assertNotIn("checkpoint_saved", [event["type"] for event in events])
        self.assertEqual(sum(name == "create_model" for name, _ in boundary.calls), 1)
        self.assertEqual(boundary.closed, 1)

    def test_review_failure_redacts_vendor_error_and_closes_connections(self):
        boundary = RiverBoundary(fail_sample=True)
        with self.assertRaises(RiverOperationError) as caught:
            asyncio.run(self.provider(boundary).review("review this"))
        self.assertNotIn("private-token", str(caught.exception))
        self.assertEqual(boundary.closed, 1)
        self.assertEqual(boundary.exited, 1)

    def test_token_budget_rejection_happens_before_remote_session(self):
        boundary = RiverBoundary()
        provider = self.provider(boundary)
        provider.max_batch_tokens = 4
        with self.assertRaisesRegex(ValueError, "RIVER_MAX_BATCH_TOKENS"):
            asyncio.run(provider.train([{"prompt": "abc", "completion": REVIEW}], name="oversized"))
        self.assertEqual(boundary.calls, [])

    def test_unsupported_training_method_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "implements SFT"):
            asyncio.run(RiverProvider(api_key="").train([], name="rl", method="rl"))

    def test_sft_then_rl_updates_one_model_and_uses_only_correction_labels(self):
        boundary = RiverBoundary()
        provider = self.provider(boundary)
        events = []

        async def receive(event):
            events.append(event)

        result = asyncio.run(
            provider.train(
                [{"prompt": "training prompt", "completion": REVIEW}],
                name="rl",
                method="sft+rl",
                on_event=receive,
            )
        )
        self.assertEqual(sum(name == "create_model" for name, _ in boundary.calls), 1)
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["metrics"]["sft_steps"], 2)
        self.assertEqual(result["metrics"]["rl_steps"], 1)
        self.assertEqual(result["metrics"]["rl_history"][0]["rewards"], [1.0, 0.0])
        self.assertEqual(result["metrics"]["rl_history"][0]["policy_before"], "policy-2")
        self.assertEqual(result["metrics"]["rl_history"][0]["policy_after"], "policy-3")
        rl_batch = [value for name, value in boundary.calls if name == "forward_backward"][-1]
        self.assertGreater(max(rl_batch[0]["advantages"]), 0)
        self.assertLess(min(rl_batch[1]["advantages"]), 0)
        sample = [value for name, value in boundary.calls if name == "sample"][0]
        decoded_prompt = "".join(chr(token) for token in sample["prompt_token_ids"])
        self.assertNotIn("REJECT", decoded_prompt)
        self.assertNotIn("catch_all", decoded_prompt)
        self.assertEqual(boundary.backward_options[-1]["expected_policy_id"], "policy-2")
        self.assertEqual(boundary.backward_options[-1]["loss_fn"], "cispo")
        self.assertIn("rl_step", [event["type"] for event in events])
        self.assertLess(
            [event["type"] for event in events].index("sft_checkpoint_saved"),
            [event["type"] for event in events].index("rl_sampling"),
        )
        self.assertEqual(result["sft_recovery_checkpoint"], "river://run/sampler_weights/rl-sft")
        self.assertEqual(result["metrics"]["rl_configuration"]["loss"], "cispo")
        self.assertEqual(
            result["metrics"]["rl_configuration"]["learning_rate"], provider.rl_learning_rate
        )

    def test_equal_rl_rewards_skip_optimizer_and_record_skip(self):
        boundary = RiverBoundary(rl_outputs=[REVIEW, REVIEW])
        result = asyncio.run(
            self.provider(boundary).train(
                [{"prompt": "abc", "completion": REVIEW}], name="uniform", method="sft+rl"
            )
        )
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["metrics"]["rl_steps"], 0)
        self.assertEqual(result["metrics"]["rl_status"], "skipped_zero_variance")
        self.assertEqual(sum(name == "optim_step" for name, _ in boundary.calls), 2)

    def test_rl_rejects_wrong_policy_and_inexact_tokens_before_update(self):
        for options in ({"wrong_policy": True}, {"inexact": True}):
            boundary = RiverBoundary(**options)
            with self.subTest(options=options), self.assertRaises(RiverOperationError):
                asyncio.run(
                    self.provider(boundary).train(
                        [{"prompt": "abc", "completion": REVIEW}],
                        name="bad-rollout",
                        method="sft+rl",
                    )
                )
            self.assertEqual(sum(name == "optim_step" for name, _ in boundary.calls), 2)
            saves = [value for name, value in boundary.calls if name == "save_weights"]
            self.assertEqual([save["name"] for save in saves], ["bad-rollout-sft"])
            self.assertEqual(boundary.closed, 1)

    def test_failed_rl_backward_never_submits_rl_optimizer(self):
        boundary = RiverBoundary(fail_rl_backward=True)
        with self.assertRaises(RiverOperationError):
            asyncio.run(
                self.provider(boundary).train(
                    [{"prompt": "abc", "completion": REVIEW}], name="bad-gradient", method="sft+rl"
                )
            )
        self.assertEqual(sum(name == "optim_step" for name, _ in boundary.calls), 2)
        self.assertEqual(boundary.closed, 1)

    def test_sft_checkpoint_survives_rl_failure_without_final_success(self):
        for options in ({"fail_rl_backward": True}, {"missing_policy": True}):
            boundary = RiverBoundary(**options)
            events = []

            async def receive(event):
                events.append(event)

            with self.subTest(options=options), self.assertRaises(RiverOperationError):
                asyncio.run(
                    self.provider(boundary).train(
                        [{"prompt": "abc", "completion": REVIEW}],
                        name="recoverable",
                        method="sft+rl",
                        on_event=receive,
                    )
                )
            checkpoints = [event for event in events if event["type"] == "sft_checkpoint_saved"]
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(
                checkpoints[0]["checkpoint"], "river://run/sampler_weights/recoverable-sft"
            )
            self.assertEqual(checkpoints[0]["steps"], 2)
            self.assertEqual(checkpoints[0]["method"], "sft")
            self.assertEqual(checkpoints[0]["metrics"]["rl_steps"], 0)
            self.assertEqual(checkpoints[0]["tokenizer_revision"], "fixture-tokenizer-revision")
            self.assertNotIn("checkpoint_saved", [event["type"] for event in events])
            saved = [value for name, value in boundary.calls if name == "save_weights"]
            self.assertEqual([value["name"] for value in saved], ["recoverable-sft"])
            self.assertTrue(saved[0]["immutable"])
            self.assertEqual(boundary.closed, 1)

    def test_actual_sdk_sample_contract_preserves_token_alignment(self):
        import river_client as river

        sample = river.Sample(
            tokens=[101, 102], text="answer", logprobs=[-0.2, -0.3], stop_reason="eos", model_step=2
        )
        datum = make_rl_datum([1, 2, 3], sample, 0.25)
        self.assertEqual(datum["input_ids"], [1, 2, 3, 101, 102])
        self.assertEqual(datum["old_logprobs"], [0, 0, -0.2, -0.3, 0])
        self.assertEqual(datum["advantages"], [0, 0, 0.25, 0.25, 0])


if __name__ == "__main__":
    unittest.main()
