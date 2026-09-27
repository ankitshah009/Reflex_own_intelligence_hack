# Verification evidence and limits

This document separates local correctness checks from a live sponsor demonstration. Passing local tests does not establish River account access, actual weight updates, a full authenticated UFO conversation, or improved judgment.

## Recorded local result

On 2026-09-27, the latest complete backend run completed with **172 passed and 51 subtests passed** in 25.58 seconds. This includes 15 repair API integration tests and 16 repair engine tests, using actual macOS isolation, alongside the original review/provider/UFO suites:

```sh
.venv/bin/pytest -q
.venv/bin/ruff check backend tests integrations/ufo scripts/check_tokenizer.py
```

Ruff passed. The production frontend also built successfully with TypeScript and Vite 8.3.1:

```sh
cd frontend
npm run build
```

There was one Starlette deprecation warning about its test client's `httpx` compatibility path. It did not fail the run. These results cover the local API and provider-contract scope described below; no River calls were submitted by this test run.

## Real tokenizer preflight

The actual tokenizer-only preparation was attempted using
`.venv/bin/python scripts/check_tokenizer.py`. Initial attempts exposed Hub
requests with no connection timeout, including metadata methods that override
a finite client default with `timeout=None`. After confirming that behavior
in the installed dependency and observing the stalled process, those probes
were stopped. Reflex now bounds timeouts at the request boundary and downloads
an explicit tokenizer-file snapshot before strictly local tokenizer loading.

The initial network proxy returned HTTP 403 for Hugging Face. On September 27,
the approved network retry downloaded all six public tokenizer/config files.
The real preflight then passed for all 38 review fixture prompts using
`Qwen2Tokenizer`, revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`.
Prompts contained 453–578 tokens; the 26 training prompts totaled 12,525 tokens.
The SFT alignment check passed with 497 tokens. This preflight submitted no
River inference or training requests. Subsequent loads use the project cache.

## First live repair result

At 2026-09-27 22:41 UTC, the production API completed a real River
`Qwen/Qwen3.5-9B` repair of the fictional checkout replay case. The original
handler passed 2/4 checks; River's generated handler passed 4/4 under the actual
macOS sandbox. The job completed in 15.4 seconds as observed by the API poller
(the stored repair duration was 13.554 seconds).

The reproduced duplicate request created two orders, reduced widget stock to
8, and left a 14,400-cent balance. Executing the generated repair produced one
order, stock of 10, and a 12,000-cent balance. These are synthetic case values,
not real customer transactions.

- Job: `c528ec42-0f65-47b6-937f-109d743671ef`
- Repair: `72a240d1-9ef5-42fb-9afe-afffd578fdfa`
- Generated code SHA-256: `b75ac63646c7169b726c634efc3c6ac0f34d0c0ee8a7f1056a8a5d2043dd921f`
- Exact model-input token SHA-256: `c06432de34ae50844a362d4074e3dec2c254d9dcaad258c7045701852cba9653`

This establishes live code generation and execution. It does not establish a
weight update or improvement from learning; no trained checkpoint or held-out
learning result is claimed by this repair.

All six supplied training incidents were subsequently attempted once using the
base model. Checkout, refund, tenant checkout, distinct stock deliveries, and
cancellation passed 4/4 checks; stock replay passed 2/4. Thus 5/6 generated
repairs passed their complete contracts. These are training-case outcomes,
not held-out results. None were silently marked as human-approved.

## Actual local runtime and browser checks

The real Uvicorn service booted on `127.0.0.1:8000`; Vite served the frontend at `127.0.0.1:5173`. Both remain pointed at the normal clean workspace after verification.

Using the browser and a separate `data/browser-qa.sqlite3` database, the check selected a fictional PR, selected two issue tags, entered an explicitly labeled QA correction, saved it through the UI, found it in the experience library, and fetched the exported JSONL. The export contained one REJECT target with `broad_exception` and `missing_regression_test`. After killing the QA process and starting a fresh process on the same database, the correction and eligible count persisted. That test record is excluded from the normal `data/reflex.sqlite3` workspace.

Learning and evaluation displayed missing-credential and empty-result states. Desktop width 1280 and mobile width 390 had no horizontal page overflow. The closed mobile sidebar was removed from the accessibility tree; issue tags used labeled native checkboxes. Screenshots: [desktop](screenshots/workspace-desktop.png), [mobile](screenshots/workspace-mobile.png). An earlier screenshot with `-qa` in its filename depicts isolated test data, not user work or measured model performance.

The actual pinned UFO distribution was installed under `.cache/ufo-env`. Running `.cache/ufo-env/bin/python integrations/ufo/verify_runtime.py` loaded the `reflex-demo` pack, discovered the real tool and four hooks, and exercised the real SDK tool handler and hook dispatcher. Only HTTP responses and the workspace store were fixtures; the verifier reported `cloud_calls: 0`. This proves source-level registration and dispatch, not an authenticated frontier-model conversation.

A subsequent startup check exposed a documentation error: a pack-only TOML file
omitted UFO's mandatory database and blob-store configuration. The installation recipe
now copies `integrations/ufo/ufo.example.toml`, which the real UFO configuration model
successfully validates. The verifier includes this configuration check and passed again.
Actual `ufoctl init` in the isolated `.cache/ufo-runtime` directory completed schema
migration and reached onboarding, then refused because the default `auto` model requires
`UFO_ANTHROPIC_API_KEY`. No model call was submitted and no authenticated server boot is
claimed. The diagnostic owner address is fictional and is not the user's account.

## API journey

`tests/test_api.py` exercises the real FastAPI application, request validation, SQLite writes, background jobs, event stream, feedback conversion, training snapshots, and evaluator. Every test creates its own database in pytest's temporary directory. The fake replaces only River cloud inference and training; returned checkpoint URIs deliberately use `river://test-only/...`. No test results or fabricated performance measurements are inserted into the application database.

