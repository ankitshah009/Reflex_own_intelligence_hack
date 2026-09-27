# Reflex: two-minute demo pitch

The current recording shot list is in [demo-script.md](demo-script.md).
Confirmed result: **24 training examples, 16 weight updates, one saved v3
checkpoint; held-out base 4/4, memory 4/4, learned 4/4. No accuracy gain measured.**

## Timed script

**0:00–0:15 — Open the broken checkout.**

“A customer pays once. A webhook arrives twice. Your software creates two orders and removes inventory twice. Reflex gives engineering teams a workspace to reproduce that failure, repair the handler, and turn approved repair experience into a specialist they can train.”

**0:15–0:35 — Replay the same event. Show the two orders and failing checks.**

“This is a fictional incident with real execution. The handler changes the application state inside an operating-system sandbox. Here, the broken checkout passes two of four behavioral checks. A retry produces the duplicate you can see.”

**0:35–0:55 — Show the saved live River repair, diff, and successful replay.**

“River generated this repair. It checks the operation identity before changing inventory. That checkout repair completed in 15.4 seconds and passed all four checks. Replaying the event now leaves one order. Across six live River repairs of our training samples, five passed every check.”

**0:55–1:15 — Open the verified experience dataset.**

“The initial stock repair failed. We kept that failure visible. We also asked River to repair generated practice cases and kept only verified successes. Five operator-accepted repairs plus 19 machine-verified repairs gave us 24 training examples, with their provenance preserved.”

**1:15–1:40 — Show the learning and evaluation workflow; state its current status.**

“River saved our specialist after 16 weight updates. We then tested four excluded cases: base, memory, and learned each passed four of four, with matching memory and learned inputs. The benchmark hit its ceiling; we did not measure an accuracy gain. The training and evaluation loop is real.”

**1:40–2:00 — Close on the buyer and ownership.**

“Our initial buyer is an engineering team maintaining commerce or webhook systems where retries cause expensive bugs. Our pricing hypothesis is a team subscription with separately metered training compute. The ownership goal is an exportable specialist adapter, its approved examples, and its evaluation history. That adapter still needs compatible base-model weights and a runtime.”

## Business answer

**Who pays?** Engineering managers and platform leads responsible for retry-heavy checkout, inventory, billing, refund, and webhook services. The first purchase hypothesis is a repair-and-learning workspace for a team that repeatedly investigates the same failure family.

**Why keep using it?** The proposed recurring value is a reproducible incident workspace, executable repair evidence, reviewable corrections, and specialist training based on the team's accepted fixes. Continued use and willingness to pay have not been validated.

**How does it make money?** A team subscription plus transparent compute charges is a hypothesis. We have no validated pricing, revenue, customer acquisition cost, or customer savings to report. The next commercial check is a paid pilot using a team's own incidents and acceptance criteria.

**What is owned?** Confirmed training examples and their recorded lineage belong in an exportable dataset. River has saved the trained adapter; its export is available through River Console. A downloaded local adapter has not yet been demonstrated. Its use requires compatible base weights, their license, and an inference runtime. River supplies managed training and inference compute in this implementation.

## Evidence to keep on screen

| Evidence | What it supports |
| --- | --- |
| Six live River repairs; five passed all checks | Repair performance on these six fictional training samples only |
| First checkout: 2/4 → 4/4 checks; 15.4 seconds | A measured repair and replay on that sample |
| Stock-replay River output: 2/4; assistant correction: 4/4 | A visible model failure and a verified proposed correction; human approval remains pending |
| 234 tests and 88 subtests passing; global Ruff clean | Engineering validation; these counts are not a model-quality score |
| Repository source/test pair: 7 passed, 1 skipped; repository suite: 30 passed | Actual local repository execution, separate from the event-handler learning experiment |
| UFO SDK integration verified | Integration compatibility; an authenticated UFO conversation has not been shown |
| Saved v3 checkpoint: 16 updates on 24 examples | Actual supervised model training; zero RL steps |
| Base 4/4, memory 4/4, learned 4/4; matched prompts | Completed small held-out experiment; ceiling reached, no measured accuracy gain |

## Explain the tied result

Say: “Base, memory, and learned all passed four of four. We did not demonstrate an improvement beyond memory. This benchmark was too easy to separate them. We can show the exact trained artifact, its dataset, and every evaluated case; harder excluded incidents are the next experiment.”

Keep the completed v3 result visible if additional training runs. Earlier training failures remain recorded, and a later unfinished run is not a completed checkpoint.

Show every evaluated case and infrastructure error. Keep the full result visible even when the most memorable individual repair looks better. Use “the prompt stayed the same; the model changed” only after a real checkpoint exists and matching prompt evidence has been recorded.
