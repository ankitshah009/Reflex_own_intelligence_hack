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
export RIVER_TRAIN_MAX_STEPS="16"
export RIVER_TRAIN_BATCH_SIZE="2"
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

`RiverProvider.repair(prompt, checkpoint=None)` uses the same sampling and
provenance path, with a separate strict parser for `summary` and complete
replacement `code`. Both fields must be nonempty text, code is limited to
32,000 characters, and hidden thinking is removed before persistence.

`RiverProvider.train(examples, name=..., on_event=...)` accepts reviewed
prompt/completion pairs for one task type: review or repair. Completion tokens
alone contribute to loss. Examples are split into ordered batches, two per
batch by default. Each step takes the next batch, submits forward/backward,
waits for its result, and then submits and waits for the optimizer update.
After the final batch, traversal restarts at the first batch without shuffling.
Before any remote work, the provider requires enough steps for every example
to participate at least once: `steps >= ceil(examples / batch_size)`.

The full frozen dataset retains its input-token hashes. Each confirmed step
records zero-based `example_indices`, `batch_tokens`, `supervised_tokens`, and
a one-based `epoch`. Final metrics include exact processed `training_tokens`,
`supervised_tokens`, `unique_examples_covered`, `examples_processed`, and
`sft_history`. `passes` is processed examples divided by dataset size;
`completed_passes` counts full ordered traversals. `dataset_tokens` counts the
corpus once, while `batch_tokens` is the largest submitted SFT batch. Initial
and final losses can describe different batches; held-out evaluation, rather
than a loss comparison alone, establishes improvement.

The final inference checkpoint is saved under an immutable name, and its
actual River URI is returned. Events report confirmed work and observed loss.

The documented primitives are [session sampling, LoRA creation, optimizer
updates and saved checkpoints](https://docs.river.ai/python-api/), following
the [SFT training flow](https://docs.river.ai/guides/sft/).

The caller must retain its own experience IDs and prompt hashes with the
returned checkpoint. Training loss measures fitting the examples; held-out
evaluation establishes whether review judgment improved.

## Optional reinforcement learning

Use `method="sft+rl"` to continue updating the **same live model** after SFT.
This mode accepts review examples only; review-tag rewards do not score code
repairs. Repair training requires `method="sft"`.
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
| `RIVER_TRAIN_MAX_STEPS` | 16 | Optimizer updates; accepted range 1–64; must cover every example |
| `RIVER_TRAIN_BATCH_SIZE` | 2 | Examples per ordered SFT batch; accepted range 1–8 |
| `RIVER_MAX_TOKENS` | 2048 | Maximum generated review tokens |
| `RIVER_MAX_EXAMPLE_TOKENS` | 8192 | Per-example token limit |
| `RIVER_MAX_BATCH_TOKENS` | 32768 | Sum of input tokens per submitted batch |
| `RIVER_LEARNING_RATE` | 0.0002 | Adam learning rate |
| `RIVER_LORA_RANK` | 16 | Adapter rank; accepted range 1–32 |
| `RIVER_RL_MAX_STEPS` | 1 | Optional RL rounds; accepted range 1–2 |
| `RIVER_RL_GROUP_SIZE` | 2 | Attempts per training prompt; range 2–4 |
| `RIVER_RL_MAX_TOKENS` | 1024 | Generated tokens per attempt; maximum 2048 |
| `RIVER_RL_LEARNING_RATE` | 0.00001 | Optional RL optimizer learning rate |

A run accepts up to 32 examples. Oversized data is rejected before a remote
training session starts. The batch token cap applies to each submitted chunk;
the full corpus may exceed it. With the default batch size, per-example limit,
and 16 steps, SFT processes at most 262,144 input tokens. This is a conservative
workload bound, **not a dollar spending cap**; it excludes sampling,
account-specific pricing and service overhead. For a one-step diagnostic,
explicitly set one step and supply at most two examples. For 32 examples at
batch size two, at least 16 steps are required.

Optional RL adds at most two rounds of four generations (2048 tokens each at
the maximum settings). Each update remains subject to the submitted-batch token
limit; its worst-case size is checked before creating the remote model.

Clients and sessions are closed on success and failure. Retries are disabled.
SFT uses the SDK's separate submit/result operations so `training_operation`
records each accepted backward or optimizer request ID before waiting. A
transport failure emits `training_diagnostic` with its stage, confirmed-step
count, session/model/run/request IDs, and recognized gRPC status. Raw provider
messages and details are excluded. An accepted request is not a confirmed
weight update; inspect the recorded request and run before submitting a retry.
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
They check deterministic minibatch coverage, insufficient-step rejection,
exact token accounting, and accepted-request diagnostics without vendor details.
They also verify RL reward isolation, alignment against the installed SDK's
`Sample` type, zero-variance skips and policy-mismatch rejection. They replace
only the SDK/tokenizer I/O boundaries and incur no River usage. Tokenizer checks
exercise cold, warm and incomplete cache behavior, snapshot revision retention,
and explicit disabled/oversized/stricter HTTP timeouts at the transport edge.
A live review/training/replay still requires credentials and authorized spend;
passing these tests does not claim a successful live training run.
