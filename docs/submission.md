# Reflex — hackathon submission

## Paste-ready fields

### Email

ankit.tronix@gmail.com

### Team Name

Reflex

### Member Names + Emails (comma separated)

Ankit Shah — ankit.tronix@gmail.com

Assuming a solo team. Add any teammates and their emails before submitting.

### Project Description

Reflex turns verified engineering repairs into training data for an agent that can learn from its work.

Start with a checkout webhook delivered twice: two orders, inventory deducted twice. Reflex reproduces the failure, asks River for a patch, executes the repaired handler, and shows the resulting application state. Accepted fixes and machine-verified practice repairs become an immutable training dataset. River trains the repair specialist; a held-out replay compares the base model, memory, and learned weights using identical memory-versus-learned inputs. A UFO extension makes the specialist available inside an agent's workflow.

Our first users are engineering teams maintaining checkout, inventory, refunds, and webhook integrations. The product hypothesis is simple: the next incident should benefit from the last accepted fix. River saved our specialist after 16 supervised training updates on 24 verified examples. On four excluded cases, base, memory, and learned each passed 4/4. This run proves the training and evaluation workflow; the benchmark reached its ceiling and showed no measured accuracy gain.

### Github URL

https://github.com/ankitshah009/Reflex_own_intelligence_hack/tree/repair-workbench

### Demo Video URL (loom, vimeo, etc)

[Paste the hosted, viewable demo link after uploading the recording.]

### Side Quest (if any)

- River AI
- UFO

### Anything else you'd like the judges / organizers to know?

The demo uses a fictional storefront with real Python execution and real River model calls. The first checkout repair raised passing checks from 2/4 to 4/4 in 15.4 seconds. This measures the generated repair; the effect of fine-tuning requires the separate held-out comparison.

We retain failed attempts, distinguish operator acceptance from machine verification, and exclude held-out cases from training. The latest dataset contains 24 eligible examples: five operator-accepted repairs and 19 machine-verified generated repairs. The generated cases are variations of six failure families, not customer incidents.

River saved `reflex-repair-v3-20260927` after 16 confirmed weight updates on these 24 examples. The completed held-out result is base **4/4**, memory **4/4**, learned **4/4**, with matching memory/learned prompts. All three reached this small benchmark's ceiling; there is no measured accuracy gain. This run used supervised fine-tuning, with no reinforcement-learning steps. Failed earlier attempts and the original evaluation remain saved.

The UFO extension has been verified against its installed SDK; an authenticated live UFO conversation has not been demonstrated. Our ownership path includes the training examples, dataset lineage, and a downloadable River adapter; the adapter still requires compatible base-model weights and compute.

## Final result line

Use the completed v3 result in the recording and submission:

> Across four excluded repair cases, base, memory, and the learned specialist each passed **4/4**. Memory and learned inputs matched. This small benchmark reached its ceiling; we did not measure an accuracy gain from training.

Additional training is a separate experiment. Keep this v3 result visible even if a later run differs; do not present an unfinished run as a saved checkpoint or improvement.

## Confirmed training receipt

[Download the recorded v3 evidence as JSON](evidence/reflex-v3.json).

| Field | Saved value |
| --- | --- |
| Checkpoint name | `reflex-repair-v3-20260927` |
| Checkpoint record ID | `f847f65a-c018-4c6c-9fcb-a1d6133f08bf` |
| Training job | `9e154360-9d54-46c0-b74d-af65cb318764` |
| Confirmed optimizer updates | 16 |
| Training examples | 24 |
| Training tokens processed | 41,153 |
| Method | SFT; zero RL steps |
| Dataset SHA-256 | `2d472e4308987ef7a518a954e31646407bf7b46faa26f1e4b56876fc2d7c4a93` |
| Completed evaluation record | `cd50efd0-d079-430e-9121-d57a1b258207` |
| Evaluation job | `8bcea186-add2-43e0-a984-17127dfb8765` |
| Base / memory / learned | 4/4 / 4/4 / 4/4 |
| Memory/learned prompts matched | Yes |

Checkpoint reference:

```text
river://46becc1e-99d0-4a01-9d67-5ce7a04979d5/sampler_weights/reflex-repair-v3-20260927-c23bc8c8-27e9-40d4-be38-9739acded3c7
```

## Submission finish

1. Add teammates if this is not a solo submission.
2. Preserve the completed v3 result and identify any later result separately.
3. Upload the recording from [the demo script](demo-script.md); confirm its link plays without requesting access.
4. Confirm the GitHub branch includes the functionality shown in the video.
5. Paste the form fields and submit. This document has not submitted the form or sent email.
