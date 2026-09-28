# Reflex demo video

**Ready:** 111.7 seconds, 1920 × 1080 at 30 fps, H.264/AAC, 40.6 MB. Full decode check passed. Loudness −16.0 LUFS integrated, −1.6 dBTP true peak.

- `reflex-demo-narrated.mp4`: final narrated video with burned-in captions (watchable on mute).
- `reflex-demo-clean.mp4`: the same picture without audio.
- `narration.txt`: complete spoken script, by chapter.
- `provenance.json`: scene timings, captions, sound cues, loudness, and evidence sources.
- `index.html`: local video player. A local path is not a hosted submission URL.

## How it was made

A motion-graphics walkthrough rendered frame by frame from HTML scenes. Every product view is an unedited retina capture of the running app (zoomed, panned, and highlighted, never repainted). Every number comes from a recorded run in `docs/evidence/` or `docs/verification.md`.

- Narration: local Kokoro TTS (kokoro-onnx 0.6.1, voice `af_heart`), no cloud services.
- Music and sound effects: original, synthesized locally from oscillators and noise; no samples.
- Chapters: Reproduce → Repair → Verify → Train → Reuse (UFO calls the trained v4 checkpoint) → Measure → Proof.

## Sources

- `docs/evidence/reflex-v4-training.json`: Qwen3.5-9B, 48 LoRA SFT steps, 24 examples, 122,752 tokens.
- `docs/evidence/ufo-live-v4.json`: recorded UFO SDK call of `repair_code_with_reflex`, checks 2/4 → 4/4 in 5.7 s.
- `docs/evidence/reflex-v3.json`: held-out comparison, base / memory / learned 4/4 each, identical memory and learned inputs.
- `docs/verification.md`: 240 backend tests and 88 subtests passing; dataset provenance (19 machine-verified + 5 operator-accepted).

## Rebuild locally

The build workspace lives in `.cache/demo-v2/` (gitignored): `script.json` (narration and facts), `scenes/` (one HTML scene per chapter on a shared time-driven runtime), `render.mjs` (Playwright frames piped to FFmpeg), and `assemble.py` (narration, ducked music, sound effects, two-pass loudness normalization, final encode).

```sh
cd .cache/demo-v2
node render.mjs --jobs 1
../../.venv/bin/python assemble.py --music-offset -0.15
```

Rendering makes no River calls, app API calls, uploads, or Git operations.
