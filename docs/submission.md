# Reflex — hackathon submission

## Paste-ready fields

### Email

ankit.tronix@gmail.com

### Team Name

Reflex

### Member Names + Emails (comma separated)

Ankit Shah (ankit.tronix@gmail.com)

### Project Description

Reflex turns an engineering team's recurring failures into a model the team owns. It reproduces failures such as a duplicate checkout, an inventory replay, or a replayed refund, gets a patch from River, runs behavioral checks in an OS sandbox, and turns every verified repair into training data. We fine-tuned Qwen3.5-9B on River with 48 updates on 24 verified repairs. Our UFO extension then called that model and fixed the stock-replay bug, lifting its checks from 2/4 to 4/4 in 5.7 seconds. The team owns the loop: the agent's experience, the verified dataset, and the trained model. Every repair, training snapshot, checkpoint, and outcome is traceable.

### Github URL

https://github.com/ankitshah009/Reflex_own_intelligence_hack

### Demo Video URL (loom, vimeo, etc)

https://ankitshah009.github.io/Reflex_own_intelligence_hack/

### Side Quest (if any)

- River AI
- UFO

### Anything else you'd like the judges / organizers to know?

Built solo during the hackathon. Every number below comes from a recorded run, with receipts linked at the end.

- The agent's work trains our own model. Of 24 generated practice tasks, River's repairs passed every behavioral check on 19. Together with 5 operator-accepted fixes, that gave 24 verified examples across six failure families. We fine-tuned Qwen3.5-9B on them with River: 48 LoRA fine-tuning steps over 122,752 training tokens.
- The agent then uses that model. Our UFO extension's repair tool called the checkpoint through the UFO SDK and fixed the stock-replay bug, lifting its checks from 2/4 to 4/4 in 5.7 seconds. Reflex imported the call's trace into its experience ledger, which closes the loop.
- Execution decides correctness, not an LLM judge. Every patch runs against behavioral checks in an OS-level macOS sandbox with no network, host writes, or child processes, under CPU, time, and memory limits. River's first checkout repair lifted the checks from 2/4 to 4/4 in 15.4 seconds.
- The data is auditable. Failed attempts stay on record, every example is labeled operator-accepted or machine-verified, and each training snapshot is SHA-256 hashed and tied to the checkpoint it produced.
- The evaluation is controlled. Held-out incidents never enter training, and the memory and learned conditions receive identical input tokens, so any difference between them comes from the weights. On four held-out incidents, base, memory, and learned each passed 4/4. The benchmark saturated, so harder held-out incidents are the next experiment.
- It reaches beyond the sample store. The Repository tab applies candidate patches to local Python source and runs its pytest tests in an isolated snapshot. The backend passes 240 tests and 88 subtests.

Who pays: engineering teams that run checkout, inventory, refund, and webhook systems, where a retried webhook creates duplicate orders or deducts inventory twice. Every accepted fix becomes training data for the team's own specialist. The team owns the dataset, its lineage, and the LoRA adapter, downloadable from River in PEFT format.

Receipts:

- v4 training run: https://github.com/ankitshah009/Reflex_own_intelligence_hack/blob/main/docs/evidence/reflex-v4-training.json
- Live UFO tool call: https://github.com/ankitshah009/Reflex_own_intelligence_hack/blob/main/docs/evidence/ufo-live-v4.json
- Held-out comparison: https://github.com/ankitshah009/Reflex_own_intelligence_hack/blob/main/docs/evidence/reflex-v3.json
- Full verification log: https://github.com/ankitshah009/Reflex_own_intelligence_hack/blob/main/docs/verification.md

## Final result line

Use these two lines when presenting:

> We fine-tuned Qwen3.5-9B on River with 48 updates on 24 verified repairs. Our UFO extension then called that model and fixed the stock-replay bug, lifting its checks from 2/4 to 4/4 in 5.7 seconds.

> On four held-out incidents, base, memory, and the learned specialist each passed 4/4, with memory and learned receiving identical inputs. The benchmark saturated; harder held-out incidents are next.

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

1. Preserve the completed v3 result and identify any later result separately.
2. Confirm the hosted recording plays without requesting access and includes the v4/UFO segment.
3. Confirm GitHub `main` includes the functionality shown in the video.
4. Paste the form fields and submit. This document has not submitted the form or sent email.
