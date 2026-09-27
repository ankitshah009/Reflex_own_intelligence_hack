# Reflex release-repair workspace

## Current product goal

Build a practical workspace where a developer reproduces a broken customer flow,
inspects a proposed code repair, runs behavioral checks, and accepts or corrects
the repair. Confirmed repairs become training data for a River specialist. UFO
captures the observable work and calls the saved specialist on later tasks.

The main product surface is the running application and its repair evidence.
Training, checkpoints, and evaluation support that work. A visible improvement
must be measured against both the base model and the same model with feedback
memory, on a held-out set excluded from training.

## First supported workload

JSON event handlers with the interface `apply(state, event)`: duplicate requests,
replayed inventory events, and repeated operations. The handler mutates a JSON
state object and returns a JSON response. A developer can supply their handler,
initial state, event sequence, and expected state/responses as a custom case.
This is an explicit bounded repair environment, not automatic production access.

Synthetic examples provide a usable storefront preview. They are labeled as
samples and never presented as real incidents, revenue, or customer traffic.
The UI executes the candidate handler to obtain its preview state; it cannot
manufacture a successful repair or a measured learning improvement.

## End-to-end evidence required

1. Reproduce a real failing assertion from the supplied handler.
2. Obtain replacement source from River, with model/input provenance.
3. Execute the replacement in an isolated, bounded process and show actual checks.
4. Let a developer correct the source and explicitly approve a passing repair.
5. Freeze the approved dataset and train a real SFT checkpoint.
6. Compare base, memory and learned weights with identical memory/learned prompts.
7. Call the learned repair specialist through UFO on a new task.

Repair SFT is the first training method. The existing review RL reward is not
appropriate for executable repairs and is not advertised as repair RL.

## Cost and responsiveness

Editing, reproduction, local checks, and exports require no model call.
Inference/training are explicit operations. Jobs stream confirmed events;
interrupted jobs are retained and never automatically resubmitted. Partial
evaluation evidence survives failure. No numeric latency or cost improvement is
claimed before measurement. Live operations consume River credits. The default
SFT workload is four steps on at most 32 examples, subject to token limits;
these workload limits are not a dollar cap. No dedicated deployment is created.

## Verification status

River authentication and model access were checked successfully after the key
was supplied: the account includes `Qwen/Qwen3.5-9B`. That check submitted no
inference or training. The tokenizer is now downloaded and verified. A real
River checkout repair completed in 15.4 seconds, changing the executed outcome
from 2/4 to 4/4 passing checks. The repair API has 15 passing integration tests
using the real local sandbox and fake River I/O. No checkpoint or learning
improvement is implied by those results; see `verification.md` for live evidence.
