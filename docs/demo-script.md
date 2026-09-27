# Reflex — 110-second demo

**Opening line:** “A customer clicks once. Your webhook arrives twice. Watch what breaks.”

**Closing line:** “Your next incident should benefit from the last one. That's Reflex.”

The story is a failing customer flow, an executed repair, and evidence carried forward into learning. Keep the app on screen. Use the completed run's actual results in the final segment.

## Prepare the shot

- Open `http://127.0.0.1:5173` in a desktop window with the checkout case selected.
- Start with **Original** and the initial state. Keep the saved successful River attempt available under **Saved attempts**.
- Have **Learning & replay** ready with the 24-example dataset, saved `reflex-repair-v3-20260927` checkpoint, and current evaluation state. Use the completed training event log on camera.
- Use a completed recording of the real provider run if a fresh repair takes too long. Label that segment **Recorded live River run**. Keep failures and measured results intact.
- Record the application window and microphone. Close unrelated tabs; keep the pointer still while explaining an outcome.

## Shot list and spoken script

| Time | On screen | Say |
| --- | --- | --- |
| 0:00–0:12 | Checkout preview. Click **Place order**, then click it again to replay the same request. | “A customer clicks once. Your webhook arrives twice. Watch what breaks. Two orders. Inventory deducted twice.” |
| 0:12–0:25 | Click **Reproduce issue**. Show the two orders and **2/4** checks. | “This is a sample incident, but the code is really running. Reflex gives engineering teams a place to reproduce the failure and prove a repair.” |
| 0:25–0:45 | Click **Ask agent to repair**, or open the clearly labeled recorded River run. Show progress, then **Patch**. | “River writes a patch. Here it recognizes a replay before changing inventory. Reflex executes it against the same behavior contract.” |
| 0:45–0:58 | Show **4/4**, one order, and the updated inventory. | “One order. Four checks pass. This checkout repair took 15 seconds in our recorded run. The model produced code; execution determined whether it worked.” |
| 0:58–1:12 | Open **Learning & replay**. Show the accepted examples and provenance labels. | “The repair becomes experience we can train on. We have 24 eligible examples: five accepted repairs and 19 generated repairs that passed executable checks. Failures stay out of training.” |
| 1:12–1:34 | Show `reflex-repair-v3-20260927`, its 16 confirmed updates, and the completed comparison. | “River saved our specialist after 16 weight updates on 24 examples. On four excluded cases, base, memory, and learned all passed four of four. The inputs matched. This small benchmark hit its ceiling; we haven't measured an accuracy gain.” |
| 1:34–1:50 | End on the workbench and repaired customer flow. | “Our first users are teams maintaining checkout, inventory, and webhook services. UFO brings the specialist into the agent workflow; River supplies training. Your next incident should benefit from the last one. That's Reflex.” |

**Timing:** This leaves ten seconds inside a two-minute slot for a provider delay or an extra result explanation. If a fresh model call runs long, cut to the saved run with the recording label. Do not wait through training on camera.

## The completed result

| Condition | Passed repair cases |
| --- | --- |
| Base | 4/4 |
| Memory | 4/4 |
| Learned v3 | 4/4 |

Memory and learned prompts matched. The real checkpoint and completed evaluation demonstrate the mechanism; all three conditions hit the four-case benchmark's ceiling. **No measured accuracy gain.** Show the per-case results and preserve failed earlier attempts. A later experiment must not replace this original result in the record.

## Evidence notes for the presenter

Current verified evidence supplied by the running project:

| Item | Accurate description |
| --- | --- |
| Checkout repair | Broken handler 2/4 checks; real River patch 4/4; observed 15.4 seconds |
| Original sample repairs | Six live River repairs, five passing all four checks |
| Curriculum run | 24 generated tasks; 23 River requests; 19 returned repairs passed all four checks |
| Eligible data | 24 examples: five operator-accepted plus 19 machine-verified generated repairs |
| Generated-data breadth | Variants from six templates; not 24 independent incident families |
| Saved specialist | `reflex-repair-v3-20260927`; 16 confirmed weight updates; 24 examples; 41,153 training tokens processed |
| Training method | Supervised fine-tuning; zero RL steps |
| Evaluation | Completed: base 4/4, memory 4/4, learned 4/4; matched prompts; no measured accuracy gain |
| UFO | Installed SDK and extension verified; authenticated live conversation not yet demonstrated |
| Repository workflow | Local source/test snapshots and isolated pytest execution implemented; a real source/test pair returned 7 passed and 1 skipped; repository test suite: 30 passed |
| Complete backend validation | 234 tests and 88 subtests passed in 89.94 seconds; global Ruff passed |

The generated data's correct reference implementations and private checks are kept out of model prompts. Machine-verified labels describe executed checks, not human review. A passing synthetic repair is evidence for that case, not a production guarantee.

The full checkpoint reference, training job, and immutable dataset hash are recorded in [submission.md](submission.md#confirmed-training-receipt). Loss values from different minibatches are not a measured quality improvement.

## Short answers for judges

**Who pays?** “Engineering teams that own retry-heavy commerce and webhook integrations. We would start with a paid pilot on their own incidents. Team subscription plus training compute is the pricing hypothesis.”

**Why learning rather than memory alone?** “We measure both. Memory and learned receive the same input tokens on excluded cases, so we can see whether the weight update adds anything in this experiment.”

**What do you own?** “The accepted examples, their lineage, and the trained adapter once exported. River handles compute here. The adapter still needs compatible base weights and an inference runtime.”

**What is UFO doing today?** “We built and SDK-verified the extension that calls the repair specialist and captures observable task events. We have not demonstrated an authenticated live UFO conversation.”

**How does this grow beyond a sample storefront?** “The Repository tab works with local Python source and regression tests in an isolated snapshot. We executed a real source/test pair: seven passed, one skipped. The learning experiment shown here still uses the bounded event-handler curriculum.”

## Submission video

Title: **Reflex — your next incident learns from the last fix**

Description: **Real River repairs, executable checks, and a saved specialist trained with 16 weight updates on 24 verified examples. Four held-out cases: base 4/4, memory 4/4, learned 4/4. The training workflow is demonstrated; no accuracy gain was measured.**

After uploading, put the playable URL into [submission.md](submission.md). A local recording path is not a submission URL.
