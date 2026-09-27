# Reflex — two-minute demo

**Opening line:** “A customer clicks once. Your webhook arrives twice. Watch what breaks.”

**Closing line:** “Your next incident should benefit from the last one. That's Reflex.”

The story is a failing customer flow, an executed repair, a trained specialist,
and the real UFO SDK using that specialist. Keep the app and saved receipts on
screen. The final narrated transcript is in [demo-assets/narration.txt](demo-assets/narration.txt).

## Prepare the shot

- Open `http://127.0.0.1:5173` in a desktop window with the checkout case selected.
- Start with **Original** and the initial state. Keep the saved successful River attempt available under **Saved attempts**.
- Have **Learning & replay** ready with the 24-example dataset, saved `reflex-repair-v4-48steps-20260927` checkpoint, and completed training log. Keep the original v3 comparison available.
- Prepare the [live UFO tool receipt](evidence/ufo-live-v4.json): stock training case, 2/4 original checks, 4/4 repaired checks, saved observable trace, about 5.7 seconds.
- Use a completed recording of the real provider run if a fresh repair takes too long. Label that segment **Recorded live River run**. Keep failures and measured results intact.
- Record the application window and microphone. Close unrelated tabs; keep the pointer still while explaining an outcome.

## Shot list and spoken script

| Time | On screen | Say |
| --- | --- | --- |
| 0:00–0:12 | Checkout preview. Click **Place order**, then click it again to replay the same request. | “A customer clicks once. Your webhook arrives twice. Watch what breaks. Two orders. Inventory deducted twice.” |
| 0:12–0:25 | Click **Reproduce issue**. Show the two orders and **2/4** checks. | “This is a sample incident, but the code is really running. Reflex gives engineering teams a place to reproduce the failure and prove a repair.” |
| 0:25–0:43 | Open the recorded River repair, **Patch**, and **4/4** checks. | “River writes a patch. It recognizes the replay before changing inventory. Reflex executes it against the same contract. One order. Four checks pass.” |
| 0:43–0:58 | Open **Learning & replay**. Show provenance and the v4 checkpoint. | “Five accepted repairs and 19 machine-verified practice repairs became our dataset. River trained this specialist with 48 weight updates on those 24 examples.” |
| 0:58–1:22 | Show the live UFO receipt, checkpoint identity, stock repair, and saved trace. | “Now the model goes back to work. The actual UFO SDK tool called our trained checkpoint. This stock training case went from two of four to four of four checks in 5.7 seconds. Its observable work is saved back into Reflex.” |
| 1:22–1:40 | Show the preserved v3 comparison and the v4 execution-error note. | “The earlier held-out comparison was four of four in every condition. The later replay had a base execution permission error. We don't claim an accuracy gain. We can show the complete learning and reuse path.” |
| 1:40–1:55 | End on the workbench and repaired customer flow. | “Our first users are teams maintaining checkout, inventory, and webhook services. Verified fixes become a specialist they can train and reuse. Your next incident should benefit from the last one. That's Reflex.” |

**Timing:** This leaves five seconds inside a two-minute slot. Use the recorded
live runs with clear labels rather than waiting through training on camera.

## The completed result

| Condition | Passed repair cases |
| --- | --- |
| Base | 4/4 |
| Memory | 4/4 |
| Learned v3 | 4/4 |

Memory and learned prompts matched. The real checkpoint and completed evaluation demonstrate the mechanism; all three conditions hit the four-case benchmark's ceiling. **No measured accuracy gain.** Show the per-case results and preserve failed earlier attempts. A later experiment must not replace this original result in the record.

The later v4 replay recorded base 3/4, memory 4/4, learned 4/4, but the missing
base execution was an OS permission error. A local recheck of that exact code
passed. Preserve the original error; do not present the repeat as a learning
advantage. The live UFO repair used a training case and demonstrates specialist
reuse, without proving generalization or a full authenticated UFO conversation.

## Evidence notes for the presenter

Current verified evidence supplied by the running project:

| Item | Accurate description |
| --- | --- |
| Checkout repair | Broken handler 2/4 checks; real River patch 4/4; observed 15.4 seconds |
| Original sample repairs | Six live River repairs, five passing all four checks |
| Curriculum run | 24 generated tasks; 23 River requests; 19 returned repairs passed all four checks |
| Eligible data | 24 examples: five operator-accepted plus 19 machine-verified generated repairs |
| Generated-data breadth | Variants from six templates; not 24 independent incident families |
| Latest saved specialist | `reflex-repair-v4-48steps-20260927`; 48 confirmed weight updates; 24 examples; 122,752 training tokens processed |
| Preserved earlier specialist | `reflex-repair-v3-20260927`; 16 updates; 24 examples; 41,153 training tokens processed |
| Training method | Supervised fine-tuning; zero RL steps |
| Evaluation | Completed: base 4/4, memory 4/4, learned 4/4; matched prompts; no measured accuracy gain |
| UFO | Actual programmatic SDK tool used v4; stock training case 2/4 → 4/4 in about 5.7 seconds; observable trace saved; full authenticated conversation not demonstrated |
| Repository workflow | Local source/test snapshots and isolated pytest execution implemented; a real source/test pair returned 7 passed and 1 skipped; repository test suite: 30 passed |
| Complete backend validation | 240 tests and 88 subtests passed in 75.79 seconds; global Ruff passed |

The generated data's correct reference implementations and private checks are kept out of model prompts. Machine-verified labels describe executed checks, not human review. A passing synthetic repair is evidence for that case, not a production guarantee.

The full checkpoint reference, training job, and immutable dataset hash are recorded in [submission.md](submission.md#confirmed-training-receipt). Loss values from different minibatches are not a measured quality improvement.

## Short answers for judges

**Who pays?** “Engineering teams that own retry-heavy commerce and webhook integrations. We would start with a paid pilot on their own incidents. Team subscription plus training compute is the pricing hypothesis.”

**Why learning rather than memory alone?** “We measure both. Memory and learned receive the same input tokens on excluded cases, so we can see whether the weight update adds anything in this experiment.”

**What do you own?** “The accepted examples, their lineage, and the trained adapter once exported. River handles compute here. The adapter still needs compatible base weights and an inference runtime.”

**What is UFO doing today?** “The actual installed SDK tool called our v4 specialist, received a stock repair that passed all four checks, and imported its observable trace. That is a programmatic tool invocation. A full authenticated UFO conversation has not been demonstrated.”

**How does this grow beyond a sample storefront?** “The Repository tab works with local Python source and regression tests in an isolated snapshot. We executed a real source/test pair: seven passed, one skipped. The learning experiment shown here still uses the bounded event-handler curriculum.”

## Submission video

Title: **Reflex — your next incident learns from the last fix**

Description: **Verified engineering repairs become a River specialist: 48 weight updates on 24 examples, then real reuse through the UFO SDK. The stock training-case repair passes 4/4 checks in about 5.7 seconds. Held-out v3 results remain 4/4 in every condition; no accuracy gain is claimed.**

Video: https://ankitshah009.github.io/Reflex_own_intelligence_hack/

Source: https://github.com/ankitshah009/Reflex_own_intelligence_hack
