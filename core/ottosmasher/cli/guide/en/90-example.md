# Worked example

Task: "Here are some anime episodes with subtitles. Prepare them, turn every line that talks about games into a speech sample tagged `topic:game`, search those samples for a rhythm, and export the hits for me."

1. `export OTTO_AGENT_SESSION=game-lines-1`; `otto status`.
2. Clean the subtitle files (`prepare` section 0) → `roots.add --wait` → `sources.list`.
3. `subtitles.previewMany` → `subtitles.importMany`; OP/ED pairs that did not match: `oped.identify` + `oped.add`.
   Vocal track: separate (slow, see the queue note in `prepare`) or `tracks.originalAsVocal` for now. Check with `sources.prep`.
4. Write a script (`scripts`): `textLayer.list` per episode → keyword prefilter → judge each candidate with its context → segment ids per source. List the doubtful ones for the owner.
5. Per source `samples.plan` → `samples.createPlanned` (`nature: speech`) → all new ids `speech.submit --wait`
   → `samples.batchEdit` (`addTags: ["topic:game"]`) → `edits.apply`.
6. Search:
   ```sh
   otto call search.speech '{"query": {"strategy": "rank", "length": 2, "blocks": [{"note": [0, 0.5]}, {"note": [1, 1.5]}]}, "scope": {"tags": {"expr": "topic:game"}}}' --wait
   otto call results.page '{"id": "<resultId>"}'
   ```
7. Export: `hits.export` (hits) or `exports.samples` / `exports.video`; the paths are in the result.
8. Report: which samples you created (ids), the tags you added, what you were unsure about, search results and file paths. To undo: `edits.undoSession`.
