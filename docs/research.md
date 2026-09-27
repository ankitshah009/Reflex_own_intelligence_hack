# Reflex integration decision record

Research date: 2026-09-27. This record distinguishes a documented API contract from an integration actually exercised against a live service. Public documentation and source were inspected; this research did not spend River credits or execute remote inference/training.

## Decision

Use UFO as the source of observable work, Reflex as the experience/feedback/evaluation ledger, and River as a narrowly scoped PR-review specialist. Start with human-approved SFT; optional `sft+rl` continues on that same live adapter. Call the specialist through a UFO tool. Keep remote deployment and RL separate capabilities whose status cannot be inferred from successful SFT.

The proposed loop is supported in principle. Improvement, format reliability, queue latency, account access, and the sponsor runtime's actual installation still require live evidence. Ten to thirty examples are a hypothesis about data sufficiency, not an accuracy guarantee. River explicitly recommends evaluating beyond its tiny SFT demonstration. [River SFT guide](https://docs.river.ai/guides/sft/)

## Versions and source authority

- River's current reference identifies **river-client 0.11.0**. Pin the SDK and record its installed version in run metadata. [Python reference](https://docs.river.ai/python-api/)
- UFO source inspected at commit **63ba388ed449ff46c9d70744119dffc85df0fbf8**, distribution version `0.1.0`. Use the commit, not the generic distribution version, to identify the integration contract. [UFO package metadata](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/pyproject.toml)
- Account-authorized models come from `get_capabilities()` at runtime. A catalog entry does not establish this account's permission or current capacity. [Models and access](https://docs.river.ai/guides/models/)

## River: confirmed contract and constraints

**Training changes a LoRA adapter.** River's adapter changes the behavior of a fixed base model and needs that base model for inference. Both SFT and RL use the adapter mechanism. The default rank range is 1–32, subject to server limits. Record base model, tokenizer revision, LoRA initialization seed/rank, learning rate, dataset hash, and rendering version. [Adapter guide](https://docs.river.ai/guides/lora/)

