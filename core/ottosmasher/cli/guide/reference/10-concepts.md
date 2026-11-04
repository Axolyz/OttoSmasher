# Concepts

## Objects

| Object | What it is | Read it with |
|---|---|---|
| **Source** (原素材) | One registered video or audio file, never copied. Belongs to a **work** (first-level folder) and has an **episode / identifier**. | `sources.list`, `sources.get`, `sources.prep` |
| **Sound asset / track** | Audio that belongs to a source: the original mix (`origin: stream`), separated stems (`separation`), flattened or reimported versions. Each has **roles** `vocal` / `sfx`; a source has one **default vocal track** and one **default sfx track**. | `assets.listForSource`, `assets.tracks` |
| **Text layer** | Per source: **segments** (what was said: `text`, `speakers`, `start`/`end`), **sfx hints**, **range tags**, **OP/ED** ranges. Comes from subtitles or is typed by hand. | `textLayer.list` |
| **Phonemes** | Speech analysis result of one segment; shared by every vocal track of the source. | `speech.forAsset`, `speech.sample` |
| **Sample** | A usable piece cut from a source: a saved range on one asset (cut one by one, or created in bulk from segments; being a sample does not mean "valuable" — the star and tags record that), with name, **nature** (`speech`, `pitched`, `unpitched`, `unclassified`), tags, star, rating. Samples read the segments their judge interval overlaps. | `samples.list`, `samples.get`, `samples.ids` |
| **Fixed result** | The saved outcome of a rhythm or pitch search. | `results.list`, `results.page` |
| **Job** | Any long or model-based work (scan, separation, analysis, export of video). | `jobs.list`, event `job.updated` |

A file may have several audio streams (the main mix, a commentary, a dub in another language…). Each is registered as an `origin: stream` track, but a source has only one **analysis track**
(`default_audio_stream` in `sources.get` = the `ordinal` of an audio stream in `streams`; `audio_streams` in `sources.list` is how many there are):
subtitle import, setting the original mix as vocal, creating samples from lines and playback all use it. On registration the app picks the stream whose language tag matches the source language in the settings, else the first one —
with no tags, or a commentary tagged with the same language, it picks wrong; to change it see topic `combine`. Changing it does not switch the default vocal track.
The app's convention is one original track per source: line segments and phonemes belong to the source's timeline, and any other track given the vocal role shows the same phonemes.
To use another stream on its own, extract it to a separate file and register that as another source.

## Time

Every time value says which clock it uses: **source seconds** (segments, OP/ED, `source_start`/`source_end` of a sample),
**asset-local seconds** (sample `start`/`end`, separation ranges), **file seconds** (inside a media file). The app converts between
them; you normally pass back the values it gave you for the same object.
An asset's `mapping` (`assets.get`) is a polyline `[[asset seconds, source seconds], …]`: e.g. a partially separated stem `[[0, 100], [10, 110]]` = asset 0–10 s is source 100–110 s.
WAV export results carry the `mapping` of the file itself (file seconds → source seconds); convert times from external tools back to the source with it (topic `export`).

## Tags

Tags are strings, usually `namespace:value`. Facets: `work:` (from the work folder), `type:`, person (`character:` /
`participants:`, from segment speakers), `pitch:`, and **other** (anything else, e.g. `topic:game`). A sample's **effective tags**
= its local tags + tags inherited from its source and from range tags it lies in.
Tag expressions: `NOT` > `AND` > `OR`, parentheses, double quotes, `ns:*` for a whole namespace. Check one with `tags.checkExpr`.

## Changing data

* Most writes go through the **edit channel**: they are atomic and undoable, and objects carry a `version`.
  Commands such as `samples.batchEdit`, `tags.globalPlan`, `works.settingsBatch` return a **preview** with a `batch`;
  you inspect it and pass the batch unchanged to `edits.apply`. If something changed meanwhile, `edits.apply` refuses (re-plan).
* Some commands write directly but are still undoable (`tracks.setDefault`, `visuals.bind`, `subtitles.importMany`, ...).
* A few cannot be undone; they need the user's confirmation (overview, "Commands that cannot be undone").
* Two-step flows with a **token**: `samples.plan` → `samples.createPlanned`, `subtitles.preview(Many)` → `subtitles.import(Many)`.
  Pass the token back; if the data changed you get a `*-stale` error: plan again.

## Jobs and events

Job commands return a job summary (`id`, `status` = queued / running / succeeded / failed / cancelled / interrupted, `progress`,
`error`, `result`). Use `--wait`, or `otto wait job <id>`, or watch `otto events --name job.updated`.
Searches return `{"searchId"}` and end with event `search.finished`; `--wait` handles that too.
Batch jobs keep per-item results (`speech.results`, `flatten.results`); a job where no item succeeded is `failed` (`job-all-items-failed`; per-item reasons are still in the results),
and one success is enough for `succeeded` — so `succeeded` does not mean every item worked; check per-item failures in the results (per-item results, `warnings` or `f0Errors` in `result`, etc.).
List all events with `otto commands --events`.
