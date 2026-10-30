# Your judgement and tools, written back into the app

The app is the library and the analysis engine; judgement and other tools are yours: you read the data, decide or process it yourself,
and write back the conclusions that should stay.

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

All are recorded under your session. Edits (tags, segments, OP/ED, default tracks, pictures) can be undone; newly created samples (`samples.plan` / `samples.create`) and reimported tracks cannot — they can only be deleted (with the owner's confirmation).

## Getting the raw material

* Text: `textLayer.list {"sourceId"}` (segments, sound hints, OP/ED); the subtitle files themselves.
* Audio: the source media file (`path` in `sources.list`; read it directly with ffmpeg, **read-only**); or export: `exports.wav`, `exports.range` (WAV; the result carries the file-seconds → source-seconds `mapping`), `exports.samples`.
* Pictures: `visuals.forSample {"id"}` (which file and range the picture comes from); `exports.video`, `exports.videoRange` (clips).
* Analysis: `speech.sample` (the segments and phonemes a sample reads), `measure.f0` (pitch curve).
* If you cannot hear, look at exported WAVs with an audio analysis tool in your environment (e.g. audio-mcp's spectrograms, loudness, timed transcripts) (topic `notes`).

## Keep the owner informed

Before writing, summarise big or ambiguous decisions for the owner (which lines count as "about games", which separation model,
how many files you will change). Your changes show up as "data updated" in the app and under your session in its **History** panel, and can be undone as a whole.
