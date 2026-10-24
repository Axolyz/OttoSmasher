# Worked example

Task: "Here are some anime episodes with subtitles. Prepare them, make speech samples of every line that talks about games,
tag them `topic:game`, find the ones that fit a rhythm, and give me cut-out pictures of those samples."

```sh
export OTTO_AGENT_SESSION=game-lines-1
otto status                                             # app running?

# 1. Files (your tools): same-name UTF-8 .srt next to each video; Japanese only; speakers as （名前）; check with subtitles.ruleTest.
# 2. Register and scan
otto call roots.add '{"path": "/Users/me/otomad/Show"}' --wait
otto call sources.list > sources.json                    # pick the new source ids (work = folder name)

# 3. Checklist (topic prepare)
otto call subtitles.previewMany '{"sourceIds": ["S1", "S2"]}'      # take each row's token
otto call subtitles.importMany '{"items": [{"sourceId": "S1", "token": "T1"}, {"sourceId": "S2", "token": "T2"}]}'
otto call oped.identifyMany '{"sourceIds": ["S1", "S2"]}'
otto call studio.status                                  # choose a vocal model, e.g. one with "vocal": true
otto call assets.tracks '{"sourceId": "S1"}'             # the origin "stream" track = A1
otto call separation.submit '{"assetId": "A1", "model": "<model>"}' --wait
otto call separation.results '{"jobId": "<job>"}'        # stems: vocals = V1, other = O1
otto call tracks.setDefault '{"sourceId": "S1", "role": "vocal", "assetId": "V1"}'
otto call tracks.setDefault '{"sourceId": "S1", "role": "sfx", "assetId": "O1"}'
otto call sources.prep '{"id": "S1"}'                    # check

# 4. Choose lines (your judgement)
otto call textLayer.list '{"sourceId": "S1"}'            # read segments[].text, skip oped ones
# -> decide which segment ids talk about games: G = ["seg1", "seg7", ...]

# 5. Create, analyse, tag
otto call samples.plan '{"from": {"kind": "segments", "sourceId": "S1", "ids": G, "track": "default"}}'
otto call samples.createPlanned '{"from": {...same...}, "token": "<token>", "keys": [<pending keys>], "nature": "speech"}'
otto call speech.submit '{"entry": "samples", "ids": [<new ids>]}' --wait
otto call samples.batchEdit '{"ids": [<new ids>], "fields": {"addTags": ["topic:game"]}}'
otto call edits.apply '{"batch": <batch>}'

# 6. Search inside the tag
otto call search.speech '{"query": {"strategy": "rank", "length": 2, "blocks": [{"note": [0, 0.5]}, {"note": [1, 1.5]}]}, "scope": {"tags": {"expr": "topic:game"}}}' --wait
otto call results.page '{"id": "<resultId>"}'

# 7. Pictures -> cut-outs (outside the app)
otto call exports.video '{"id": "<sampleId>", "version": "original"}' --wait     # -> video.path
# ffmpeg -i <video.path> -vf fps=4 frames/%03d.png ; run your local cut-out tool on frames/ ; save results outside the workspace
# optional: otto call visuals.bind '{"ownerType": "sample", "ownerId": "<sampleId>", "path": "/path/cutout.png"}'

# 8. Report to the owner: what you created (ids), tags added, results, files. Undo if asked: edits.undoSession.
```
