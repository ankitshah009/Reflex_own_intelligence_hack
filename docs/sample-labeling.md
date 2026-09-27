# Synthetic curriculum and human labeling

The built-in picker contains **26 fictional, unreviewed PRs**. They are proposed curriculum material. They do not represent live UFO trajectories, executed tests, historical human corrections, or model performance. Every sample starts with an empty trajectory, no agent review, and no human feedback.

Use the proposals below as a review guide. Inspect each patch and its context, edit the suggested decision or reason when needed, and explicitly confirm the feedback in Reflex. That confirmation creates the learning signal. Loading a sample or running a model on it does not approve it for training.

The separate backend evaluation collection contains **12 fictional held-out PRs: 6 APPROVE and 6 REJECT**. Its labels are not exposed in the sample picker or model prompt. These labels are authored expectations, not independently validated truth. Have another reviewer validate the labels before presenting the results as engineering evidence.

Fixture timestamps identify the fixed `reflex-synthetic-prs-v1` dataset revision. They are stable across application restarts so the evaluation-set hash is reproducible; they do not claim that agent work occurred at that time.

## Proposed training labels

| Sample | Decision | Issue tags | Suggested correction or confirmation |
| --- | --- | --- | --- |
| 01 | REJECT | `broad_exception`, `missing_regression_test` | A failed charge must never be reported as paid. Catch the documented payment exception, preserve the failure, and add a regression test. |
| 02 | APPROVE | none | The narrow card-decline handler preserves failure status, and the regression test checks that no paid receipt appears. |
| 03 | REJECT | `sql_injection` | Email is untrusted input. Bind it as a query parameter instead of interpolating it into SQL. |
| 04 | APPROVE | none | The query binds email as data, and the test covers a quote-containing payload. |
| 05 | REJECT | `missing_timeout` | Bound connection and response time when requesting supplier inventory. |
| 06 | APPROVE | none | The worker uses explicit connect/read timeouts and propagates unsuccessful HTTP responses. |
| 07 | REJECT | `missing_authorization` | Authentication does not authorize access to another customer's invoice. Filter by the current user's ownership. |
| 08 | APPROVE | none | Invoice selection includes ownership and returns no record for inaccessible invoices. |
| 09 | REJECT | `path_traversal` | The untrusted filename can escape the report directory. Resolve it and check that it remains under the trusted root. |
| 10 | APPROVE | none | Resolved path containment is checked in a directory that users cannot mutate. |
| 11 | REJECT | `mutable_default` | The labels list is shared across calls. Create a fresh list and copy caller-supplied labels. |
| 12 | APPROVE | none | Each ticket receives a fresh label list without mutating the caller's list. |
| 13 | REJECT | `secret_exposure` | Credentials belong in managed configuration, not committed source. The fictional literal is redacted before storage. |
| 14 | APPROVE | none | The client receives its credential from validated environment configuration and sets a timeout. |
| 15 | REJECT | `unsafe_deserialization` | Pickle can execute code while loading attacker-controlled data. Use a safe format and validate the schema. |
| 16 | APPROVE | none | Size-limited JSON is validated against an existing strict schema. |
| 17 | REJECT | `event_loop_blocking` | A synchronous HTTP request blocks the ASGI event loop even with a timeout. Await an async client or use the configured worker boundary. |
| 18 | APPROVE | none | The route awaits a managed async client with a timeout. |
| 19 | REJECT | `race_condition` | Separate reads and writes let concurrent reservations oversell. Use an atomic conditional update inside a transaction. |
| 20 | APPROVE | none | Stock decrement and reservation creation are atomic, and unavailable stock is rejected. |
| 21 | REJECT | `missing_input_validation` | Validate pagination as an integer in a bounded positive range at the request boundary. |
| 22 | APPROVE | none | The route validates pagination and scopes data access to the authenticated user. |
| 23 | REJECT | `idempotency_violation` | Retried delivery can credit an account repeatedly. Deduplicate by event ID atomically with the credit mutation. |
| 24 | APPROVE | none | The unique event insertion and credit mutation share a transaction, so retried events do not credit twice. |
| 25 | REJECT | `error_contract_violation` | Public API error responses must use a stable `error_code` and a generic `message`. Do not return provider exception text, even when it contains no secrets. |
| 26 | APPROVE | none | The public response uses a stable error code and generic message while catching the documented provider exception. |

## The repository convention experiment

Samples 25 and 26 introduce a deliberately specific team convention: every public API error response uses a stable `error_code` plus generic `message`, and never returns a provider's exception string. This convention is not a universal security rule. The exception text in these examples explicitly contains no sensitive data.

The convention is intentionally absent from the held-out prompt and repository context. The human must confirm it in training feedback. The base condition has no prior feedback. The memory condition receives the confirmed training feedback. The learned condition receives the same memory text and the same held-out prompt, using the trained checkpoint. This isolates the additional value of weight updates over the memory condition, rather than hiding a policy change inside the prompt.

Do not train on or manually correct held-out examples. Freeze the dataset, feedback, memory, generation settings, and labels before evaluating all conditions. Report every case, errors included, with support counts and observed metrics. An equal or worse result after training is a valid result; neither improvement nor a dramatic before/after decision is guaranteed.

## What the local checks establish

- Samples do not enter SFT or the memory baseline without explicitly approved feedback.
- Held-out examples never enter either training path, even when they carry feedback.
- Normalized duplicate patches cannot cross the split, including changes only to filenames, hunk offsets, or whitespace.
- Model names, checkpoints, prior answers, feedback, and gold labels do not silently change the review prompt.
- SQLite writes and split checks are atomic across concurrent connections.

The fingerprint guard detects normalized patch duplicates, not semantic duplication. The fixtures intentionally cover related bug families using different patches; they are a small controlled curriculum, not a broad generalization benchmark. For a stronger evaluation, group real PR variants by originating PR and bug family, split before labeling, and commission independent label review.

Common credential patterns are redacted before storage and export. This is a practical filter, not comprehensive secret or personal-data detection. Review real repository material before sending it to a model provider.
