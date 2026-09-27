# Reflex: two-minute demo pitch

## Timed script

**0:00–0:15 — Open the broken checkout.**

“A customer pays once. A webhook arrives twice. Your software creates two orders and removes inventory twice. Reflex gives engineering teams a workspace to reproduce that failure, repair the handler, and turn approved repair experience into a specialist they can train.”

**0:15–0:35 — Replay the same event. Show the two orders and failing checks.**

“This is a fictional incident with real execution. The handler changes the application state inside an operating-system sandbox. Here, the broken checkout passes two of four behavioral checks. A retry produces the duplicate you can see.”

**0:35–0:55 — Show the saved live River repair, diff, and successful replay.**

“River generated this repair. It checks the operation identity before changing inventory. That checkout repair completed in 15.4 seconds and passed all four checks. Replaying the event now leaves one order. Across six live River repairs of our training samples, five passed every check.”

**0:55–1:15 — Open the stock-replay failure and proposed correction.**

“The sixth repair failed. It returned a cached response after changing stock again. We kept that failure visible. An assistant-proposed correction now passes four of four checks. It is still awaiting human approval. Confirmed corrections become the learning data; proposed corrections remain drafts.”

**1:15–1:40 — Show the learning and evaluation workflow; state its current status.**

“UFO is the experience layer. River is the training and model layer. Reflex connects executed work, verified outcomes, and approved corrections. We have verified the UFO SDK integration, but have not shown an authenticated UFO conversation. Checkpoint training and the held-out comparison are still pending. We have not measured an improvement from learned weights yet.”

**1:40–2:00 — Close on the buyer and ownership.**

“Our initial buyer is an engineering team maintaining commerce or webhook systems where retries cause expensive bugs. Our pricing hypothesis is a team subscription with separately metered training compute. The ownership goal is an exportable specialist adapter, its approved examples, and its evaluation history. That adapter still needs compatible base-model weights and a runtime.”

## Business answer

**Who pays?** Engineering managers and platform leads responsible for retry-heavy checkout, inventory, billing, refund, and webhook services. The first purchase hypothesis is a repair-and-learning workspace for a team that repeatedly investigates the same failure family.

**Why keep using it?** The proposed recurring value is a reproducible incident workspace, executable repair evidence, reviewable corrections, and specialist training based on the team's accepted fixes. Continued use and willingness to pay have not been validated.

**How does it make money?** A team subscription plus transparent compute charges is a hypothesis. We have no validated pricing, revenue, customer acquisition cost, or customer savings to report. The next commercial check is a paid pilot using a team's own incidents and acceptance criteria.

**What is owned?** Confirmed training examples and their recorded lineage belong in an exportable dataset. An exported trained adapter/checkpoint provides a model artifact whose use depends on compatible base weights, their license, and an inference runtime. River supplies managed training and inference compute in this implementation. A completed, exported trained artifact has not yet been demonstrated in the current run.

## Evidence to keep on screen

| Evidence | What it supports |
| --- | --- |
| Six live River repairs; five passed all checks | Repair performance on these six fictional training samples only |
| First checkout: 2/4 → 4/4 checks; 15.4 seconds | A measured repair and replay on that sample |
| Stock-replay River output: 2/4; assistant correction: 4/4 | A visible model failure and a verified proposed correction; human approval remains pending |
| 172 tests and 51 subtests passing | Engineering validation; these counts are not a model-quality score |
| UFO SDK integration verified | Integration compatibility; an authenticated UFO conversation has not been shown |
| Checkpoint and held-out evaluation pending | No measured benefit from learned weights yet |

## If learning does not improve the result

Say: “The learned checkpoint scored **[observed result]** across **[N]** held-out cases, compared with **[base result]** for the base model and **[memory result]** for memory alone. We did not demonstrate an improvement beyond memory in this run. The useful result is an auditable experiment: fixed inputs, recorded failures, and a reproducible checkpoint comparison.”

If the run is incomplete, say: “Training or evaluation is still pending. The repair results shown here were measured before training; we are not presenting them as learning gains.”

Show every evaluated case and infrastructure error. Keep the full result visible even when the most memorable individual repair looks better. Use “the prompt stayed the same; the model changed” only after a real checkpoint exists and matching prompt evidence has been recorded.
