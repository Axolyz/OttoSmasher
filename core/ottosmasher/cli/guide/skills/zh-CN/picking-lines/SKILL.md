---
name: picking-lines
description: "从 OttoSmasher 的几千句台词里按意思挑出需要的，不把它们全读进上下文，再做成带标签的采样。用于“把说到游戏的台词都找出来”这类请求。只挑几句时不需要。"
---

# 挑台词

不要把几千行台词全读进上下文。

1. 先在本地按关键词或规则粗筛出候选。
2. 连同前后文逐条判断。关键词会误中：《兽娘动物园》里「ボス」是角色，「プレーリー」是动物。
3. 拿不准的列给用户。

## 一个完整任务的提纲

“把这几集里说到游戏的台词建成语音采样、打 `topic:game`，在里面找某个节奏，导出命中”：

1. 看 playbook，登记文件。
2. 整集分离，在后台等（skill `separating-audio`）。
3. 洗字幕并导入（skill `cleaning-subtitles`）。
4. 用脚本粗筛，再逐条判断。
5. 用 `samples.plan` 和 `samples.createPlanned` 建采样。
6. 用 `speech.submit` 分析。
7. 用 `samples.batchEdit` 加标签。
8. 用 `search.speech` 检索，用 `hits.export` 导出。
9. 汇报建了什么、拿不准什么、文件在哪。要撤回修改就用 `edits.undoSession`。
