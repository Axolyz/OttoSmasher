# Concepts

## Objects

| Object | What it is | Read it with |
|---|---|---|
| **Source** (原素材) | One registered video or audio file, never copied. Belongs to a **work** (first-level folder) and has an **episode / identifier**. | `sources.list`, `sources.get`, `sources.prep` |
| **Sound asset / track** | Audio that belongs to a source: the original mix (`origin: stream`), separated stems (`separation`), flattened or reimported versions. Each has **roles** `vocal` / `sfx`; a source has one **default vocal track** and one **default sfx track**. | `assets.listForSource`, `assets.tracks` |
| **Text layer** | Per source: **segments** (what was said: `text`, `speakers`, `start`/`end`), **sfx hints**, **range tags**, **OP/ED** ranges. Comes from subtitles or is typed by hand. | `textLayer.list` |
| **Phonemes** | Speech analysis result of one segment; shared by every vocal track of the source. | `speech.forAsset`, `speech.sample` |
| **Sample** | A saved range on one asset, with name, **nature** (`speech`, `pitched`, `unpitched`, `unclassified`), tags, star, rating. Samples read the segments their judge interval overlaps. | `samples.list`, `samples.get`, `samples.ids` |
| **Fixed result** | The saved outcome of a rhythm or pitch search. | `results.list`, `results.page` |
| **Job** | Any long or model-based work (scan, separation, analysis, export of video). | `jobs.list`, event `job.updated` |

## Time

Every time value says which clock it uses: **source seconds** (segments, OP/ED, `source_start`/`source_end` of a sample),
**asset-local seconds** (sample `start`/`end`, separation ranges), **file seconds** (inside a media file). The app converts between
them; you normally pass back the values it gave you for the same object.

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
* A few cannot be undone; they need the owner's confirmation (overview rule 6).
* Two-step flows with a **token**: `samples.plan` → `samples.createPlanned`, `subtitles.preview(Many)` → `subtitles.import(Many)`.
  Pass the token back; if the data changed you get a `*-stale` error: plan again.

## Jobs and events

Job commands return a job summary (`id`, `status` = queued / running / succeeded / failed / cancelled / interrupted, `progress`,
`error`, `result`). Use `--wait`, or `otto wait job <id>`, or watch `otto events --name job.updated`.
Searches return `{"searchId"}` and end with event `search.finished`; `--wait` handles that too.
Batch jobs keep per-item results (`speech.results`, `flatten.results`); one failed item does not fail the batch.
List all events with `otto commands --events`.