Run from the repository root:

```sh
.venv/bin/pytest tests/test_api.py -q
```

The primary journey is:

1. Start with an empty ledger and select a clearly labeled fictional sample.
2. Submit a review, wait for the actual asynchronous job, and inspect persisted operation events.
3. Confirm the review through human feedback; prove that unconfirmed work cannot enter the dataset.
4. Export corrected prompt/completion pairs and submit an SFT or combined SFT/RL job using those same examples.
5. Persist confirmed checkpoint results, immutable dataset contents, dataset hash, experience IDs, and frozen feedback. A combined run saves a usable SFT checkpoint before starting RL.
6. Evaluate every held-out case in base, memory, and learned conditions.
7. Compare exact prompts and checkpoint routing; memory and learned receive identical prompts, while base receives no feedback memory.

The test double intentionally returns the same review in every condition. Its results are useful for checking arithmetic and routing, and provide **no evidence of model improvement**.

## Failure and integrity checks

| Area | Behavior exercised |
| --- | --- |
| Dataset approval | Unapproved corrections stay out of export; repeated patch content counts once; conflicting judgments cannot corrupt the saved dataset; fewer than two distinct approved examples cannot train. |
| Held-out isolation | Renaming a held-out patch or changing its repository does not make it training data; nested gold labels and hidden reasoning are excluded from prompts. |
| Frozen experiment | Later feedback cannot change an existing checkpoint's evaluation memory or exported training examples; a different base model blocks comparison. |
| Model input identity | A change in model-facing input hashes fails the comparison and preserves a failed artifact. |
| Invalid output | Malformed review output cannot become an approval; malformed evaluation output remains a failed attempt in the denominator. |
| Transport failure | Completed evaluation rows remain inspectable; an aborted run cannot claim complete matched prompts. |
| Missing credentials | Review, training, and replay fail explicitly; no job, checkpoint, or result is fabricated. |
| Training failure | Failure before a confirmed checkpoint leaves none. Failure during RL preserves a previously confirmed SFT checkpoint with its SFT method and original job identity; no successful RL result is fabricated. |
| Combined training | The selected SFT/RL method reaches the provider; a successful run persists distinct SFT and final checkpoints, with confirmed RL metrics and matching dataset identity. Both saved checkpoints can be selected for inference. |
| Restart | Feedback and checkpoints survive reopening SQLite; incomplete jobs are interrupted and never automatically replay paid operations. |
| Shutdown | An active review is canceled without saving a partial experience; partial evaluation evidence remains available with a terminal status. |
| Local request boundary | Foreign origins and hosts are rejected; request bodies over 1 MB are rejected before provider access. |
| UFO authentication | When configured, the ingest token is required; reviewer calls require UUID provenance and an idempotency key. |
| UFO retry behavior | Retrying a completed review returns its saved result even after restart without credentials; an unconfirmed failed request cannot automatically call River again; imports without an experience ID deduplicate by runtime turn. |
| UFO model adoption | A new auto-mode turn uses a saved checkpoint once available. Retrying an earlier turn still returns its original base-model result and cannot rerun it against new weights. |
| UFO merge identity | Imported trajectory data must match the original patch, all four runtime UUIDs, and SDK revision; it cannot overwrite human feedback or supply its own approval labels. |
| Event replay | A reconnect with `Last-Event-ID` receives only unseen operation events. |
| Import validation | A JSON array, null, or string is rejected as a client error instead of causing an unhandled server exception. |

