"""River's real sampling and LoRA SFT APIs, with no simulated provider path.

The synchronous SDK stays in worker threads. Training events are forwarded to
the application event loop after operations actually finish. See docs/river.md.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import closing
from functools import lru_cache
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import threading
from typing import Any


class ProviderNotConfigured(RuntimeError):
    """A real provider cannot be called with the current configuration."""


class RiverOperationError(RuntimeError):
    """River did not confirm completion of an operation."""


class RiverResponseError(RiverOperationError):
    """The model returned a result that is not a valid review."""


EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


def parse_review(raw: str, model: str) -> dict[str, Any]:
    """Accept a JSON object or fenced JSON; never invent a review decision."""
    text = raw.strip()
    # Some reasoning models include a separate, closed reasoning segment.
    # Persist only the final answer, never an optional hidden reasoning segment.
    if text.startswith("<think>"):
        _, boundary, text = text.partition("</think>")
        if not boundary:
            raise RiverResponseError(
                "River exhausted its output before returning a review. Increase RIVER_MAX_TOKENS."
            )
        text = text.strip()
    if text.startswith("```"):
        match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        raise RiverResponseError(
            "River returned invalid review JSON. Retry the review or inspect the model output format."
        ) from None
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("decision"), str)
        or value["decision"] not in {"APPROVE", "REJECT"}
    ):
        raise RiverResponseError("River review must contain an APPROVE or REJECT decision.")
    if not isinstance(value.get("summary"), str) or not value["summary"].strip():
        raise RiverResponseError("River review is missing its summary.")
    issues = value.get("issues")
    if not isinstance(issues, list) or any(not isinstance(issue, dict) for issue in issues):
        raise RiverResponseError("River review issues must be a list of objects.")
    for issue in issues:
        if any(
            not isinstance(issue.get(key), str) or not issue[key].strip()
            for key in ("tag", "message")
        ):
            raise RiverResponseError("Each River issue needs a nonempty tag and message.")
        if not isinstance(issue.get("severity"), str) or issue["severity"] not in {
            "critical",
            "high",
            "medium",
            "low",
        }:
            raise RiverResponseError("River issue severity must be critical, high, medium or low.")
    if value["decision"] == "APPROVE" and issues:
        raise RiverResponseError("An APPROVE review must have an empty issues array.")
    if value["decision"] == "REJECT" and not issues:
        raise RiverResponseError("A REJECT review must identify at least one issue.")
    return {
        "decision": value["decision"],
        "summary": value["summary"],
        "issues": issues,
        "raw": text,
        "model": model,
    }


def make_sft_datum(
    tokenizer: Any, prompt: str, completion: str, *, max_tokens: int = 8192
) -> dict[str, list]:
    """Mask prompt tokens and align each completion target to its predecessor."""
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    completion_ids = tokenizer(completion, add_special_tokens=False)["input_ids"]
    eos = tokenizer.eos_token_id
    if not prompt_ids or not completion_ids or eos is None:
        raise ValueError("SFT requires a nonempty prompt, completion, and tokenizer EOS token.")
    # Shift inputs and targets together; exactly one EOS target is trained.
    sequence = prompt_ids + completion_ids + [eos]
    if len(sequence) > max_tokens:
        raise ValueError(
            f"Training example exceeds {max_tokens} tokens. Shorten its repository context; examples are never silently truncated."
        )
    return {
        "input_ids": sequence[:-1],
        "target_tokens": sequence[1:],
        "weights": [0.0] * (len(prompt_ids) - 1) + [1.0] * (len(completion_ids) + 1),
    }


def _number(
    name: str, default: float, minimum: float, maximum: float, *, integer: bool = False
) -> float | int:
    value = float(os.environ.get(name, str(default)))
    if (
        not math.isfinite(value)
        or not minimum <= value <= maximum
        or (integer and not value.is_integer())
    ):
        raise ValueError(
            f"{name} must be between {minimum:g} and {maximum:g}"
            + (" and an integer." if integer else ".")
        )
    return int(value) if integer else value


@lru_cache(maxsize=2)
def _load_tokenizer(base_model: str) -> Any:
    try:
        from huggingface_hub import snapshot_download
        from transformers import AutoTokenizer
    except ImportError:
        raise ProviderNotConfigured(
            "Run uv sync from the Reflex project directory to install the River dependencies."
        ) from None
    _configure_tokenizer_http()
    # A first run downloads tokenizer files, never model weights. Keep the
    # cache inside this workspace instead of writing to the user's home.
    cache = Path(__file__).resolve().parents[3] / ".cache" / "huggingface"
    try:

        def load_snapshot(snapshot: str) -> Any:
            tokenizer = AutoTokenizer.from_pretrained(
                snapshot, local_files_only=True, trust_remote_code=False
            )
            revision = Path(snapshot).name
            if re.fullmatch(r"[0-9a-f]{40}", revision):
                tokenizer.init_kwargs["_commit_hash"] = revision
            return tokenizer

        # A cached snapshot needs no network at all. An interrupted download
        # may leave an incomplete snapshot, in which case fetch its missing files.
        try:
            cached = snapshot_download(base_model, cache_dir=str(cache), local_files_only=True)
            return load_snapshot(cached)
        except (OSError, ValueError):
            pass
        snapshot = snapshot_download(
            base_model,
            cache_dir=str(cache),
            allow_patterns=[
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "added_tokens.json",
                "vocab.json",
                "vocab.txt",
                "merges.txt",
                "tokenizer.model",
                "spiece.model",
                "config.json",
                "chat_template.jinja",
                "additional_chat_templates/*.jinja",
            ],
            max_workers=2,
            etag_timeout=10,
        )
        return load_snapshot(snapshot)
    except Exception as error:
        raise RiverOperationError(
            f"Tokenizer setup failed ({type(error).__name__}). Check access to huggingface.co "
            "and the selected base model's tokenizer, then retry. No River request was submitted."
        ) from None


@lru_cache(maxsize=1)
def _configure_tokenizer_http() -> None:
    """Bound Hub metadata requests as well as the individual file downloads.

    Hub's default client has no timeout. Keep its request hooks (including the
    offline-mode guard) when configuring the documented client factory, so a
    replacement client created during a retry has the same finite bounds.
    """
    from huggingface_hub import get_session, set_client_factory
    from huggingface_hub.utils import httpx

    hooks = {name: list(handlers) for name, handlers in get_session().event_hooks.items()}

    def bound_request_timeout(request):
        # Hub APIs sometimes pass timeout=None explicitly, which overrides a
        # finite client default. Clamp at the request boundary, before transport.
        timeouts = request.extensions.setdefault("timeout", {})
        for phase, limit in {"connect": 10.0, "read": 30.0, "write": 30.0, "pool": 10.0}.items():
            current = timeouts.get(phase)
            if current is None or current > limit:
                timeouts[phase] = limit

    hooks.setdefault("request", []).append(bound_request_timeout)

    def factory():
        return httpx.Client(
            follow_redirects=True,
            event_hooks=hooks,
            timeout=httpx.Timeout(30.0, connect=10.0, pool=10.0),
        )

    set_client_factory(factory)


def _render_prompt(tokenizer: Any, prompt: str) -> str:
    return tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def _token_hash(token_ids: list[int]) -> str:
    return hashlib.sha256(json.dumps(token_ids, separators=(",", ":")).encode()).hexdigest()


def _tokenizer_revision(tokenizer: Any) -> str | None:
    revision = getattr(tokenizer, "init_kwargs", {}).get("_commit_hash")
    return revision if isinstance(revision, str) else None


def make_rl_datum(prompt_ids: list[int], sample: Any, advantage: float) -> dict[str, list]:
    """Align sampled-token policy gradient signals without retokenizing output."""
    if not prompt_ids or not sample.token_data_is_exact or not sample.tokens:
        raise RiverOperationError("RL requires a nonempty prompt and exact sampled token data.")
    if len(sample.tokens) != len(sample.logprobs) or any(
        not isinstance(value, (int, float)) or not math.isfinite(value) for value in sample.logprobs
    ):
        raise RiverOperationError("RL sampled tokens and finite log probabilities must align.")
    if not math.isfinite(advantage):
        raise RiverOperationError("RL advantage must be finite.")
    ids = prompt_ids + list(sample.tokens)
    return {
        "input_ids": ids,
        "attention_mask": [1] * len(ids),
        "old_logprobs": [0.0] * (len(prompt_ids) - 1) + list(sample.logprobs) + [0.0],
        "advantages": [0.0] * (len(prompt_ids) - 1) + [advantage] * len(sample.tokens) + [0.0],
    }


class RiverProvider:
    """An explicit, bounded River adapter; construction never makes requests."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_model: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.environ.get("RIVER_API_KEY", "")
        ).strip()
        self.base_model = (
            base_model
            or os.environ.get("RIVER_BASE_MODEL")
            or os.environ.get("RIVER_MODEL")
            or "Qwen/Qwen3.5-9B"
        )
        self.endpoint = endpoint or os.environ.get("RIVER_ENDPOINT", "api.river.ai")
        if not re.fullmatch(r"[A-Za-z0-9.-]+", self.endpoint):
            raise ValueError(
                "RIVER_ENDPOINT must be a hostname, such as api.river.ai, without a URL scheme or path."
            )
        self.timeout = _number("RIVER_TIMEOUT_SECONDS", 180, 1, 1800)
        self.training_timeout = _number("RIVER_TRAIN_TIMEOUT_SECONDS", 600, 1, 3600)
        self.max_tokens = _number("RIVER_MAX_TOKENS", 2048, 32, 16384, integer=True)
        self.steps = _number("RIVER_TRAIN_MAX_STEPS", 4, 1, 20, integer=True)
        self.learning_rate = _number("RIVER_LEARNING_RATE", 2e-4, 1e-7, 1e-2)
        self.lora_rank = _number("RIVER_LORA_RANK", 16, 1, 32, integer=True)
        self.max_example_tokens = _number(
            "RIVER_MAX_EXAMPLE_TOKENS", 8192, 128, 32768, integer=True
        )
        self.max_batch_tokens = _number("RIVER_MAX_BATCH_TOKENS", 32768, 128, 131072, integer=True)
        self.rl_steps = _number("RIVER_RL_MAX_STEPS", 1, 1, 2, integer=True)
        self.rl_group_size = _number("RIVER_RL_GROUP_SIZE", 2, 2, 4, integer=True)
        self.rl_max_tokens = _number("RIVER_RL_MAX_TOKENS", 1024, 32, 2048, integer=True)
        self.rl_learning_rate = _number("RIVER_RL_LEARNING_RATE", 1e-5, 1e-7, 1e-3)

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _sdk(self) -> Any:
        if not self.configured:
            raise ProviderNotConfigured(
                "Set RIVER_API_KEY in the server environment and restart Reflex to enable real River reviews and training."
            )
        try:
            return importlib.import_module("river_client")
        except ImportError:
            raise ProviderNotConfigured(
                "Run uv sync from the Reflex project directory to install the River dependencies."
            ) from None

    def _client(self, sdk: Any) -> Any:
        return sdk.Client(
            api_key=self._api_key,
            endpoint=self.endpoint,
            timeout=self.timeout,
            enable_retries=False,
        )

    @staticmethod
    def _failure(operation: str, error: Exception) -> RiverOperationError:
        # Vendor errors may embed request content or credentials. Return only a
        # safe class name; the application can expose the operation and remedy.
        kind = type(error).__name__
        return RiverOperationError(
            f"River {operation} failed ({kind}). Check credentials, model access, capacity and run status in the River Console. "
            "Completion is unconfirmed; inspect the run before retrying a training operation."
        )

    async def review(self, prompt: str, checkpoint: str | None = None) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Review prompt cannot be empty.")
        if checkpoint is not None and not checkpoint.startswith("river://"):
            raise ValueError("Checkpoint must be a River checkpoint URI.")
        sdk = self._sdk()

        def run() -> dict[str, Any]:
            try:
                tokenizer = _load_tokenizer(self.base_model)
                prompt_ids = tokenizer(_render_prompt(tokenizer, prompt), add_special_tokens=False)[
                    "input_ids"
                ]
                if len(prompt_ids) > self.max_example_tokens:
                    raise ValueError(
                        f"Review prompt exceeds {self.max_example_tokens} tokens. Reduce repository context."
                    )
                with closing(self._client(sdk)) as client:
                    with client.session(timeout=self.timeout, project="reflex-review") as session:
                        samples = session.sample(
                            prompt_token_ids=prompt_ids,
                            tokenizer=tokenizer,
                            base_model=self.base_model,
                            checkpoint=checkpoint,
                            num_samples=1,
                            max_tokens=self.max_tokens,
                            temperature=0.0,
                            seed=42,
                            timeout=self.timeout,
                        )
                        if not samples or not samples[0]:
                            raise RiverResponseError(
                                "River returned no review sample. Check model availability and retry."
                            )
                        return {
                            **parse_review(samples[0][0].text, checkpoint or self.base_model),
                            "input_token_hash": _token_hash(prompt_ids),
                            "tokenizer_revision": _tokenizer_revision(tokenizer),
                            "base_model": self.base_model,
                            "generation": {
                                "temperature": 0.0,
                                "seed": 42,
                                "max_tokens": self.max_tokens,
                                "thinking": False,
                            },
                        }
            except (ProviderNotConfigured, RiverOperationError, ValueError):
                raise
            except Exception as error:
                raise self._failure("review", error) from None

        return await asyncio.to_thread(run)

    def _rl_configuration(self) -> dict[str, Any]:
        return {
            "loss": "cispo",
            "eps_max": 6.0,
            "learning_rate": self.rl_learning_rate,
            "beta1": 0.9,
            "beta2": 0.95,
            "eps": 1e-8,
            "weight_decay": 0.0,
            "grad_clip_norm": 1.0,
            "group_size": self.rl_group_size,
            "max_rounds": self.rl_steps,
            "max_generated_tokens": self.rl_max_tokens,
            "advantage": "group_centered",
            "normalization": "all_generated_tokens",
            "scorer": "core.score_review.normalized_reward.v1",
            "selection": "first_training_examples_in_order",
        }

    def _train_rl(
        self,
        model: Any,
        examples: list[dict[str, str]],
        prompts: list[list[int]],
        policy: Any,
        name: str,
        emit: Callable[[dict], None],
        check_cancelled: Callable[[], None],
    ) -> list[dict[str, Any]]:
        """Small synchronous CISPO updates on the same post-SFT live model."""
        from reflex.core import score_review

        if policy is None:
            raise RiverOperationError(
                "River did not return a committed SFT policy. RL needs policy provenance; use sft mode or ask River to enable policy versions."
            )
        history: list[dict[str, Any]] = []
        for attempt in range(self.rl_steps):
            check_cancelled()
            index = attempt % len(examples)
            prompt_ids = prompts[index]
            gold = parse_review(examples[index]["completion"], self.base_model)
            gold["critical_issue_tags"] = [
                issue["tag"] for issue in gold["issues"] if issue["severity"] == "critical"
            ]
            emit(
                {
                    "type": "rl_sampling",
                    "attempt": attempt + 1,
                    "total_attempts": self.rl_steps,
                    "group_size": self.rl_group_size,
                    "method": "rl",
                }
            )
            groups = model.sample(
                prompt_token_ids=prompt_ids,
                num_samples=self.rl_group_size,
                max_tokens=self.rl_max_tokens,
                temperature=1.0,
                top_p=1.0,
                top_k=-1,
                seed=42 + attempt,
                timeout=self.training_timeout,
            )
            if len(groups) != 1 or len(groups[0]) != self.rl_group_size:
                raise RiverOperationError(
                    "River returned an incomplete RL sample group. No RL update was submitted."
                )
            samples = groups[0]
            rewards: list[float] = []
            records = []
            for sample in samples:
                if sample.policy_version is None or sample.policy_version.id != policy.id:
                    raise RiverOperationError(
                        "RL rollout weights do not match the committed training policy. No RL update was submitted."
                    )
                make_rl_datum(prompt_ids, sample, 0.0)  # Validate exact alignment before scoring.
                if sample.stop_reason not in {"stop", "eos", "length"}:
                    raise RiverOperationError(
                        "River returned an unknown RL completion status. No RL update was submitted."
                    )
                components = None
                if sample.stop_reason != "length":
                    try:
                        prediction = parse_review(sample.text, self.base_model)
                        components = score_review(prediction, gold)
                    except RiverResponseError:
                        pass
                reward = float(components["normalized_reward"]) if components else 0.0
                rewards.append(reward)
                records.append(
                    {
                        "reward": reward,
                        "score": components,
                        "generated_tokens": len(sample.tokens),
                        "stop_reason": sample.stop_reason,
                        "output_token_hash": _token_hash(list(sample.tokens)),
                        "policy_id": policy.id,
                    }
                )
            mean_reward = sum(rewards) / len(rewards)
            record = {
                "attempt": attempt + 1,
                "example_index": index,
                "input_token_hash": _token_hash(prompt_ids),
                "mean_reward": mean_reward,
                "rewards": rewards,
                "rollouts": records,
                "policy_before": policy.id,
                "updated": False,
                "configuration": self._rl_configuration(),
                "generation": {
                    "temperature": 1.0,
                    "top_p": 1.0,
                    "top_k": -1,
                    "seed": 42 + attempt,
                    "max_tokens": self.rl_max_tokens,
                },
            }
            check_cancelled()
            if max(rewards) - min(rewards) <= 1e-12:
                record["skip_reason"] = "zero_reward_variance"
                history.append(record)
                emit({"type": "rl_skipped", "method": "rl", **record})
                continue
            response_tokens = sum(len(sample.tokens) for sample in samples)
            batch = [
                make_rl_datum(prompt_ids, sample, (reward - mean_reward) / response_tokens)
                for sample, reward in zip(samples, rewards, strict=True)
            ]
            if sum(len(datum["input_ids"]) for datum in batch) > self.max_batch_tokens:
                raise RiverOperationError(
                    "RL batch exceeded the configured token bound. No RL update was submitted."
                )
            result = model.forward_backward(
                batch,
                loss_fn="cispo",
                eps_max=6.0,
                zero_out=True,
                expected_policy_id=policy.id,
                timeout=self.training_timeout,
            )
            loss = result.metrics.get("loss")
            if not isinstance(loss, (int, float)) or not math.isfinite(loss):
                raise RiverOperationError(
                    "River returned no finite RL loss. No RL optimizer step was submitted."
                )
            check_cancelled()
            optimized = model.optim_step(
                lr=self.rl_learning_rate,
                beta1=0.9,
                beta2=0.95,
                grad_clip_norm=1.0,
                expected_policy_id=policy.id,
                idempotency_key=f"{name}-rl-{attempt + 1}",
                timeout=self.training_timeout,
            )
            committed = optimized.policy_version
            if (
                committed is None
                or committed.parent_id != policy.id
                or committed.step != policy.step + 1
            ):
                raise RiverOperationError(
                    "River did not confirm the expected RL policy update. Inspect the run before retrying."
                )
            record.update(
                {
                    "updated": True,
                    "loss": float(loss),
                    "policy_after": committed.id,
                    "response_tokens": response_tokens,
                    "training_tokens": sum(len(datum["input_ids"]) for datum in batch),
                }
            )
            policy = committed
            history.append(record)
            emit({"type": "rl_step", "method": "rl", **record})
        return history

    async def train(
        self,
        examples: list[dict[str, str]],
        *,
        name: str,
        method: str = "sft",
        on_event: EventCallback | None = None,
    ) -> dict[str, Any]:
        if method not in {"sft", "sft+rl"}:
            raise ValueError(
                "This integration implements SFT and optional SFT+RL; choose sft or sft+rl."
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
            raise ValueError(
                "Checkpoint name must be 1–80 letters, digits, underscores or hyphens, starting with a letter or digit."
            )
        if not 1 <= len(examples) <= 32:
            raise ValueError("SFT requires between 1 and 32 reviewed examples.")
        for example in examples:
            if any(
                not isinstance(example.get(key), str) or not example[key].strip()
                for key in ("prompt", "completion")
            ):
                raise ValueError(
                    "Every SFT example needs a nonempty prompt and corrected completion."
                )
            parse_review(example["completion"], self.base_model)
        sdk = self._sdk()
        loop = asyncio.get_running_loop()
        cancelled = threading.Event()

        def check_cancelled() -> None:
            if cancelled.is_set():
                raise RiverOperationError(
                    "Training was cancelled. Any in-flight River operation may finish; no new step will be submitted."
                )

        def emit(event: dict[str, Any]) -> None:
            check_cancelled()
            if on_event is not None:
                future = asyncio.run_coroutine_threadsafe(on_event(event), loop)
                try:
                    future.result(timeout=30)
                except Exception:
                    future.cancel()
                    raise RiverOperationError(
                        "Training stopped because its progress could not be persisted. Check the Reflex server before retrying."
                    ) from None

        def run() -> dict[str, Any]:
            try:
                emit(
                    {
                        "type": "preparing",
                        "message": "Tokenizing reviewed examples",
                        "examples": len(examples),
                        "method": "sft",
                    }
                )
                tokenizer = _load_tokenizer(self.base_model)
                rendered = [_render_prompt(tokenizer, item["prompt"]) for item in examples]
                prompts = [
                    tokenizer(prompt, add_special_tokens=False)["input_ids"] for prompt in rendered
                ]
                batch = [
                    make_sft_datum(
                        tokenizer,
                        rendered[index],
                        item["completion"],
                        max_tokens=self.max_example_tokens,
                    )
                    for index, item in enumerate(examples)
                ]
                token_count = sum(len(item["input_ids"]) for item in batch)
                if token_count > self.max_batch_tokens:
                    raise ValueError(
                        f"SFT batch has {token_count} tokens, exceeding RIVER_MAX_BATCH_TOKENS={self.max_batch_tokens}. Reduce repository context or select fewer examples."
                    )
                if method == "sft+rl" and any(
                    (len(prompts[index % len(prompts)]) + self.rl_max_tokens) * self.rl_group_size
                    > self.max_batch_tokens
                    for index in range(self.rl_steps)
                ):
                    raise ValueError(
                        "Potential RL rollout batch exceeds RIVER_MAX_BATCH_TOKENS. Reduce prompt context, rollout group size or RL output tokens before training."
                    )
                check_cancelled()
                with closing(self._client(sdk)) as client:
                    with client.session(
                        timeout=self.training_timeout, project="reflex", run=name
                    ) as session:
                        model = session.create_model(
                            base_model=self.base_model,
                            lora=sdk.LoraConfig(rank=self.lora_rank, seed=42),
                            tokenizer=tokenizer,
                            timeout=self.training_timeout,
                        )
                        emit(
                            {
                                "type": "training_started",
                                "model": model.model_id,
                                "steps": self.steps,
                                "method": "sft",
                                "batch_tokens": token_count,
                            }
                        )
                        losses: list[float] = []
                        policy = None
                        for step in range(self.steps):
                            check_cancelled()
                            result = model.forward_backward(
                                batch, loss_fn="cross_entropy", timeout=self.training_timeout
                            )
                            check_cancelled()
                            loss = result.metrics.get("loss")
                            if not isinstance(loss, (int, float)) or not math.isfinite(loss):
                                raise RiverOperationError(
                                    "River returned no finite SFT loss. No optimizer step was submitted; inspect the run in the River Console."
                                )
                            optimized = model.optim_step(
                                lr=self.learning_rate,
                                grad_clip_norm=1.0,
                                timeout=self.training_timeout,
                                idempotency_key=f"{name}-step-{step + 1}",
                            )
                            policy = getattr(optimized, "policy_version", None)
                            losses.append(float(loss))
                            emit(
                                {
                                    "type": "training_step",
                                    "step": step + 1,
                                    "total_steps": self.steps,
                                    "loss": float(loss),
                                    "method": "sft",
                                }
                            )
                        provenance = {
                            "model": self.base_model,
                            "tokenizer_revision": _tokenizer_revision(tokenizer),
                            "input_token_hashes": [_token_hash(prompt) for prompt in prompts],
                            "generation": {
                                "temperature": 0.0,
                                "seed": 42,
                                "max_tokens": self.max_tokens,
                                "thinking": False,
                            },
                        }
                        sft_metrics = {
                            "initial_loss": losses[0],
                            "final_loss": losses[-1],
                            "losses": losses,
                            "examples": len(batch),
                            "method": "sft",
                            "batch_tokens": token_count,
                            "training_tokens": token_count * len(losses),
                            "learning_rate": self.learning_rate,
                            "lora_rank": self.lora_rank,
                            "lora_seed": 42,
                            "sft_steps": len(losses),
                            "rl_steps": 0,
                            "rl_attempts": 0,
                            "rl_status": "not_requested",
                        }
                        recovery_checkpoint = None
                        if method == "sft+rl":
                            check_cancelled()
                            recovery = model.save_weights(
                                f"{name}-sft",
                                mode="inference",
                                immutable=True,
                                timeout=self.training_timeout,
                            )
                            if not isinstance(recovery.path, str) or not recovery.path.startswith(
                                "river://"
                            ):
                                raise RiverOperationError(
                                    "River did not confirm the recovery SFT checkpoint. RL was not started; inspect the training run before retrying."
                                )
                            recovery_checkpoint = recovery.path
                            emit(
                                {
                                    "type": "sft_checkpoint_saved",
                                    "checkpoint": recovery_checkpoint,
                                    "steps": len(losses),
                                    "metrics": sft_metrics,
                                    "method": "sft",
                                    **provenance,
                                }
                            )
                        rl_history = (
                            self._train_rl(
                                model, examples, prompts, policy, name, emit, check_cancelled
                            )
                            if method == "sft+rl"
                            else []
                        )
                        rl_updates = sum(record["updated"] for record in rl_history)
                        emit(
                            {
                                "type": "saving",
                                "message": "Saving learned weights",
                                "method": method,
                            }
                        )
                        checkpoint = model.save_weights(
                            name, mode="inference", immutable=True, timeout=self.training_timeout
                        )
                        if not isinstance(checkpoint.path, str) or not checkpoint.path.startswith(
                            "river://"
                        ):
                            raise RiverOperationError(
                                "River did not return a saved checkpoint URI. Inspect the training run before retrying."
                            )
                        result = {
                            "checkpoint": checkpoint.path,
                            "steps": len(losses) + rl_updates,
                            **provenance,
                            "sft_recovery_checkpoint": recovery_checkpoint,
                            "metrics": {
                                **sft_metrics,
                                "method": method,
                                "training_tokens": token_count * len(losses)
                                + sum(record.get("training_tokens", 0) for record in rl_history),
                                "rl_steps": rl_updates,
                                "rl_attempts": len(rl_history),
                                "rl_history": rl_history,
                                "rl_configuration": self._rl_configuration()
                                if method == "sft+rl"
                                else None,
                                "rl_status": "updated"
                                if rl_updates
                                else ("skipped_zero_variance" if rl_history else "not_requested"),
                            },
                        }
                        emit({"type": "checkpoint_saved", **result})
                        return result
            except (ProviderNotConfigured, RiverOperationError, ValueError):
                raise
            except Exception as error:
                raise self._failure("training", error) from None

        try:
            return await asyncio.to_thread(run)
        except asyncio.CancelledError:
            cancelled.set()
            raise
