# River integration

Reflex uses `river-client==0.11.0` and the same base model for initial reviews and
training. SDK signatures were checked against the installed package on Python
3.14.7. Missing credentials fail explicitly; no result, loss, checkpoint, or
evaluation score is simulated.

## Setup

Run `uv sync` from this repository. Create an API key in the
[River Console](https://console.river.ai), then configure the server environment
before starting Reflex:

```sh
export RIVER_API_KEY="your-river-key"
export RIVER_BASE_MODEL="Qwen/Qwen3.5-9B"
export RIVER_TRAIN_MAX_STEPS="4"
```

The key must have access to the selected model. River requests consume account
capacity and balance; check access and pricing before enabling live operations.
See the official [authentication and model access instructions](https://docs.river.ai/quickstart/).
Keep the key in your own environment or ignored `.env`; never paste it into a
task, fixture, log, or versioned file. Restart the server after changing it.

## What runs

`RiverProvider.review(prompt, checkpoint=None)` loads the model's tokenizer and
applies its chat template with thinking disabled. Base and learned review calls
use identical tokenization, temperature zero, and seed 42. The only changed
sampling argument is the checkpoint. The parser requires a JSON review with
`decision`, `summary`, and an `issues` array; every issue has `tag`, `message`,
and `severity` (`critical`, `high`, `medium`, or `low`). Invalid output is an
error, never an implicit approval. Approval requires an empty issue list;
rejection requires at least one issue. Results carry a hash of the actual input
token IDs, tokenizer revision when available, and generation settings. Optional
thinking segments are removed before the final answer is retained.

`RiverProvider.train(examples, name=..., on_event=...)` accepts reviewed
prompt/completion pairs. Completion tokens alone contribute to loss. Each
step submits a forward/backward operation, waits for its result, then applies
the optimizer update. All examples participate in every step. The final
inference checkpoint is saved under an immutable name, and its actual River
URI is returned. Events report confirmed work and observed loss.

The documented primitives are [session sampling, LoRA creation, optimizer
updates and saved checkpoints](https://docs.river.ai/python-api/), following
the [SFT training flow](https://docs.river.ai/guides/sft/).

The caller must retain its own experience IDs and prompt hashes with the
returned checkpoint. Training loss measures fitting the examples; held-out
evaluation establishes whether review judgment improved.

## Optional reinforcement learning

Use `method="sft+rl"` to continue updating the **same live model** after SFT.
Before RL starts, Reflex saves an immutable `<name>-sft` recovery checkpoint
and emits `sft_checkpoint_saved` so the server can retain it independently.
An RL error leaves that completed SFT checkpoint available; it does not report
a successful final RL checkpoint. Plain SFT saves only its final checkpoint.
The default remains `sft`. The bounded synchronous loop follows River's
[RL primitives](https://docs.river.ai/guides/rl-primitives/): grouped sampling,
exact generated tokens/log probabilities, group-centered advantages,
token-normalized CISPO loss, and a guarded optimizer update.

Each round uses one training prompt and its confirmed correction as the reward
label. `core.score_review` scores decision accuracy, issue precision/recall and
missed critical issues. Its normalized reward is used for learning; malformed
or truncated output receives zero. Held-out examples and labels are never
inputs to this provider's RL loop. The first one or two training examples are
selected deterministically and their indexes recorded.

Zero reward variance produces `rl_skipped` and no optimizer call. Successful
updates emit `rl_step` only after the next policy is confirmed. The result
separates attempted rounds, actual RL updates, rollout rewards, policy IDs and
SFT steps. It retains loss, optimizer, normalization, group-size, sampling
limit and scorer-version settings. It keeps token hashes rather than raw
generated reasoning; hashes alone cannot reconstruct the original rollout.
This
correction-derived review reward is not a claim that UFO ran tests or patched
code. See River's [reward and zero-variance behavior](https://docs.river.ai/guides/rl-sync/).

Missing policy provenance, inexact rollout tokens, mismatched policy IDs or a
failed backward operation stop the run without another optimizer submission.
The loop has one owner and does not reuse trajectories across updates.

## Limits and failure behavior

| Setting | Default | Purpose |
| --- | --- | --- |
| `RIVER_ENDPOINT` | `api.river.ai` | gRPC hostname, without URL scheme/path |
| `RIVER_TIMEOUT_SECONDS` | 180 | Review operation timeout |
| `RIVER_TRAIN_TIMEOUT_SECONDS` | 600 | Per-operation training timeout |
| `RIVER_TRAIN_MAX_STEPS` | 4 | Optimizer updates; accepted range 1–20 |
| `RIVER_MAX_TOKENS` | 2048 | Maximum generated review tokens |
| `RIVER_MAX_EXAMPLE_TOKENS` | 8192 | Per-example token limit |
| `RIVER_MAX_BATCH_TOKENS` | 32768 | Sum of input tokens per full batch |
| `RIVER_LEARNING_RATE` | 0.0002 | Adam learning rate |
| `RIVER_LORA_RANK` | 16 | Adapter rank; accepted range 1–32 |
| `RIVER_RL_MAX_STEPS` | 1 | Optional RL rounds; accepted range 1–2 |
| `RIVER_RL_GROUP_SIZE` | 2 | Attempts per training prompt; range 2–4 |
| `RIVER_RL_MAX_TOKENS` | 1024 | Generated tokens per attempt; maximum 2048 |
| `RIVER_RL_LEARNING_RATE` | 0.00001 | Optional RL optimizer learning rate |

A run accepts up to 32 examples. Oversized data is rejected before a remote
training session starts. At default bounds, four steps process at most 131,072
input tokens. This is a workload bound, **not a dollar spending cap**; it excludes
sampling, account-specific pricing and service overhead.

Optional RL adds at most two rounds of four generations (2048 tokens each at
the maximum settings). Each update remains subject to the full-batch token
limit; its worst-case size is checked before creating the remote model.

Clients and sessions are closed on success and failure. Retries are disabled.
If a timeout leaves remote completion uncertain, inspect the run in the River
Console before retrying. Cancellation stops subsequent training operations;
an operation already running may finish before its session is released.
Tokenizer files are cached inside this repository's `.cache/huggingface`.
Reflex first loads a usable cached snapshot without network access. On a cold
or incomplete cache, it downloads an allowlist of tokenizer/configuration
files (never model weights), then loads that snapshot with
`local_files_only=True` and remote code disabled. The snapshot revision is
retained in inference provenance.

Hub request timeouts are enforced at the request boundary: at most 10 seconds
for connection/pool acquisition and 30 seconds for each read/write wait,
including metadata methods that explicitly pass `timeout=None`. Stricter
timeouts and the Hub's offline-mode guard are preserved. These are per-wait
bounds; Hub retries and multiple files can extend the total setup time. A
tokenizer setup failure occurs before any River request is submitted.

## Serving the learned reviewer

Replay supplies the saved URI to `session.sample(checkpoint=...)`. It does not
reserve a dedicated deployment. This is sufficient for the UFO specialist
tool to use learned weights.

River's optional [dedicated OpenAI-compatible deployments](https://docs.river.ai/guides/deployments/)
require enabled team access and reserve billable capacity until stopped.
Reflex does not provision them. Saved checkpoints also have retention limits;
see [saving and restoring weights](https://docs.river.ai/guides/checkpoints/).

## Verification

Check the actual public tokenizer and all 38 fixture prompts without a River
key or model call:

```sh
.venv/bin/python scripts/check_tokenizer.py
```

The first successful run requires access to Hugging Face; subsequent runs use
the repository cache. The script reports the tokenizer revision, token counts,
and completion-target alignment. It never saves its sample completion as
training feedback. See [verification.md](verification.md) for the observed
network result, including any unverified step.

```sh
.venv/bin/python -m pytest tests/test_river.py -q
```

These tests exercise masking, strict review parsing, unchanged evaluation
inputs, event ordering, failure cleanup, bounded batches and credential errors.
They also verify RL reward isolation, alignment against the installed SDK's
`Sample` type, zero-variance skips and policy-mismatch rejection. They replace
only the SDK/tokenizer I/O boundaries and incur no River usage. Tokenizer checks
exercise cold, warm and incomplete cache behavior, snapshot revision retention,
and explicit disabled/oversized/stricter HTTP timeouts at the transport edge.
A live review/training/replay still requires credentials and authorized spend;
passing these tests does not claim a successful live training run.
