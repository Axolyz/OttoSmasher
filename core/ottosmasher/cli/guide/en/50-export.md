# Export

Exports are written under the workspace (`Library/Exports` by default; `exports.wav` takes a `directory` to write elsewhere) with names built by the app's naming rule; the command returns the
paths. Copy files from there to where you need them; do not rename or delete inside the workspace.

| What | Command |
|---|---|
| Samples as WAV (original, or stretched to the global BPM per sample) | `exports.samples {"ids": [...], "versions": {"<id>": "stretched"}}` → list of paths |
| One sample stretched, with a manifest | `exports.stretched {"id"}` |
| Any asset range as WAV | `exports.wav` / `exports.range` |
| A sample as a **video clip** (its picture: synced video, image or loop) | `exports.video {"id", "version": "original"} --wait` → `video.path` |
| An asset range as a video clip | `exports.videoRange {...} --wait` |
| A search hit | `hits.export`, `hits.video` |
| REAPER track template | `reaper.template` (the clipboard hand-off exists only in the app) |

WAV exports (`exports.wav`, `exports.range`, `exports.stretched`, `hits.export`) return, besides `path` and `reused`, coordinates for external tools:
`range` (the asset range actually exported, after rounding to source samples), `sampleRate`, `frames`, `mapping` (file seconds → source seconds; for stretched versions the composed mapping including the stretch).
`content` / `track` of `exports.wav` are only words in the file name; `assetId` decides which sound is exported.
After a video export finishes, its path is also in the job result (`result.path` in `jobs.list`), so you can look it up by job later.

Video export fails with an error (no black video) when a sample has no picture; bind one first (topic `combine`).
The global BPM for stretched versions: `rhythm.bpm` (read). It is set by the owner in the app.
