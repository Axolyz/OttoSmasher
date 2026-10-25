# Preparing sources (the 7-item "prep" checklist)

## 0. Tidy the subtitle files first (your own tools)

**Goal**: for each episode, one **UTF-8 `.srt`** with **exactly the same name** as the video, each cue holding **only the words actually spoken** (speech analysis currently supports Japanese only) —
speech analysis aligns this text to the audio, and translations, notes or anything else make it fail or misalign. Put the speaker in a leading bracket when you can tell;
otherwise leave it out (fansub subtitles usually have no speakers; that is normal, do not invent them).
The app also reads `.ass`, but write your cleaned result as a same-name `.srt`: with the same name the app prefers `.srt` (also over suffixed names like `<video name>.ja.srt`), so the original `.ass` can stay untouched.

The app recognises things by file layout: one folder per **work** under the root; subtitles next to the media.
How the app reads subtitles: a full-width bracket at the start is the speaker `（京子）こんにちは` (every outermost bracket in a line counts);
a line that is only a bracket is a sound `（足音）`; lines starting `♪～` / ending `～♪` mark the OP / ED. See how the app reads one line with `subtitles.ruleTest`:
`otto call subtitles.ruleTest '{"text": "（京子）こんにちは"}'`.
The app does not read subtitle streams embedded in video files: to use one, extract it to a same-name file first (e.g. `ffmpeg -i ep01.mkv -map 0:s:0 ep01.ass`); image subtitles (PGS, VobSub) come out as pictures and need text recognition first.

Common problems in real subtitles (fix them in the files, never overwrite the owner's original: keep it with a `backup_` prefix, then write the clean same-name version):
* **Fansub bilingual Chinese–Japanese subtitles** (the most common case): when reading `.ass` the app takes the Dialogue lines of **every style**, without telling styles apart, so the Chinese line also becomes a line of speech.
  Keep only the Japanese, by style name (`JP` / `CN` and the like) or by the text itself; when one event stacks two languages with `\N`, keep only the Japanese line. Remove `{\…}` override tags, Comment lines,
  and effect-only lines (titles, notes, translations of on-screen text). Delete the lyric lines of the OP/ED and insert songs, and write `♪～` / `～♪` markers at the lyric timings instead, or mark them with `oped.add` after importing.
* Translations or notes mixed into the text → remove them. Readings inside speaker names `（京子(きょうこ)たち）` are dropped by the app by default;
  but readings in the spoken text `歳納(としのう)京子！` are read as a speaker 「としのう」 (every outermost bracket in a line is a speaker) → remove them from the file.
* A cue whose first line is a sound and the speech starts on the second line `（ドアチャイム）\nウワーッ！` → the app would read the sound as the speaker; split it into two cues with the same timing.
* OP/ED markers that do not pair up (e.g. one start followed by two ends) → check `opedErrors` after import and confirm the suggestions of `oped.identify` (section 2). Both wave dashes `♪〜` and `♪～` are recognised.
* Humming or singing written as `♪（ちなつのハミング）` → becomes a line whose text is just "♪", and speech analysis fails with `frontend-failed` (`empty-text`); make it a sound line `（ちなつのハミング）`, or write out the lyrics.
* Subtitle name differs from the video (extra prefix, language suffix) → write a same-name copy. With both a machine transcript (`.ja.srt`) and proper subtitles, prefer the proper ones (they have speakers).
* **Timing does not match**: when the subtitles come from another release than the video (e.g. TV subtitles on a BD video) they are off by a few seconds overall, or start drifting after where a commercial break used to be.
  Spot-check a few lines at the start, middle and end: cut that audio with `ffmpeg -ss <s> -t <s>` and compare with local speech recognition or the loudness on/offsets. Shift all times for an overall offset, or from the point where it starts.
* No subtitles: you may run speech recognition locally and write a same-name `.srt`; or skip it, see section 3.

**Check before importing**: register first (section 1) if you have not; if already registered and you wrote a new same-name file, run `otto call sources.rescan --wait`; then `otto call subtitles.preview '{"sourceId": "<id>"}'` (read-only, imports nothing):
`speakers` (names and counts; pieces of speech, readings or odd names = brackets left over), `problems` (blocks whose timing cannot be read),
the `text` of `segments` (exactly the text that will be aligned), `hints` (sounds), `oped` (OP/ED pairs). Fix the file and check again.

## 1. Register and scan

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait     # adopt + scan; files are never copied
otto call sources.list                                     # all sources (work = work folder name, episode, subtitle_path, counts)
```
After changing files, rescan: `otto call sources.rescan --wait`.

## 2. The checklist

`otto call sources.prep '{"id": "<sourceId>"}'` returns the seven items (each with `ok`):

| item | how to complete it |
|---|---|
| `subtitle` (text layer) | `subtitles.previewMany {"sourceIds": [...]}` → pass rows with a `token` to `subtitles.importMany {"items": [{"sourceId", "token"}]}`. OP/ED markers in the subtitles are imported too. |
| `oped` | Pairs that did not match on import (`opedErrors`): `oped.identify {"sourceId"}` still suggests `pairs` (`suggest` = OP / ED) and lists `errors`; decide and confirm with `oped.add {"sourceId", "kind", "start", "end", "via": "confirm", "refs"}`. No subtitles: see `combine`. |
| `separation` | `studio.status` (models; if `ok` is false tell the owner to install PyMSS Studio) → the `origin: stream` track from `assets.tracks {"sourceId"}` → `separation.submit {"assetId", "model"}` → `separation.results {"jobId"}`. |
| `defaultVocal` | `tracks.setDefault {"sourceId", "role": "vocal", "assetId": "<vocal stem>"}`. Without separation (clear dialogue, or for now): `tracks.originalAsVocal {"sourceIds": [...]}` sets the original mix for many sources at once; switch after separating. |
| `defaultSfx` | `tracks.setDefault {"sourceId", "role": "sfx", "assetId": "<instrumental stem>"}` |
| `lineSamples` | samples from the line segments, see topic `samples`. |
| `speech` | `speech.preview {"entry": "source", "ids": [...]}` → `speech.submit` with the same params → `speech.results {"jobId"}`. Needs a text layer and a vocal track. |

No fixed order, and no item is mandatory (sources without subtitles are normal).

**Queue**: separation and speech analysis run in one "model" queue, one at a time, first come first served. Separating an episode takes
ten to several tens of minutes; submit the analyses you need before a big batch of separations, or submit in batches. There is no reorder command;
if needed, `jobs.cancel` queued jobs and submit them again later.

## 3. Without subtitles

Add lines by hand: `segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}` (source seconds).
Without lines you can still cut, separate, flatten, export, and run pitch search on source tracks (topic `search`).
