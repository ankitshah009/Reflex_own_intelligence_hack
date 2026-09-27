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

Reflex turns recurring software failures into a specialist an engineering team can train and reuse. Reproduce a duplicate checkout, inventory replay, or refund bug; generate a patch with River; execute the checks; and turn verified repairs into training data. We trained Qwen3.5-9B with 48 weight updates on 24 examples. A real UFO SDK tool then used that checkpoint to repair a stock training case from 2/4 to 4/4 passing checks in 5.7 seconds. Every repair, training snapshot, checkpoint, and outcome is traceable. Reflex connects an agent's working experience to a repair specialist the team can inspect and reuse.

### Github URL

https://github.com/ankitshah009/Reflex_own_intelligence_hack

### Demo Video URL (loom, vimeo, etc)

https://ankitshah009.github.io/Reflex_own_intelligence_hack/

### Side Quest (if any)

- River AI
- UFO

### Anything else you'd like the judges / organizers to know?

The demo uses a fictional storefront with real Python execution and real River model calls. The first checkout repair raised passing checks from 2/4 to 4/4 in 15.4 seconds. This measures the generated repair; the effect of fine-tuning requires the separate held-out comparison.

We retain failed attempts, distinguish operator acceptance from machine verification, and exclude held-out cases from training. The latest dataset contains 24 eligible examples: five operator-accepted repairs and 19 machine-verified generated repairs. The generated cases are variations of six failure families, not customer incidents.

River saved `reflex-repair-v3-20260927` after 16 confirmed weight updates on these 24 examples. The completed held-out result is base **4/4**, memory **4/4**, learned **4/4**, with matching memory/learned prompts. All three reached this small benchmark's ceiling; there is no measured accuracy gain. This run used supervised fine-tuning, with no reinforcement-learning steps. Failed earlier attempts and the original evaluation remain saved.

The longer v4 run completed 48 updates and processed 122,752 training tokens on the same 24 examples. A real programmatic UFO SDK tool invocation then used that checkpoint to repair the stock training case from 2/4 to 4/4 checks in about 5.7 seconds, importing its observable trace. This demonstrates live use of the trained specialist through the installed SDK. A full authenticated UFO chat has not been demonstrated, and this training-case repair does not establish generalization. The repeated v4 benchmark had one base execution permission error, so it does not establish an accuracy gain. Our ownership path includes the training examples, dataset lineage, and a downloadable River adapter; the adapter still requires compatible base-model weights and compute.

Receipts: [v4 training and replay](evidence/reflex-v4-training.json), [live UFO tool invocation](evidence/ufo-live-v4.json), [original v3 comparison](evidence/reflex-v3.json).

## Final result line

Lead with the live v4 specialist use, then preserve the completed v3 comparison:

> River trained our specialist with 48 weight updates on 24 verified examples. The real UFO SDK tool used it to repair a stock training case from 2/4 to 4/4 checks in about 5.7 seconds, saving its observable trace.

> Across four excluded repair cases, base, memory, and the learned specialist each passed **4/4**. Memory and learned inputs matched. This small benchmark reached its ceiling; we did not measure an accuracy gain from training.

The later v4 replay included a base execution permission error. Keep the original v3 result and this infrastructure error visible; neither the repeat nor the live training-case repair proves a held-out accuracy gain.

## Confirmed training receipt

Latest checkpoint: `reflex-repair-v4-48steps-20260927` — **48 SFT updates,
24 examples, 122,752 processed training tokens, four passes, zero RL steps**.
Its [receipt](evidence/reflex-v4-training.json) records the saved checkpoint and
the repeated evaluation's execution error. The [live UFO receipt](evidence/ufo-live-v4.json)
records the actual specialist call and imported trace. The original v3 receipt
below remains part of the evidence.

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
3. Confirm the hosted recording plays without requesting access and includes the v4/UFO segment.
4. Confirm GitHub `main` includes the functionality shown in the video.
5. Paste the form fields and submit. This document has not submitted the form or sent email.