## Provider contracts

The existing `tests/test_river.py` suite targets the installed provider adapter at its SDK and tokenizer I/O boundaries. It covers token/target alignment, completion-only loss masking, model sampling settings, confirmed optimizer and checkpoint operations, resource cleanup, and error sanitization. Optional RL checks cover exact rollout token/log-probability alignment, current policy identity, reward variation, and stopping before an optimizer update when the backward operation fails. Equal rewards must report a skipped update. The suite does not submit live River requests.

The existing `tests/test_ufo.py` suite targets the public envelope and HTTP transport boundaries. It covers runtime UUID validation, observable event limits, rejection of agent-supplied training labels, HTTPS requirements for remote transport, bearer/idempotency headers, redirect suppression, and sanitized remote errors. This fast suite uses a double at the UFO SDK/store boundary.

Separate [UFO loader evidence](ufo.md#failure-behavior-and-validation) records verification against the actual pinned distribution installed in `.cache/ufo-env`: extension and pack discovery, real tool schema and `ToolContext` dispatch, and actual lifecycle `HookChain` events. Its command is:

```sh
.cache/ufo-env/bin/python integrations/ufo/verify_runtime.py
```

That check uses fixtures only for HTTP responses and workspace storage. It establishes registration and dispatch without making a model call; it does not establish a full server boot or authenticated conversation.

Run those contract checks with the API journey:

```sh
.venv/bin/pytest tests/test_api.py tests/test_river.py tests/test_ufo.py -q
```

Run the complete backend suite:

```sh
.venv/bin/pytest -q
```

## What still needs live evidence

The [research record](research.md) identifies the official sources and pinned integration contracts. The following observations are required before claiming a complete sponsor loop:

- Boot the actual UFO runtime at the documented revision and confirm the Reflex tool and hooks are active in the selected pack.
- Run a real UFO review and verify that its actual workspace, turn, thread, agent, and observable trajectory reach Reflex.
- Use a configured River account to complete a sample with the selected base model and the production tokenizer/rendering path.
- Approve sufficient distinct experiences, run a real SFT backward/optimizer sequence, and confirm the saved checkpoint URI in River and Reflex. If claiming RL, additionally confirm varied scored rollouts, a successful RL optimizer update, and the final checkpoint; a skipped update is not evidence of reward learning.
- Run all held-out cases in all three conditions. Publish observed denominators, failed outputs, and results even if learned weights do not outperform memory.
- Invoke that saved specialist through UFO on a genuinely new PR; verify restart recovery and retry behavior against real service behavior.

Local tests do not prove network availability, tokenization downloads, account permissions, provider queue latency, provider billing, convergence, hosting eligibility, or a performance improvement. The held-out fixtures are small fictional engineering cases, so even a successful live evaluation supports only a limited measured claim.

## Scope of API verification

FastAPI's test client executes application lifespan and asynchronous tasks in process. These checks exercise production application code and persistent storage, but they do not substitute for boot logs from a real Uvicorn process, frontend/browser checks, accessibility checks, or sponsor integration evidence. Those checks should be reported separately with the exact commands and observations that actually ran.
