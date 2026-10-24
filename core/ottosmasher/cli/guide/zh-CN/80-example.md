# 完整示例

任务：“这里有几集带字幕的动画。把它们准备好，把每句说到游戏的台词都建成语音采样，
打上 `topic:game`，找出符合某个节奏的那些，再把这些采样的画面抠图给我。”

```sh
export OTTO_AGENT_SESSION=game-lines-1
otto status                                             # 应用开着吗？

# 1. 文件（你的工具）：每个视频旁边放同名 UTF-8 .srt；只留日语；说话人写成（名前）；用 subtitles.ruleTest 检查。
# 2. 登记并扫描
otto call roots.add '{"path": "/Users/me/otomad/Show"}' --wait
otto call sources.list > sources.json                    # 挑出新原素材的 ID（work = 文件夹名）

# 3. 清单（主题 prepare）
otto call subtitles.previewMany '{"sourceIds": ["S1", "S2"]}'      # 记下每行的 token
otto call subtitles.importMany '{"items": [{"sourceId": "S1", "token": "T1"}, {"sourceId": "S2", "token": "T2"}]}'
otto call oped.identifyMany '{"sourceIds": ["S1", "S2"]}'
otto call studio.status                                  # 选一个人声模型，例如 "vocal": true 的
otto call assets.tracks '{"sourceId": "S1"}'             # origin 为 "stream" 的那条轨 = A1
otto call separation.submit '{"assetId": "A1", "model": "<模型>"}' --wait
otto call separation.results '{"jobId": "<任务>"}'        # 声部：人声 = V1，其他 = O1
otto call tracks.setDefault '{"sourceId": "S1", "role": "vocal", "assetId": "V1"}'
otto call tracks.setDefault '{"sourceId": "S1", "role": "sfx", "assetId": "O1"}'
otto call sources.prep '{"id": "S1"}'                    # 检查

# 4. 挑台词（你的判断）
otto call textLayer.list '{"sourceId": "S1"}'            # 读 segments[].text，跳过 oped 的
# -> 决定哪些段在说游戏：G = ["seg1", "seg7", ...]

# 5. 新建、分析、打标签
otto call samples.plan '{"from": {"kind": "segments", "sourceId": "S1", "ids": G, "track": "default"}}'
otto call samples.createPlanned '{"from": {...同上...}, "token": "<token>", "keys": [<pending 的 key>], "nature": "speech"}'
otto call speech.submit '{"entry": "samples", "ids": [<新 ID>]}' --wait
otto call samples.batchEdit '{"ids": [<新 ID>], "fields": {"addTags": ["topic:game"]}}'
otto call edits.apply '{"batch": <batch>}'

# 6. 在这个标签里检索
otto call search.speech '{"query": {"strategy": "rank", "length": 2, "blocks": [{"note": [0, 0.5]}, {"note": [1, 1.5]}]}, "scope": {"tags": {"expr": "topic:game"}}}' --wait
otto call results.page '{"id": "<resultId>"}'

# 7. 画面 -> 抠图（在应用之外）
otto call exports.video '{"id": "<sampleId>", "version": "original"}' --wait     # -> video.path
# ffmpeg -i <video.path> -vf fps=4 frames/%03d.png ；对 frames/ 跑你本机的抠图工具；结果存到工作区之外
# 可选：otto call visuals.bind '{"ownerType": "sample", "ownerId": "<sampleId>", "path": "/path/cutout.png"}'

# 8. 向所有者报告：建了什么（ID）、加了什么标签、检索结果、文件。要求撤回时：edits.undoSession。
```
