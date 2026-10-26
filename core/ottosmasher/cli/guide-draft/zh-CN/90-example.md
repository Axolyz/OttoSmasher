# 一个组合示例

下面假设素材尚未登记；已完成的部分可以跳过，分离也可以提前用于外部字幕处理。

任务：“这里有几集带字幕的动画。准备好，把说到游戏的台词都建成语音采样、打上 `topic:game`，在这些采样里找某个节奏，把命中导出给我。”

1. `export OTTO_AGENT_SESSION=game-lines-1`；`otto status`。
2. 清理字幕文件（`prepare` 的字幕说明）→ `roots.add --wait` → `sources.list`。
3. `subtitles.previewMany` → `subtitles.importMany`；OP/ED 没配成对的用 `oped.identify` + `oped.add`。
   人声轨：分离（慢，`prepare` 的队列说明）或先 `tracks.originalAsVocal`。用 `sources.prep` 检查。
4. 写一个脚本（`scripts`）：每集 `textLayer.list` → 关键词粗筛 → 逐条看前后文判断 → 每个原素材一组段 ID。拿不准的列给所有者。
5. 每个原素材 `samples.plan` → `samples.createPlanned`（`nature: speech`）→ 全部新 ID `speech.submit --wait`
   → `samples.batchEdit`（`addTags: ["topic:game"]`）→ `edits.apply`。
6. 检索：
   ```sh
   otto call search.speech '{"query": {"strategy": "rank", "length": 2, "blocks": [{"note": [0, 0.5]}, {"note": [1, 1.5]}]}, "scope": {"tags": {"expr": "topic:game"}}}' --wait
   otto call results.page '{"id": "<resultId>"}'
   ```
7. 导出：`hits.export`（命中）或 `exports.samples` / `exports.video`；路径在结果里。
8. 报告：建了哪些采样（ID）、加了什么标签、拿不准的地方、检索结果与文件路径。要撤回：`edits.undoSession`。
