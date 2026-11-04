# Primitives: computations that do not touch the library

Commands come in two layers (`otto commands --layer library|primitive`): **library commands** work on objects in the library (sources, samples, edits, undo);
**primitives** only compute and never change the library, and their sound can be a track in the library or any file, no registration needed. Both layers use the same engine and models, so results match the app.
Use library commands when the result should stay in the library (searchable, usable later); use primitives to just compute something, or to work on sound outside the library.

## Register first, or call directly?

It depends on whether the result should stay and connect to the rest of the library:

| What you want | Which layer | Why |
|---|---|---|
| A one-off answer: check how a line reads or its timing, look at the pitch of a stretch, see how a subtitle file would be read | primitives, give the file directly | nothing enters the library, nothing to clean up |
| **Separation** | register first | separation only takes tracks in the library (`separation.submit` needs an `assetId`); there is no un-stored separation |
| Samples, search, beat-fitting, stretched exports, or anything the user should see in the app | register first, use library commands | these only work on library objects; note that partial separation creates samples automatically (topic `prepare`) |
| The same file used again and again (analysis, alignment, pitch several times) | register first | speech analysis is stored once and read afterwards; primitives recompute every time, and their results stay only in that job — not searchable, no samples |

What registering costs: the app then prepares in the background (pitch measurement, search index), using the model channel for a while; **deleting a source cannot be undone and needs the user's confirmation** — so do not register files you only want to compute something on once.
For sources that are already registered, primitives can use their tracks directly (`assetId`); the results still do not enter the library.

## Sound input

`{"assetId": "<track>", "start": s, "end": s}` (asset seconds) or `{"path": "/some/file.wav", "stream": 0, "start": s, "end": s}` (file seconds; videos work too, `stream` = which audio stream).
Without `start` / `end` the whole track is used.

## Commands

| Command | What it does | Results |
|---|---|---|
| `speech.align {"items": [{"text", <sound input>}, ...]}` | Japanese alignment: phoneme, mora and word times. Several lines spoken one after another in the same audio (e.g. the two lines of a cue): `lines` instead of `text` aligns each line as a sentence and also gives each line's span | `speech.alignResults {"jobId"}` |
| `text.analyze {"texts": [...]}` | Japanese reading: phonemes, morae (katakana), words and readings (with the user dictionary) | `text.analyzeResults {"jobId"}` |
| `f0.track <sound input>` | Pitch (FCPE, the same model as the app's pitch search): pitch, confidence and energy every 10 ms + median pitch | `f0.trackResults {"jobId"}` |
| `subtitles.parse {"path", "duration"}` | How the app would read this subtitle file with the current rules (lines, sounds, speakers, OP/ED pairs) | returned directly |
| `subtitles.ruleTest`, `dictionary.check`, `spectrum.get` | How one subtitle line is read, user dictionary validation, the spectrum of a track range (`spectrum.get` takes only an `assetId`, with a required range of at most 30 s) | returned directly |

The first three are jobs: with `--wait` the call waits for the end and prints the per-item results too (`{"job", "results"}`). One failed item in a batch (e.g. text that is only symbols) does not affect the others.
`subtitles.parse` decides OP vs ED from the media duration, so pass `duration` (by default the last cue's end is used and the decision may be wrong).

## When alignment works

The aligner only fits the whole line **into the window you give**; it does not look for where the line is and never reports "no match". The window must hug the actual speech: 0.1–0.2 s of margin on each side.
Tested on 2026-10-29 / 30 with 60 lines: widening the window to 0.5 s on each side moved the start or end by more than 0.3 s for about half of them; shifting the time by 0.5 s or more almost never aligned well.
`edges` (blank time between the window ends and the first / last phoneme) and `longestPhone` in the result are facts, not verdicts: an edge near 0 may mean the speech is cut by the window; an absurdly long phoneme usually means the window is too wide.
Where windows come from: existing line segments, a transcript with word timestamps, or loudness on/offsets. Languages other than Japanese are not supported.
