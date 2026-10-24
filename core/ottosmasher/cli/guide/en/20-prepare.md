# Prepare sources (the 7-item checklist)

## 0. Files first (your own tools)

The app recognises things by layout, so tidy the files before registering:

* One folder per **work** under a root folder; any sub-folders inside a work.
* Subtitles next to the media with the **same file name** (`.srt` preferred, or `.ass`), **UTF-8**.
* Each line contains only the Japanese that is actually spoken. Remove translations, furigana, translator notes.
* Speakers go in a leading full-width bracket: `（京子）こんにちは`. All outermost brackets on a line count as speakers,
  so leave no other brackets in the text. A line with only brackets is a sound effect: `（足音）`.
* A line starting with `♪～` / ending with `～♪` marks OP / ED (skipped later).
* Pictures with the same name as an audio file (`.png`, `.jpg`, `.gif`, video) are bound as its picture automatically.
* Check a cleaned line against the app's rules: `otto call subtitles.ruleTest '{"text": "（京子）こんにちは"}'`.
* Do not delete or move the owner's media; show the owner your plan first if you change many files.

## 1. Register and scan

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait     # adopts and scans; files are not copied
otto call sources.list                                     # every source with counts
otto call works.list
```
Rescan after you changed files: `otto call sources.rescan --wait`. Files added later are picked up the same way.

## 2. The checklist

`otto call sources.prep '{"id": "<sourceId>"}'` shows the seven items for one source (each with `ok`):

| Item | How to complete it |
|---|---|
| `subtitle` (text layer) | `subtitles.previewMany {"sourceIds": [...]}` → for every row with a `token`, `subtitles.importMany {"items": [{"sourceId", "token"}]}`. Rows with `skipped` have no subtitle; rows with `error` need fixing. One source: `subtitles.importDefault {"sourceId"}`. |
| `oped` | `oped.identifyMany {"sourceIds": [...]}` (from the ♪ lines). Manual: `oped.add`. |
| `separation` | `studio.status` (models; needs PyMSS Studio installed — if `ok` is false, tell the owner). Then `assets.tracks {"sourceId"}` → the `origin: stream` track id → `separation.submit {"assetId", "model"} --wait` → `separation.results {"jobId"}` lists the stems. Identical input + model returns `reused` without a job. |
| `defaultVocal` | `tracks.setDefault {"sourceId", "role": "vocal", "assetId": "<vocal stem>"}`. Already-clean voice (game lines): `tracks.originalAsVocal {"sourceIds": [...]}` sets the original mix for many sources at once. |
| `defaultSfx` | `tracks.setDefault {"sourceId", "role": "sfx", "assetId": "<instrumental / sfx stem>"}` |
| `lineSamples` | Samples from segments, see topic `samples`. |
| `speech` | `speech.preview {"entry": "source", "ids": [...]}` → `speech.submit` (same params) `--wait` → `speech.results {"jobId"}`. Needs the text layer and a vocal track that covers each segment. |

The items have no fixed order and are not mandatory, but analysis is better on a separated vocal track, and the subtitles and OP/ED
should be in before creating samples. Separation is slow (minutes per episode, one job at a time): submit all, then wait.

## 3. Without subtitles

Add lines by hand: `segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}` (source seconds). If you produce
text with your own speech recognition, keep it local, write it as a same-name `.srt`, and import it as above.
