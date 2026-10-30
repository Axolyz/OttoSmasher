# Primitives: computations that do not touch the library

Commands come in two layers (`otto commands --layer library|primitive`): **library commands** work on objects in the library (sources, samples, edits, undo);
**primitives** only compute and never change the library, and their sound can be a track in the library or any file, no registration needed. Both layers use the same engine and models, so results match the app.
Use library commands when the result should stay in the library (searchable, undoable); use primitives to just compute something, or to work on sound outside the library.

## Sound input

`{"assetId": "<track>", "start": s, "end": s}` (asset seconds) or `{"path": "/some/file.wav", "stream": 0, "start": s, "end": s}` (file seconds; videos work too, `stream` = which audio stream).
Without `start` / `end` the whole track is used.

## Commands

| Command | What it does | Results |
|---|---|---|
| `speech.align {"items": [{"text", <sound input>}, ...]}` | Japanese alignment: phoneme, mora and word times | `speech.alignResults {"jobId"}` |
| `text.analyze {"texts": [...]}` | Japanese reading: phonemes, morae (katakana), words and readings (with the user dictionary) | `text.analyzeResults {"jobId"}` |
| `f0.track <sound input>` | Pitch (FCPE, the same model as the app's pitch search): pitch, confidence and energy every 10 ms + median pitch | `f0.trackResults {"jobId"}` |
| `subtitles.parse {"path", "duration"}` | How the app would read this subtitle file with the current rules (lines, sounds, speakers, OP/ED pairs) | returned directly |
| `subtitles.ruleTest`, `dictionary.check`, `spectrum.get` | How one subtitle line is read, user dictionary validation, the spectrum of a track range | returned directly |

The first three are jobs: with `--wait` the call waits for the end and prints the per-item results too (`{"job", "results"}`). One failed item in a batch (e.g. text that is only symbols) does not affect the others.
`subtitles.parse` decides OP vs ED from the media duration, so pass `duration` (by default the last cue's end is used and the decision may be wrong).

## When alignment works

The aligner only fits the whole line **into the window you give**; it does not look for where the line is and never reports "no match". The window must hug the actual speech: 0.1–0.2 s of margin on each side.
Tested on 2026-10-29 / 30 with 60 lines: widening the window to 0.5 s on each side moved the start or end by more than 0.3 s for about half of them; shifting the time by 0.5 s or more almost never aligned well.
`edges` (blank time between the window ends and the first / last phoneme) and `longestPhone` in the result are facts, not verdicts: an edge near 0 may mean the speech is cut by the window; an absurdly long phoneme usually means the window is too wide.
Where windows come from: existing line segments, a transcript with word timestamps, or loudness on/offsets. Languages other than Japanese are not supported.
