# 采样：建立、语音分析、标签、查找

## 读台词

```sh
otto call textLayer.list '{"sourceId": "<id>"}'
```
`segments[]` 有 `id`、`text`、`speakers`、`start`/`end`（原素材秒）、`oped`（在 OP/ED 里）、`analysis`、`usedBy`
（已有几个采样读它）。要哪些台词由你自己判断（例如“这句在说游戏”）。
在已有采样里做文字搜索（名称、段的原文与读音）：`samples.list {"text": "..."}`。

## 从选中的段建采样

```sh
otto call samples.plan '{"from": {"kind": "segments", "sourceId": "<id>", "ids": ["<段ID>", ...], "track": "default"}}'
```
计划里有 `token`、`missingDefault`（原素材还缺的默认轨——先设好）、以及 `items[]`（`key`、
`name`（= 台词）、`nature`、`status`）。只有 `status: "pending"` 的能建（`oped`、`no-name`、`out-of-track` 不能）。

```sh
otto call samples.createPlanned '{"from": <同样的 from>, "token": "<token>", "keys": ["<key>", ...], "nature": "speech"}'
```
返回新采样的 `ids`。`overrides` 可以给单条设置名称或本地标签，例如 `{"<key>": {"name": "...", "localTags": ["project:demo"]}}`。标签与采样在同一事务中保存。
其他来源：`kind: "whole"`（整个原素材，`sourceIds`）、`"hints"`（音效提示）、`"selection"`
（`assetId`、`start`、`end`，资产秒），或者直接建一段：`samples.create {"assetId", "start", "end"}`。

## 语音分析

```sh
otto call speech.preview '{"entry": "samples", "ids": ["<sampleId>", ...]}'   # 要分析 / 已是最新 / 无法处理及原因
otto call speech.submit  '{"entry": "samples", "ids": [...]}' --wait
otto call speech.results '{"jobId": "<job>"}'
```
分析属于段，不属于采样；删采样不删分析。已是最新的段会跳过（`rerunFresh: true` 强制重跑）。
分析完成后应用会在后台准备检索索引（事件 `search.coverage`）。

## 打标签

```sh
otto call samples.batchEdit '{"ids": [...], "fields": {"addTags": ["topic:game"]}}'   # 预览，不写入
otto call edits.apply '{"batch": <预览里的 batch>}'
```
`fields` 还能设 `name`、`nature`、`starred`、`rating`、`removeTags`。查看采样的有效标签：`tags.ofSamples {"ids"}`。
全局改名或移除一个标签：`tags.globalPlan` → `edits.apply`。

## 找采样

`samples.ids`（所有匹配的 ID）与 `samples.list`（分页，`limit`/`offset`、`sort`）用同一套条件：
`natures`、`starred`、`text`、`sourceId`、`expr`（主表达式）、`tags: {"facets": [{"facet": "other", "values": ["topic:game"]}], "expr": "..."}`。
例：`otto call samples.ids '{"tags": {"expr": "topic:game AND character:*"}}'`。
只查某个项目时，传 `projectTag: "project:dil"`，匹配采样自身的完整标签。命令行不会自动读取桌面的当前项目。

## 筛选与创建物

列表用 rows/total/offset，允许的 sort 为 created、name、source、duration。`samples.ids` 与列表共用过滤器，createdBySession 可查某个会话创建的采样。不要把 samples.list 的过滤器再包进 scope；search 与 metrics 的范围才用 scope。`samples.metrics {"ids"}` 只读取已有指标，逐个返回 ready/stale/missing，不会启动测量。

已有采样用相关范围和来源判断后复用；新建不可撤销。局部采样读到 partial 分析可能是有意截取，并不必然是错误。


## 已缓存的声学指标

`samples.metrics {"ids": [...]}` 读取现有指标，每个采样带 ready/stale/missing 状态。缺失的测量用 metrics.prepare 计算，尚无测量值的字段保持 null。采样的音高曲线用 measure.f0 读取对应资产范围，列表的 glyphs 显示语音形状。

spectrum.get 返回 data 字节、scale、nyquist 和每行中心频率 frequencies（Hz），可用来解释 log/mel 行。列表 sort 接受 created / name / source / duration；createdBySession 按创建会话筛选，samples.ids 也支持。同名的轨道或采样用 ID 区分。
