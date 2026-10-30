# Field notes (not rules)

Practices and pitfalls collected while doing real tasks with `otto`. **They are not rules and may be out of date**; where they disagree with the
regular topics, the topics win, and `otto describe` wins on parameters. When unsure, use your own judgement.

## Where to start from the problem at hand

| What you want | Look at first |
|---|---|
| What the library already has (sources, subtitles, vocals, analysis) | `sources.list`, `sources.get`, `assets.tracks`, `textLayer.list`, `sources.prep`, `jobs.list` |
| Tidy subtitles, get a whole or partial vocal | topic `prepare`; separation does not need subtitles, so you can get the vocal first to help with the subtitles and import them last |
| Pick lines, cut, analyse, tag | topic `samples` |
| Hand sound to an external tool and write the conclusion back | topics `combine`, `export` (the `mapping` in results) |

You do not have to prepare everything from scratch each time: pick up from the results that already exist.

## Some combinations

- Subtitles are fine already: import the text layer → pick lines with their context → analyse or create samples only for the chosen segments.
- You need to hear the voice while fixing subtitles: register the source → use an existing or new vocal (a part is enough) → `exports.wav` the range for an external tool → import the subtitles when done.
- Only one sound matters: separate a part, export or cut it, settle the range, then create a sample or flatten; no need to complete the episode's subtitles first.
- Comparing instrument / one-shot material: read pitch, export clips, compare spectra etc. externally, tag the candidates and let the owner listen.

## Mapping external times back to the source

Results of `exports.wav` / `exports.range` / `exports.stretched` / `hits.export` carry `mapping` (file seconds → source seconds, a polyline).
For a time t in the file from an external tool, linear interpolation over `mapping` gives the source time; write segment boundaries back in source seconds (`segments.get` for the version → `edits.apply`, entity `segment`, fields `start` / `end`).
Scripts run with `otto run` can also use the app's implementation: `from ottosmasher.domain.mapping import Mapping; Mapping.of(m).to_source(t)`.

## Shifting many line times at once

Put the `start` / `end` updates of many `segment`s into the `ops` of one `edits.apply`: one commit, one undo. To remove unwanted segments: the same kind of update with fields `{"deleted": true}`.
Segments whose text or boundaries changed lose their old analysis; with the setting `analysis.auto_rerun_segments` (off by default) the app re-analyses them in the background, otherwise submit it yourself.

## Retiming: rough first, then refine with alignment

Tried on 2026-10-29 with 20 analysed lines: shifting their times by ±0.5 / ±1.5 s and widening the analysis window to ±2 s, alignment **always "succeeded"**,
but the recovered start/end were mostly 1–2 s off (only a few within 50 ms) — the aligner fits the whole line into the window; it does not find where the line is.
So: first get line boundaries roughly right (within a few tenths of a second) from a transcript with word timestamps (e.g. audio-mcp's `audio_transcribe`, Whisper), write them back,
then run speech analysis and refine with the first and last phoneme times. Separated vocals are steadier than the original mix.

## When you cannot hear

Models without native hearing can use audio-mcp (installed by the owner with `uvx` and registered as an MCP server): `audio_view` (spectrogram / waveform images to look at),
`audio_analyze` (loudness, peaks, onsets, pitch etc.), `audio_transcribe` (Whisper turbo with word times and uncertain words).
Point it at exported WAVs or the original media; it is CPU only, so split long audio with `start` / `end`.

## External tools used before (production task of 2026-10-26, removed afterwards)

- Multilingual sentence embeddings (MiniLM, ONNX): matching Chinese and Japanese subtitle lines.
- mlx-whisper (small and large-v3-turbo): local transcription of doubtful subtitle passages, two rounds.
- Matplotlib: plotting waveforms, pitch and spectra to look at; Mido: reading MIDI tracks and pitches; RAR / UnRAR: unpacking some subtitle archives.
Clean up tools and models when done, and list what you removed.

## Pitfalls met

- Keywords mis-hit (in Kemono Friends 「ボス」 is a character, 「プレーリー」 an animal); prefilter locally, then judge each candidate with its context; do not read thousands of lines into context.
- Re-importing subtitles replaces only old segments overlapping in time; non-overlapping old segments stay and must be deleted by you (also in topic `prepare`).
- A pitch measurement job can be `succeeded` with an empty result and the errors in `f0Errors`; check the result, not only the status.
- Keeping one connection open through long external computations can let events pile up; short connections (one `otto call` each) are steadier.
- Separating 65 whole episodes once filled the disk with intermediate files (fixed: they are deleted after success); check free space before big batches and submit in batches.
- Do not pile working files in the workspace root; use your own temporary folder and list what you left behind.
