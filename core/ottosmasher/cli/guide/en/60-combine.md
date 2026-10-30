# Your judgement and tools, written back into the app

The app is the library and the analysis engine; judgement and other tools are yours. The pattern is always: **read the data → decide or
process it yourself → write the conclusion back into the app**.

## Where conclusions go

| your conclusion | write it back with |
|---|---|
| these samples belong to a class (topic, character, tone…) | `samples.batchEdit {"ids", "fields": {"addTags": [...]}}` → `edits.apply` |
| this line should become a sample | `samples.plan` → `samples.createPlanned` (topic `samples`) |
| the OP / ED is here | `oped.add {"sourceId", "kind": "OP" / "ED", "start", "end"}` (source seconds) |
| a line is spoken here (missing from the subtitles) | `segments.add`; to change an existing segment: version from `segments.get` → `edits.apply` (entity `segment`) |
| which audio stream the source should use (analysis track) | `sources.get` for the `version` → `edits.apply` (entity `source`, field `default_audio_stream`) |
| which track is the vocal / sfx | `tracks.setDefault`, `tracks.setRole` |
| processed audio goes back into the library | `reimport.preview {"assetId", "start", "path"}` → `reimport.commit` |
| a picture or clip as a sample's picture | `visuals.bind {"ownerType": "sample", "ownerId", "path"}` |

All of these are undoable and recorded under your session.

## Getting the raw material

* Text: `textLayer.list {"sourceId"}` (segments, sound hints, OP/ED); the subtitle files themselves.
* Audio: the source media file (`path` in `sources.list`; read it directly with ffmpeg, **read-only**); or export: `exports.wav`, `exports.range` (WAV; the result carries the file-seconds → source-seconds `mapping`), `exports.samples`.
* Pictures: `visuals.forSample {"id"}` (which file and range the picture comes from); `exports.video`, `exports.videoRange` (clips).
* Analysis: `speech.sample` (the segments and phonemes a sample reads), `measure.f0` (pitch curve).
* If you cannot hear, look at exported WAVs with an audio analysis tool in your environment (e.g. audio-mcp's spectrograms, loudness, timed transcripts) (topic `notes`).

## Examples

* **Choosing lines**: do not read thousands of lines into your context. Prefilter locally by keywords or rules, then read each candidate
  with its neighbours and decide. Keywords misfire (in Kemono Friends 「ボス」 is a character and 「プレーリー」 an animal); judge by meaning.
* **Finding the OP / ED without subtitles**: every episode of a work has the same OP / ED song. Extract the first and last minutes of
  audio of several episodes with ffmpeg and compare them; the longest stretch of near-identical audio is the OP (or ED); then `oped.add`.
  Report episodes that do not match (different version, no OP) to the owner instead of guessing.
* **Messy subtitles**: clean the files as in topic `prepare` section 0, then import.
* **An analysis result looks wrong**: find the cause first (typos in the subtitle, wrong vocal track, inaccurate segment bounds), fix it and
  analyse again; when unsure, export that audio and listen to it yourself.

## Keep the owner informed

Before writing, summarise big or ambiguous decisions for the owner (which lines count as "about games", which separation model,
how many files you will change). Your changes show up as "data updated" in the app and under your session in its **History** panel, and can be undone as a whole.
