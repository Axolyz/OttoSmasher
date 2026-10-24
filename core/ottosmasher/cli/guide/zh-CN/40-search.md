# 检索：节奏（语音）与音高

两种检索都在一个**范围**里进行（和 `samples.ids` 同一套条件），结果存成**固定结果**，之后资料变化也不会改它。
先看准备情况：`search.coverage`（索引已建 / 音高已测）；`search.prepare` 把缺的部分排进任务。

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
