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

The Repository tab also accepts a local Python source file under `backend/`
and its regression-test file under `tests/`. It captures a snapshot, runs pytest
in isolation, and retains candidate code, a diff, and execution evidence without
changing the original working files. A real source/test pair returned 7 passed
and 1 skipped; the repository-specific suite passed 30 tests. The completed
training experiment below used event handlers, not repository repairs.

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
SFT workload defaults to 16 steps with minibatches of two examples, on at most
32 examples and subject to token limits. Configuration supports a bounded
longer run. These workload limits are not a dollar cap. No dedicated deployment
is created.

## Verification status

The tokenizer is downloaded and verified. A real `Qwen/Qwen3.5-9B` checkout
repair completed in 15.4 seconds, changing the executed outcome from 2/4 to
4/4 passing checks. River then saved `reflex-repair-v3-20260927` after 16
confirmed SFT weight updates on 24 examples: five operator-accepted repairs
and 19 machine-verified generated repairs. No RL steps ran.

The completed four-case held-out replay produced **base 4/4, memory 4/4,
learned 4/4**, with identical memory/learned inputs. All three reached this
small benchmark's ceiling; no accuracy improvement was measured. Earlier
failed training attempts and this v3 result remain recorded. The complete
backend suite passed 234 tests and 88 subtests in 89.94 seconds; global Ruff
passed. The UFO extension is SDK-verified, with no authenticated live UFO
conversation claimed. See [verification.md](verification.md) for receipts.