**The SFT path is token based.** Build aligned `input_ids`, next-token `target_tokens`, and `weights`; mask prompt positions so only the corrected completion trains. A one-position mask error changes the objective. `forward_backward(..., loss_fn="cross_entropy")` calculates gradients; `optim_step(...)` changes the weights. For a fail-closed small run, wait for a successful backward result before submitting the optimizer update. The convenience `train_step` pipelines both and can submit the optimizer before a backward failure is known. [SFT guide](https://docs.river.ai/guides/sft/), [Python reference](https://docs.river.ai/python-api/)

**Saved-weight inference does not require dedicated deployment.** `session.sample(..., base_model=..., checkpoint=...)` loads a saved adapter for sampling. `Session.sample` and `Model.sample` return nested prompt/sample lists; `Client.sample` returns a flat list. Sampling exposes no documented `response_format` parameter. Validate final JSON locally; a malformed/truncated result is an error, never an inferred approval. [SFT checkpoint example](https://docs.river.ai/guides/sft/), [Python reference](https://docs.river.ai/python-api/)

**Rendering must match.** Raw prompt strings are valid in River's SFT examples, but the Qwen3.5 model card uses chat formatting and thinking by default. It does not officially support `/nothink`; nonthinking behavior is controlled through the chat template. Use one versioned rendering path for training and inference. Any template change invalidates an existing prompt-comparison claim. A bounded token budget can truncate reasoning before the final JSON. [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B)

**Lifecycle and timeouts matter.** Use a session context manager, save before exit, and close the client. Queued sampling blocks until completion unless using submit/poll primitives; this does not imply token streaming. Stream Reflex's real operation events while waiting. A timeout is not proof that submitted remote work stopped. [Sessions and requests](https://docs.river.ai/guides/requests/)

**A checkpoint is not a permanent downloaded model.** Training checkpoints include optimizer state; inference checkpoints contain PEFT weights. A `river://` identifier survives its session. The API's default and maximum checkpoint TTL is one year. Keep checkpoint identity/step/type, and do not claim a local export unless the weights were actually downloaded. [Checkpoint guide](https://docs.river.ai/guides/checkpoints/), [Python reference](https://docs.river.ai/python-api/)

**OpenAI-compatible serving is gated.** Dedicated streaming deployment needs a team API key and River-enabled deployment/model access; a personal key cannot create it. Deployment capacity has a separate lifecycle from training sessions. Ending a session does not release a deployment. This is why the first tool integration uses checkpoint sampling. [Deploy and serve](https://docs.river.ai/guides/deployments/)

## UFO: verified extension boundary

UFO's public Python surface is `ufo.sdk.*`. A `ufo.extension` entry point is a callable returning a `Manifest`; tools use `ToolDef` with a Pydantic `input_model` and an async handler producing `ToolResult`. Importing a package alone does not prove its tool is active. [Public tool exports](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/sdk/tools.py), [official sample](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/extensions/sample/ufo_ext_sample/manifest.py)

Useful lifecycle payloads are `UserPromptSubmit.text`, `PostToolUse.tool_name/tool_input/output/call`, `PostToolUseFailure`, and `Stop.answer`. `Stop` is observed before the turn commits. Failed argument validation and unknown tool names do not produce `PostToolUseFailure`. Therefore hook output alone is not proof of a fully committed, exhaustive transcript. `HookContext` supplies workspace-scoped extension state and optional turn/agent/sandbox; turn hooks must not reenter the agent loop. [Hook types](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/runtime/ext/manifest.py)

The durable extension store provides `get`, `put`, conditional `put_if`, and prefix `list`. Ordinary `put` is an upsert, not compare-and-swap. Use stable event/experience identity and idempotent transfer; never count replayed events as new experience. Store observable inputs, tool results, final decisions, and human feedback, rather than treating hidden model reasoning as required training data. [Scoped store implementation](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/runtime/ext/context.py)

**Source/spec discrepancy:** `spec.md` describes isolated JS third-party extensions with a limited manifest. At the pinned commit, the actual Python loader also discovers separately installed Python entry points and does not include `hooks` in its privileged-capability gate. This supports a self-hosted Python hooks integration. It does **not** establish permission to upload it to UFO's hosted service. Treat hosted installation as unverified. [Design spec](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/spec.md#third-party-extensions), [actual loader](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/host/ext/loader.py)

Activation is explicit: without a lockfile the loader considers discovered extensions; with a lockfile only matching pinned digests qualify. An active pack narrows that set to its named extensions. The stock `assistant` pack does not name Reflex. A custom pack must include it, and the pack's name must differ from a bundled extension name. `ufoctl ext install` pins an already-installed package from an enabled catalog; it is not a Python package installer. Verify installed CLI help before presenting commands as executable. [Loader](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/host/ext/loader.py), [CLI](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/cli.py)

Two setup traps were checked against source: upstream `.python-version` selects 3.12 unless the installer explicitly overrides it, while Reflex requires 3.13 or newer; and the stock generated configuration selects a Perplexity search backend which is absent from the minimal Reflex pack. Create the minimal configuration before initialization. `UFO_CONFIG`/`UFOCTL_DIR` and client `UFO_HOME` redirect runtime configuration and credentials into this repository without changing `HOME`. [Upstream Python pin](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/.python-version), [Runtime configuration](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/cli.py), [Search backend selection](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/core/src/ufo/serve.py), [Client configuration](https://github.com/ufo-ai/ufo-core/blob/63ba388ed449ff46c9d70744119dffc85df0fbf8/client/src/config.rs)

The local UFO carrier permits host reads and does not enforce network isolation at the kernel. Connected terminal execution is the member's local machine. Do not describe that as containment for arbitrary untrusted PR execution. [UFO security model](https://github.com/ufo-ai/ufo-core#security-model)

## Experiment contract

These are Reflex experiment requirements, rather than provider guarantees:

| Condition | Weights | Context |
| --- | --- | --- |
| Base | Original base | Task and repository context only |
| Memory | Original base | Task plus frozen, approved training feedback |
| Learned | Saved trained adapter on the same base | Exactly the same prompt and frozen memory as Memory |

The claim “the prompt did not change” applies to **Memory versus Learned**. Base versus Memory intentionally changes context. Store both logical-prompt and rendered-input hashes so a hidden template change cannot masquerade as weight improvement.

Freeze evaluation cases and human gold labels before training. Partition by PR/bug family; reject normalized exact content duplicates across splits. Hash checks cannot detect all semantic duplicates. Exclude held-out labels, corrections, previous answers, and evaluation trajectories from SFT and memory. Changing memory, model, parser, generation budget, scoring, or checkpoint requires a new evaluation record.

Report decision accuracy with its denominator, per-condition invalid-output count, false approvals/false rejections, issue-tag precision/recall, and per-case results. Label a small synthetic suite as such. Never hardcode uplift, hide failures, choose only successful examples, or call training-loss reduction generalization. River's evaluation documentation likewise requires held-out questions and warns that semantic duplicates remain the caller's responsibility. [Evaluation and recovery](https://docs.river.ai/guides/rl-checkpoints/)

For this review-only specialist, test results are **input evidence**. Rewarding it merely because a supplied PR's tests passed gives the same reward regardless of its review and is not useful causal feedback. RL scores the generated review against confirmed training corrections. Group-relative RL can produce no gradient when all attempts have equal reward; a completed batch does not necessarily mean an optimizer update. [First RL run](https://docs.river.ai/guides/rl-sync/)

### Optional RL: independent source audit

The current adapter's RL data construction and API calls were checked against installed `river-client==0.11.0` (`client.py`, `types.py`) and the official low-level guide. This is source evidence, not a live service result.

- **Inputs:** the same rendered training prompt IDs are sampled at temperature 1, top-p 1, top-k −1. Correction JSON stays in the local scorer. The exact generated IDs and corresponding chosen-token log probabilities form the training datum; no response retokenization occurs. Prompt positions have zero advantage, the first response prediction starts at prompt length minus one, and the final position is zero.
- **Estimator:** subtract the group mean reward, then divide once by all generated tokens in that group. Malformed and length-limited outputs receive zero reward but still participate in the baseline and token denominator. This is a deliberate truncation policy. The documented losses sum token contributions. `cispo` accepts `input_ids`, `old_logprobs`, `advantages`, with `eps_max=6.0`. [Loss contract](https://docs.river.ai/guides/losses/)
- **Updates:** exact rollout data and the current committed policy are required. The code waits for finite backward loss, submits one guarded optimizer operation, then requires a child policy with the next step. Equal-reward groups skip backward/optimizer entirely. Counts separate attempts, confirmed RL updates, and SFT steps; local `model.step` is not used as confirmation. [Custom RL primitives](https://docs.river.ai/guides/rl-primitives/)

Current limitations are explicit: only the first one or two approved training examples receive RL attempts. The decision/tag reward does not evaluate explanatory prose or execution outcomes; tag synonyms count as errors. Reusing those labels after SFT is training, not held-out evaluation. No gain is promised, and an all-equal rollout group can leave the result SFT-only. The implementation now saves an immutable SFT checkpoint before optional RL, so an RL failure preserves usable SFT weights while the combined job remains failed. Inspect River before retrying any operation whose completion was not confirmed.

The history retains reward components, generation settings, policy IDs and token hashes, but does not retain original token IDs/log probabilities or every loss/optimizer setting. It can document that an update was confirmed; it cannot fully reconstruct the submitted gradient data. A recoverable custom trainer would need those additional bounded artifacts. The present implementation neither replays failed runs nor claims exact resumption. [Custom-loop recordkeeping](https://docs.river.ai/guides/rl-primitives/)

## Cost, privacy, and unresolved evidence

River Cloud stores training data and weights remotely; downloaded weights are supported as a product capability. This is not an all-local learning system. No zero-retention guarantee was established by this audit. Keep credentials server-side and do not upload repository secrets or raw personal information. [Cloud versus on-premises](https://docs.river.ai/guides/models/)

River's published preview rates on the research date list Qwen3.5-9B at $0.66/M prompt, $1.99/M completion, and $1.46/M training tokens; Qwen3.6-35B-A3B-FP8 at $0.33/$0.82/$1.00 respectively. Smallest parameter count is therefore not the cheapest listed rate. Checkpoint storage is listed at $0.10/GB/month. Rates can change; a token cap is a usage bound, not an account spending guarantee. No account balance, credits, or exact end-to-end bill was verified. [River pricing](https://river.ai/api)

## Acceptance evidence before claiming the complete loop

1. Installed UFO runtime boots with the Reflex manifest and tool visible; a real task creates observable events tied to its actual workspace and turn.
2. Transfer survives retry without duplicates; human correction reaches the training split; unapproved and held-out examples are excluded.
3. A live River call verifies this account's selected model and output parser. Missing credentials, denied access, capacity errors, malformed output, and timeout have explicit UI states.
4. A real backward/optimizer sequence saves a checkpoint whose URI is persisted. Optional RL displays confirmed updates or an explicit zero-variance skip; SFT completion does not imply an RL update.
5. Replay runs frozen held-out cases in all three conditions, stores actual responses and hashes, and publishes measured results even if the learned model loses.
6. UFO invokes the saved specialist on a new PR after training. A restart preserves experiences/checkpoints and identifies interrupted jobs without silently rerunning paid training.

Until these observations exist, describe the implementation as built or locally verified with the remaining live steps named. Research alone cannot certify account access, measured improvement, or an end-to-end sponsor demo.
