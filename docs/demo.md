# Reflex demonstration

## Evidence before presenting

Run the real sponsor path first. Record the UFO revision, River base model, confirmed dataset hash, saved checkpoint URI, evaluation set hash, and measured result. Use the live app or a recorded run of that same execution. Keep failure states available; a failed training run is not a checkpoint.

## A focused three-minute story

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
