# 检索：节奏（语音）与音高

两种检索都在一个**范围**里进行（和 `samples.ids` 同一套条件），结果存成**固定结果**，之后资料变化也不会改它。

节奏检索以**采样**为单位。想搜一整季的节奏，先从台词段批量建采样。要在**原料**里找一句台词在哪一集、哪个时间点，用 `textLayer.search`：
搜文本层的段和音效提示（规范化原文子串，或读音子串，和采样的“原句”筛选同一套规则），结果是原片上的位置（原片秒），不是采样、不存结果；
`sourceIds` 缺省 = 全部原素材；`notImported` = 关联了字幕但文本层是空的（搜不到）；`readingPending` = 读音还没算好的段数（这些段只按原文匹配）。

## 检查和补齐覆盖

用实际检索的同一组范围条件调用 `search.coverage`。节奏用 `mode: "speech"`，采样音高用 `"pitch"`，原素材音轨用 `"pitchSources"`。覆盖结果里有 `total`（范围总数）、`ready`（已就绪）、`stale`（待准备）和 `noAnalysis`（缺少有效语音分析）。

- 节奏模式的 `noAnalysis` 包括没有可用分析，以及已有分析但无法生成音块索引的采样。用 `speech.preview` 检查相关采样，用 `speech.submit` 补能补的语音分析。比如缺台词段或有音素重叠时，按实际原因处理。
- 节奏模式的 `stale` 表示分析已有、索引缺失或过期。后台若正在准备，可以等它完成。也可以用同一范围调用 `search.prepare` 并加 `--wait`。这一步只建索引。音高模式的 `search.prepare` 则补测基频（F0）。

准备完成后再查覆盖。检索只处理当时已就绪的部分。报告结果时可用结果统计里的 `searched` 和 `total` 给出实际检索数和范围总数，并说明剩余缺口。固定结果记录的是执行当时的覆盖，补齐后要重新检索。

## 语音 / 节奏检索

```sh
otto call search.speech '{"query": {"blocks": [{"vowel": "a"}, {"vowel": "i"}]}, "scope": {"tags": {"expr": "topic:game"}}}' --wait
```
查询是一串**音块**（一个音块 ≈ 一个音节核），每块可选条件：`vowel`（a/e/i/o/u）、`consonants`、
`pitch`（0–11）与 `octave`、`duration`、`trend`（up/down）、`relPitch`、`loudnessMin`、`character` 等。
`strategy`：`free`（默认：只看顺序）、`strict` / `rank`（节奏：每块都要 `note: [起拍, 止拍]`，按顺序、
不重叠；相邻起拍间距大于 2 × `tolerance`；`tolerance` 默认 0.1 拍）。`edge`、`scope`、`speedRange`、
`maxGap`、`length` 进一步限定——`otto describe search.speech` 列出全部。
写错的查询报 `speech-query-invalid`，指出字段和第几块。

## 音高检索

```sh
otto call search.pitchCheck '{"text": "0.3 C4\n0.3 E4"}'       # 校验 / 转换文本格式（每行“秒数 音高”）
otto call search.pitch '{"blocks": [{"seconds": 0.3, "low": "C4"}, {"seconds": 0.3, "low": "E4"}], "mode": "samples"}' --wait
```
`mode: "samples"` 在已保存的采样里找；`"sources"` 在已测的原素材音轨上找。`params` 设音分容差（50）、
覆盖率（0.8）、`ignoreOctave`、`elastic` 时长弹性等。结果是完整的（不截断），属于近似检索。

## 读结果

`--wait` 打印带 `resultId` 的最终状态。然后：
```sh
otto call results.page '{"id": "<resultId>", "offset": 0, "limit": 100}'
```
每行有 `sampleId`（原素材模式是 `assetId`）、`state`（ok / deleted / changed / stale）和带区间的 `hits[]`。
命中可以渲染或导出：`hits.export`、`hits.video`、`hits.render`（用它的证据所选的卡拍方案），也可以用
`samples.create`（`via: "hit"`）存成采样。不再需要的结果：`results.close`。
