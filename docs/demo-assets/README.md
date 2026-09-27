# Reflex demo video

**Ready:** 104.252344 seconds, 1920 × 1080, H.264/AAC, 3,526,332 bytes. Full decoding completed successfully. macOS Samantha narration, mean −16.3 dB and peak −1.7 dB.

- `reflex-demo-narrated.mp4`: final narrated video.
- `reflex-demo-clean.mp4`: the same picture without audio.
- `narration.txt`: complete spoken script.
- `provenance.json`: scene timings from encoded video frames, source evidence hashes, and receipt fields.
- `index.html`: local video player. A local path is not a hosted submission URL.

## What the recording shows

This is an **edited walkthrough**, using genuine app screenshots and faithful compositions of saved provider receipts. It is not a continuous live screen recording.

The original checkout handler creates two orders and passes 2/4 checks. Its saved River repair creates one order and passes 4/4. Generation uses rejection-sampling fine-tuning: **24 generated tasks → 23 River requests → 19 verified repairs**, plus five accepted repairs, produce 24 eligible examples.

The latest checkpoint is **reflex-repair-v4-48steps-20260927**: **48 confirmed weight updates, 24 examples, 122,752 training tokens**, SFT only. The checkpoint slide uses the v4 receipt, not an older screenshot.

The short held-out comparison is explicitly the **earlier v3 experiment**: base 4/4, memory 4/4, learned 4/4. No learning advantage is claimed. The separate v4 repeat encountered a base execution infrastructure error; it is not presented as a model improvement.

## UFO climax

The dedicated UFO sequence occupies **81.933–96.533 seconds** in the video. It shows a recorded **programmatic UFO SDK invocation** of `repair_code_with_reflex`, using the v4 River checkpoint on training case `repair-stock-replay`.

- Original checks: 2/4.
- Specialist repair: 4/4, with the OS sandbox enforced.
- Recorded timestamps: 23:38:53.251702 → 23:38:58.944854 UTC.
- Recorded elapsed time: 5.693152 seconds, displayed as 5.7 seconds.
- Source: `docs/evidence/ufo-live-v4.json`.

The sequential highlights animate the **saved receipt** for presentation. They are not an attempt to reproduce the original stage timing. The sequence does not claim a full agent conversation or held-out improvement. The ending states that UFO used the trained specialist.

## Sources

- `docs/evidence/ufo-live-v4.json`
- `docs/evidence/reflex-v4-training.json`
- `docs/evidence/reflex-v3.json`

## Rebuild locally

```sh
.venv/bin/python .cache/demo/build_demo.py
```

The render script uses the installed gstack browser, local macOS speech, and FFmpeg. It performs no River calls, app API calls, uploads, or Git operations.
