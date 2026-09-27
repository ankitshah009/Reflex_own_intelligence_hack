# Reflex demo video

**Ready:** 115.543 seconds, 1920 × 1080, H.264/AAC, 4,064,507 bytes. Full decoding completed successfully. Narration peaks at −1.6 dB, with no clipped samples indicated.

- `reflex-demo-narrated.mp4`: 1080p edited walkthrough, with local macOS Samantha narration.
- `index.html`: local video player with poster and transcript links; this file is not itself a hosted URL.
- `reflex-demo-clean.mp4`: the same picture without audio, for a founder voice-over or a live presentation.
- `provenance.json`: the exact narration, scene timings, and genuine screenshot sources.
- `narration.txt`: the spoken script.

This is an edited walkthrough of actual product captures, not a continuous live screen recording. It shows the original checkout handler, its saved River repair, executed behavioral checks, the verified dataset, and the completed `reflex-repair-v3-20260927` checkpoint.

The measured held-out result is **base 4/4, memory 4/4, learned 4/4**. Memory and learned inputs matched. This small benchmark did not measure an accuracy gain. The checkpoint was trained with 16 confirmed updates on 24 eligible examples; no reinforcement-learning update is claimed.

The repository segment shows inspection and baseline execution, not a generated repository repair. The UFO extension was SDK verified; no authenticated live UFO conversation is shown.

## Submission

Upload `reflex-demo-narrated.mp4` to the chosen video host and use its playable URL in the submission form. A local path is not a public video URL. No upload or external posting is performed by the render script.

## Rebuild

From the repository root, with the installed gstack browser available:

```sh
.venv/bin/python .cache/demo/build_demo.py
```

The script reads `.cache/demo/manifest.json`, renders local HTML composition cards around unaltered screenshots, generates speech locally, and encodes H.264/AAC with FFmpeg. It does not call the app API or River.

## Capture verification

Wait for the execution status indicator before capturing a local reproduction; a click returns before the result settles. Select **Original** explicitly for the broken baseline, because **Reproduce issue** runs the currently selected preview source.

The current UI was also exercised during background training: original handler 2/4, two orders, 8 units, $144; saved River patch 4/4, one order, 10 units, $120. Additional paid repair requests remained disabled during the active training job.
