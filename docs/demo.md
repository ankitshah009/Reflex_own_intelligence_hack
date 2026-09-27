# Reflex demonstration

## Evidence before presenting

Run the real sponsor path first. Record the UFO revision, River base model, confirmed dataset hash, saved checkpoint URI, evaluation set hash, and measured result. Use the live app or a recorded run of that same execution. Keep failure states available; a failed training run is not a checkpoint.

## Current two-minute repair demonstration

**0:00–0:20 — The problem.** Open the repair workbench. “A checkout retry should
not charge twice. Here it creates two orders and deducts inventory twice.” Run
the original handler and show its 2/4 checks and actual preview state.

**0:20–0:45 — Work with a result.** Open the saved River repair, explicitly
identifying it as the recorded live run. Show the patch's early return for an
already-processed event, one resulting order, and 4/4 checks. The observed first
run took 15.4 seconds. The model generated executable source; Reflex ran it.

**0:45–1:15 — Learning from correction.** Show the stock replay attempt that
still fails. Inspect the correction and approval before adding it to training.
Only show a checkpoint if the River run has actually finished and its receipt
is saved. A passing repair alone is not a demonstration of learned weights.

**1:15–1:45 — Measure the claim.** Show completed base/memory/learned results
case by case, with four held-out cases per condition. Do not fill empty results
with illustrative numbers. “The prompt did not change; the model did” applies
only to the memory-versus-learned comparison with matching input hashes.

**1:45–2:00 — Product and ownership.** “Engineering teams already pay to fix
the same classes of incidents. Reflex turns accepted fixes into a specialist
they can inspect and export. We are testing whether that reduces corrections
on the next incident.” Explain that this is an adapter on a base model, with
River-hosted checkpoint storage and compute; ownership does not mean free or
independent inference infrastructure.

The UFO extension has been verified through the real installed SDK, but a live
authenticated UFO conversation has not been demonstrated. State that directly.

## Original PR-review demonstration

**Work.** Ask UFO to review an engineering patch with its normal tools and `review_code_with_reflex`. Show the observed trajectory and specialist review in Reflex.

**Correction.** Supply a specific repository convention the review missed, or confirm a correct judgment. Explain that a final decision and a justified correction become a training example; the hidden reasoning is not collected. Show the dataset export and provenance.

**Learning.** Start a bounded River run from already accumulated, explicitly confirmed experiences. Show actual progress, actual optimizer updates, and the checkpoint receipt. If presenting a completed run, identify it as recorded rather than simulating live training.

**Measurement.** Show the held-out comparison, including the denominator and any failed answers. The memory and learned models receive exactly the same inputs. Only display improvement if measured. A flat or worse result is a valid experiment and a signal to improve the curriculum.

**Return to work.** Ask UFO to review a new PR using the saved specialist checkpoint. Show its checkpoint identity and the resulting review.

## The claim

UFO gives the agent a place to work. River lets it learn from that work. Reflex connects the experience, correction, learned weights, and evidence.

“The prompt did not change. The model did.” applies to the **memory versus learned** comparison. The base condition intentionally omits memory. Do not use fictional curriculum counts as completed agent work or training loss as held-out accuracy.

## If live access is unavailable

Show the functional review workspace, manually confirmed data pipeline, export, provider setup, and local verification evidence. Say that live training and improvement have not been demonstrated. Do not manufacture the missing magic moment.
