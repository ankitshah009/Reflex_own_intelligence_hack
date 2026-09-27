# Repair workbench browser QA

URL: http://127.0.0.1:5173/

Browser: installed gstack browse, dedicated tab opened and closed by this pass.

## Runtime evidence

- Desktop viewport: 1440 × 1000; document width 1440.
- Mobile viewport: 390 × 844; document width 390; no visible horizontal overflow.
- Local original-handler reproduction: 2 orders, 8 widget units, $144.00 balance, 2/4 behavioral checks passing.
- Existing live River repair selected from saved attempts: 1 order, 10 widget units, $120.00 balance, 4/4 checks passing.
- Unsaved whitespace edit: verification count cleared, preview reset to 0 orders / 12 units / $96.00 initial state, acceptance disabled.
- Closed mobile case navigation has computed visibility hidden and is absent from the interactive accessibility tree.
- Unfocused skip link is clipped to a 1px box; it is absent from screenshots.
- Fresh console error buffer: no console errors.
- No additional model calls, training requests, feedback labels, or acceptance actions were submitted in this QA pass.

## Screenshots

- `repair-desktop-broken.png`: actual baseline reproduction.
- `repair-desktop-fixed.png`: existing verified River repair, unaccepted.
- `repair-mobile-fixed.png`: same verified repair at mobile width.

## Fixes and durable observations

- The legacy stylesheet defines a column direction for all navigation elements; the workbench top navigation must explicitly set `flex-direction: row`.
- Background job logs must be associated with `job.payload.case_id`; otherwise an unrelated running repair can appear to describe the selected case.
- A skip link positioned above the viewport can appear in a full-page capture at a preserved scroll offset. Clip it when unfocused, reveal only for keyboard focus, and transfer focus to the main region when activated.
- Primary supporting copy now uses #58677c; verified computed color is rgb(88, 103, 124).

Production verification: `npm run build --prefix frontend` passes.

## Learning and replay QA

- Read-only browser pass at 1440×1000 and 390×844. No model requests, training requests, or acceptance labels were submitted by this QA pass.
- Initial state: six real attempts, zero accepted repairs, no checkpoint. Training and replay controls disabled; all three conditions displayed “Not measured.” Saved `repair-learning-desktop.png`.
- Root then authorized five sample acceptances and one live SFT run. The actual job `7d56f384-1e98-4750-98f1-a138df5b25a6` reported `RiverConnectionError`. The screen showed that error, retained all five accepted examples, and kept scores unmeasured.
- Fixed terminal learning logs disappearing: the latest training/evaluation job now keeps its persisted events, final status, and error visible after completion/failure and after reload.
- Added actual measured checkpoint identity to replay metadata, separate from the checkpoint selected for the next evaluation.
- Browser reload confirmed persisted failed-job history, 390px document width at a 390px viewport, and no fresh console errors.
- Final real-state captures inspected: `repair-learning-live-desktop.png`, `repair-learning-mobile.png`.
- Production build passed. Checkpoint/evaluation field bindings were checked against the backend route contracts; completed learning and evaluation rendering has not yet been exercised with a real checkpoint because this observed SFT attempt failed. No checkpoint or score was injected for QA.
