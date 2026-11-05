# Sources, subtitles and vocals

## Registering

The app recognises things by file layout: under a registered root folder, each first-level subfolder is a **work**; sources are referenced in place, never copied.

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait     # adopt + scan
otto call sources.list                                     # all sources (work, episode, subtitle_path, counts, audio_streams)
otto call sources.rescan --wait                            # rescan after changing or adding files
```
A rescan registers new files and refreshes subtitle links of registered sources: a source with no link or a missing subtitle file gets the file found by the rules below, and a same-name `.ass` gives way to a new same-name `.srt`. It links but does not import. Sources whose `subtitle_path` was set or cleared with `edits.apply` or in the app keep that choice; the scan event reports the count in `subtitlesLinked`.
Files outside a root can be registered too: `sources.add {"paths": [...]}`. Once registered they can be separated, given lines and analysed; results stay in the library and can be undone.

## How the app finds and reads subtitles

- **Association**: a `.srt` with **exactly the same name** in the media's folder wins, then `.ass`; then same name plus a suffix (`<video name>.ja.srt`, Japanese suffixes first), then the same in a subtitle subfolder of that folder (`Subs`, `Sub`, `Subtitles`, `字幕` and the like, case-insensitive). Association only; importing is a separate step. UTF-8 is required.
- Subtitle streams **embedded** in video files are **not read**; image subtitles (PGS, VobSub) are pictures, not text.
- **ASS**: Dialogue lines of every style are read, without telling styles apart (the Chinese line of bilingual subtitles also becomes a line); `{…}` override tags and `<…>` are removed, `\N` is a line break, Comment lines are skipped.
- **How each line is read** (the rules are in the settings and can be changed; line by line, recording less rather than recording wrong):
  - A bracket at the **start** of a speech line is that line's speaker: `（京子）こんにちは`; `（虹夏、リョウ）せーの` = several people at once. Readings nested inside names are dropped by default: `（京子(きょうこ)たち）` → 「京子たち」.
  - Brackets in the middle of speech are never names; they are only removed from the text: `歳納(としのう)京子` → text 「歳納京子」.
  - A line that is only a bracket is a sound: `（足音）` (line breaks inside brackets do not count). **But when the next line is unlabelled speech, it is read as neither sound nor speaker** (it may be a name written on its own line).
    A cue with both a sound line and speech gives one of each: a sound hint and a segment.
  - An unlabelled speech line = speaker unknown; it **never inherits the previous line**. A cue records speakers only when **every speech line is labelled** (different names = several people);
    if one line is unlabelled nothing is recorded and the segment's `speakersWithheld` is true.
  - So a segment's `speakers` are the speakers that could be read **for certain**; empty = unknown, not "nobody". The full labels are in the segment's `raw` (the original text of that cue; kept through edits and splits, joined from the parts after a merge).
    To get speakers on every cue, first clean the subtitles into "one person per cue, every speech line labelled".
  - Lines starting `♪～` / ending `～♪` mark the OP / ED (`〜` is recognised too).
  - Music inside an episode (an insert song, a karaoke scene) uses the same marks, so a correct subtitle file can report OP/ED errors. Only pairs without errors import on their own; `opedErrors` and `problems` show the rest (skill `preparing-subtitles`).
  - A cue longer than 120 s cannot be a segment or sound hint: `subtitles.parse` lists it in `problems` and the preview marks it `invalid` / `too-long`. It is left out on import; split it into consecutive cues if you need it.
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
A segment whose time and text did not change is `unchanged` and **its speakers and original text are not updated**; to start over from a new subtitle file, first delete the imported markers with `subtitles.clear {"sourceIds"}`
(`subtitles.clearPlan` shows what would go; typed segments stay, protected ones stay unless `protected: true`; one undoable edit), then import.

## The prep checklist

`sources.prep {"id"}` returns seven status items (each with `ok`). It is a status summary: no fixed order, and no item is mandatory (sources without subtitles are normal):

| item | related commands |
|---|---|
| `subtitle` (text layer) | subtitle preview and import (above); without subtitles `segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}` (source seconds) |
| `oped` | `opedErrors` when pairs did not match on import; `oped.identify {"sourceId"}` returns `pairs` and `errors`, and writes the pairs that overlap nothing when there are no errors; `oped.add {"sourceId", "kind", "start", "end", "via": "confirm", "refs"}` |
| `separation` | see the next section |
| `defaultVocal` / `defaultSfx` | `tracks.setDefault {"sourceId", "role": "vocal" / "sfx", "assetId"}`; `tracks.originalAsVocal {"sourceIds"}` sets the original mix as vocal for many sources at once; `tracks.separatedVocals {"sourceIds"}` lists existing vocal stems and `tracks.defaultFromSeparation {"sourceIds", "model", "stem"}` makes one the default vocal track in one go |
| `lineSamples` | topic `samples` |
| `speech` | `speech.preview {"entry": "source", "ids"}` → `speech.submit` with the same params → `speech.results {"jobId"}` |

In the `speech` item, segments that failed because their text has nothing to pronounce (e.g. just "♪") are counted as unreadable and do not block completion.

## Separation and vocal tracks

- Before separating, look for what exists: `tracks.separatedVocals {"sourceIds"}` lists finished vocal stems, including sources that have a stem but no default vocal track yet.
- Time cost, measured with HyperACE v2 on Apple silicon (other machines and models differ): each job takes about 8 s to start, then about 0.35 s per second of audio, so a 24-minute episode takes about 9 minutes. With one job per line, a few dozen lines take about as long as the whole episode; 10 parts of 6 s took 31 s with `ranges` against about 100 s as separate jobs. The same line separated alone, joined with others or inside the surrounding minute differs by about −9 dB, so use a longer range or the whole episode for demanding lines.
- `studio.status`: whether PyMSS Studio is installed and which models it has (if `ok` is false, tell the user to install PyMSS Studio).
- `separation.submit {"assetId", "model"}` separates the whole track; add `start` / `end` (asset seconds) to separate one part; `ranges: [[start, end], ...]` separates several parts in one job by joining them into one input (Studio works in blocks of about 22 s, so a short part alone still costs a whole block). Results: `separation.results {"jobId"}`, one new track per stem with its time mapping.
  Stems from a partial separation cover only that part; the vocal stem gets the vocal role automatically; **every stem of a partial separation also gets a sample automatically** (whole-track separation does not) — those samples cannot be undone and deleting them needs the user's confirmation, so a many-range separation creates many samples. Every request really separates again and makes new tracks; existing results are never reused. Check `assets.tracks` before re-running, and remove extras with `assets.delete` (tracks with samples on them cannot be deleted). Separating a whole episode takes ten to several tens of minutes (how to wait: overview, "Long jobs").
- The default vocal / sfx track must cover the whole source, so a partial stem cannot be the default. But wherever a track can be named, you can pass it:
  `speech.preview` / `speech.submit` with `"assetId"` analyse on that track (only segments inside its range), and `samples.create`, `exports.wav` and the primitives take an `assetId` too.
- A line's phonemes exist once and belong to the source's timeline: whichever track analysed them, the original mix, a full vocal stem and partial stems all read the same ones.
- When a file has several audio streams, only the "analysis track" takes part (topic `concepts`).

## Jobs and the queue

Separation, speech analysis and pitch measurement (including the primitives `speech.align` and `f0.track`) use the "model" channel; scans, `text.analyze` etc. use the "light" channel. How many run at once is set by
`jobs.concurrency_model` (default 1) / `jobs.concurrency_light` (default 2) (read with `settings.list`, change with `edits.apply`, entity `setting`).
While queued, jobs submitted by you or the user go before the app's automatic preparation jobs, otherwise first come first served; `jobs.promote` moves a queued job to the front of its channel
(the most recently promoted first); running jobs are never interrupted. A successful separation deletes its intermediate files; a failed one keeps them.

## A successful analysis is not proof of a good alignment

Alignment only looks inside "the segment's time ± the tolerance in the settings (`analysis.tolerance_before` / `analysis.tolerance_after`, 0.2 s each by default; current values in `settings.list`)", and it always fits the whole line into that window —
when a segment's boundaries are off, phonemes get stretched onto neighbouring sounds and the job still succeeds. When boundaries are off from the actual speech by more than a few tenths of a second, the result is unreliable (numbers in topic `primitives`).
