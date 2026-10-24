# Combining the app with your own tools

The app is the library and the analysis engine; you bring judgement and other tools. Patterns:

## Judge content, then write it back as tags

Read text (`textLayer.list`; the segments a sample reads: `speech.sample`), decide with your own
reasoning, then tag (`samples.batchEdit` → `edits.apply`) or create samples from the segments you picked (topic `samples`).
Tags are the hand-off point: later searches and exports filter by them.

## Pictures of samples → image tools → back

1. Get the samples: `otto call samples.ids '{"tags": {"expr": "topic:game"}}'`.
2. For each, either export a clip (`exports.video {"id", "version": "original"} --wait`) or read where its picture comes from:
   `visuals.forSample {"id"}` → `binding.path` (the media file), `binding.mode`, `binding.offset`, and the sample's `start`/`end`
   with `mapping` (asset time → source time). Extract frames with your own ffmpeg from the clip or the original file.
3. Process them with your tools (for example a local cut-out model). Write results **outside** the workspace.
4. Optionally bind a result back as the sample's picture: `visuals.bind {"ownerType": "sample", "ownerId", "path"}`
   (images become still pictures, gifs loops, videos synced). `path: null` removes the binding. Undoable.

## Audio processed elsewhere → back into the library

`reimport.preview {"assetId", "start", "path"}` → `reimport.commit` brings a processed file back at a position on a track
(copied into the library, a new whole sample is created). Separation and flattening are built in (`separation.submit`, `flatten.*`).

## Subtitles from elsewhere

Speech recognition, translation removal, speaker guessing: do it on the files, keep the same file name, then
`subtitles.previewMany` → `subtitles.importMany`. Re-importing shows what is new / unchanged / replaced; hand-edited segments are protected.

## Keep the owner in the loop

Large or ambiguous decisions (which lines count as "about games", which model to separate with) are worth a short summary to the
owner before you write. Your changes appear in the app as "data updated" and can be undone per session.
