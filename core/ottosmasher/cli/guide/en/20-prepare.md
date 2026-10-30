# Sources, subtitles and vocals

## Registering

The app recognises things by file layout: under a registered root folder, each first-level subfolder is a **work**; sources are referenced in place, never copied.

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait     # adopt + scan
otto call sources.list                                     # all sources (work, episode, subtitle_path, counts, audio_streams)
otto call sources.rescan --wait                            # rescan after changing or adding files
```
Files outside a root can be registered too: `sources.add {"paths": [...]}`. Once registered they can be separated, given lines and analysed; results stay in the library and can be undone.

## How the app finds and reads subtitles

- **Association**: a `.srt` with **exactly the same name** in the media's folder wins, then `.ass`; then same name plus a suffix (`<video name>.ja.srt`, Japanese suffixes first), then the same in a subtitle subfolder of that folder (`Subs`, `Sub`, `Subtitles`, `字幕` and the like, case-insensitive). Association only; importing is a separate step. UTF-8 is required.
- Subtitle streams **embedded** in video files are **not read**; image subtitles (PGS, VobSub) are pictures, not text.
- **ASS**: Dialogue lines of every style are read, without telling styles apart (the Chinese line of bilingual subtitles also becomes a line); `{…}` override tags and `<…>` are removed, `\N` is a line break, Comment lines are skipped.
- **How each line is read** (the rules are in the settings and can be changed):
  - A full-width bracket holds the speaker: `（京子）こんにちは`. **Every** outermost bracket in a line counts, so a reading inside the spoken text `歳納(としのう)京子` becomes a speaker 「としのう」;
    readings nested inside speaker names are dropped by default: `（京子(きょうこ)たち）` → 「京子たち」.
  - A line that is only a bracket is a sound: `（足音）`. When a cue's first line is a sound and the second is speech, the whole cue is read as "speaker + speech", so the sound becomes a speaker.
  - Lines starting `♪～` / ending `～♪` mark the OP / ED (`〜` is recognised too).
  - A line like `♪（ハミング）` becomes speech that is just "♪"; speech analysis fails with `frontend-failed` (`empty-text`).
- **Line text is the alignment text**: speech analysis aligns the audio to it, so it must be the words actually spoken (Japanese only for now); translations or notes inside make alignment wrong or fail.

To see how the app reads things:

| What | Command |
|---|---|
| One line | `subtitles.ruleTest {"text": "（京子）こんにちは"}` |
| Any subtitle file (no registering, no importing) | `subtitles.parse {"path", "duration"}` (topic `primitives`) |
| The associated subtitles of registered sources, before importing | `subtitles.preview {"sourceId"}` / `subtitles.previewMany {"sourceIds"}`: `segments`, `speakers` (names and counts), `hints` (sounds), `oped`, `problems`, `token` |

Importing: pass the preview's `token` to `subtitles.import` / `subtitles.importMany {"items": [{"sourceId", "token"}]}`; OP/ED markers in the subtitles are imported too.
**Re-importing** replaces only old objects that overlap a new cue in time; old segments that no new cue overlaps stay (by design); delete them with edits. A new cue that touches a **protected** old object (a segment that was edited or has manual phonemes, an edited or hand-added sound hint, a hand-marked OP/ED) is skipped (`status: skip`, `reason: protected` in the preview); with `replace: false` in `options` all old objects are kept, and `force` overrides per cue (`otto describe subtitles.preview`).

## The prep checklist

`sources.prep {"id"}` returns seven status items (each with `ok`). It is a status summary: no fixed order, and no item is mandatory (sources without subtitles are normal):

| item | related commands |
|---|---|
| `subtitle` (text layer) | subtitle preview and import (above); without subtitles `segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}` (source seconds) |
| `oped` | `opedErrors` when pairs did not match on import; `oped.identify {"sourceId"}` suggests `pairs` and lists `errors`; `oped.add {"sourceId", "kind", "start", "end", "via": "confirm", "refs"}` |
| `separation` | see the next section |
| `defaultVocal` / `defaultSfx` | `tracks.setDefault {"sourceId", "role": "vocal" / "sfx", "assetId"}`; `tracks.originalAsVocal {"sourceIds"}` sets the original mix as vocal for many sources at once |
| `lineSamples` | topic `samples` |
| `speech` | `speech.preview {"entry": "source", "ids"}` → `speech.submit` with the same params → `speech.results {"jobId"}` |

In the `speech` item, segments that failed because their text has nothing to pronounce (e.g. just "♪") are counted as unreadable and do not block completion.

## Separation and vocal tracks

- `studio.status`: whether PyMSS Studio is installed and which models it has (if `ok` is false, tell the owner to install PyMSS Studio).
- `separation.submit {"assetId", "model"}` separates the whole track; add `start` / `end` (asset seconds) to separate one part; `ranges: [[start, end], ...]` separates several parts in one job by joining them into one input (Studio works in blocks of about 22 s, so a short part alone still costs a whole block). Results: `separation.results {"jobId"}`, one new track per stem with its time mapping.
  Stems from a partial separation cover only that part; the vocal stem gets the vocal role automatically; **every stem of a partial separation also gets a sample automatically** (whole-track separation does not) — those samples cannot be undone and deleting them needs the owner's confirmation, so a many-range separation creates many samples. An identical request (same track, same range, same model) returns the existing result (`reused`; with several ranges, already separated ones go to `reused` and the rest into the job); a different range, even an overlapping one, makes a new copy. Separating a whole episode takes ten to several tens of minutes (how to wait: ground rule 5 in the overview).
- The default vocal / sfx track must cover the whole source, so a partial stem cannot be the default. But wherever a track can be named, you can pass it:
  `speech.preview` / `speech.submit` with `"assetId"` analyse on that track (only segments inside its range), and `samples.create`, `exports.wav` and the primitives take an `assetId` too.
- A line's phonemes exist once and belong to the source's timeline: whichever track analysed them, the original mix, a full vocal stem and partial stems all read the same ones.
- When a file has several audio streams, only the "analysis track" takes part (topic `concepts`).

## Jobs and the queue

Separation, speech analysis and pitch measurement (including the primitives `speech.align` and `f0.track`) use the "model" channel; scans, `text.analyze` etc. use the "light" channel. How many run at once is set by
`jobs.concurrency_model` (default 1) / `jobs.concurrency_light` (default 2) (read with `settings.list`, change with `edits.apply`, entity `setting`).
While queued, jobs submitted by you or the owner go before the app's automatic preparation jobs, otherwise first come first served; running jobs are never interrupted
and there is no reorder command (if needed, `jobs.cancel` queued jobs and submit them again later). A successful separation deletes its intermediate files; a failed one keeps them.

## A successful analysis is not proof of a good alignment

Alignment only looks inside "the segment's time ± the tolerance in the settings (`analysis.tolerance_before` / `analysis.tolerance_after`, 0.65 s each by default; current values in `settings.list`)", and it always fits the whole line into that window —
when a segment's boundaries are off, phonemes get stretched onto neighbouring sounds and the job still succeeds. When boundaries are off from the actual speech by more than a few tenths of a second, the result is unreliable (numbers in topic `primitives`).
