---
name: retiming-lines
description: "Fixes line boundaries in OttoSmasher with a rough pass and alignment, maps times from external tools back to the source, and writes many edits as one undo. Use when segments are mistimed or analysis results look wrong. Not needed for ordinary speech analysis."
---

# Retiming lines

The aligner fits the whole line into the window it receives and does not look for where the line is. Numbers are in `otto guide primitives`.

## Retime a line

1. Get boundaries within 0.1–0.2 s from a transcript with word times (such as audio-mcp's `audio_transcribe`) or from loudness on/offsets.
2. Refine with the first and last phoneme times from `speech.align`, which stores nothing. Leave 0.1–0.2 s of margin on each side and use separated vocals, which are steadier than the original mix.
3. Write the segments back.

In the alignment result, `edges` near 0 or an absurdly long phoneme, such as a 0.8 s 「ン」, usually mean the window is off or overlaps another line.

## Map external times to the source

WAV export results carry `mapping`, a polyline from file seconds to source seconds. Interpolate a time from an external tool over it.
Scripts run with `otto run` can call the app's implementation: `from ottosmasher.domain.mapping import Mapping; Mapping.of(m).to_source(t)`.

## Write back

- One segment: read the version with `segments.get`, then call `edits.apply` (entity `segment`, fields `start` / `end`).
- Many segments: put all the updates in the `ops` of one `edits.apply`, which makes one commit and one undo.
- Removing a segment: fields `{"deleted": true}`.

Segments whose text or boundaries changed lose their old analysis. Submit analysis again unless the setting `analysis.auto_rerun_segments` is on.

## When analysis looks wrong

Look for these causes first: a typo in the subtitle, the wrong vocal track (music in the original mix), or boundaries that are off. Fix the cause and analyse again. When unsure, export the audio and listen or look at its spectrogram.
