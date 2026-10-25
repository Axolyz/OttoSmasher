# 准备原素材（“准备”清单 7 项）

## 0. 先整理字幕文件（用你自己的工具）

应用按文件布局认东西：总文件夹下每个**作品**一个文件夹；字幕和媒体放在一起、**文件名相同**（优先 `.srt`，也可以 `.ass`），**UTF-8**。
应用读字幕的规则：全角括号开头的是说话人 `（京子）こんにちは`（一行里所有最外层括号都算）；只有括号的行是音效 `（足音）`；
`♪～` 开头 / `～♪` 结尾的行标出 OP / ED。用 `subtitles.ruleTest` 看应用怎么读一行：
`otto call subtitles.ruleTest '{"text": "（京子）こんにちは"}'`。

真实字幕常见的问题（都在文件上改，不要改所有者的原文件——先留一份 `backup_` 前缀的原件，再写同名的干净版本）：
* 翻译、注音、译注混在正文里；说话人带注音 `（京子(きょうこ)たち）` → 去掉注音。
* 一个条目第一行是音效、第二行起才是台词 `（ドアチャイム）\nウワーッ！` → 应用会把音效当成说话人；拆成两个时间相同的条目。
* OP/ED 标记写法不同（`♪〜` 用的是波浪号 U+301C）→ 统一成 `♪～` / `～♪`，或者导入后自己标 OP/ED。
* 哼歌、歌声写成 `♪（ちなつのハミング）` → 会变成一段只有“♪”的台词，语音分析报 `frontend-failed`（`empty-text`）；改成音效行 `（ちなつのハミング）`，或有歌词就写出歌词。
* 字幕文件名和视频不同（多了前缀、语言后缀）→ 写一份同名的。有机器转写（`.ja.srt`）和正式字幕两份时，优先正式字幕（有说话人）。
* 没有字幕：可以在本机做语音识别生成同名 `.srt`；不做也行，见第 3 节。

## 1. 登记并扫描

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait     # 收编并扫描；不复制文件
otto call sources.list                                     # 所有原素材（work = 作品文件夹名、episode、subtitle_path、counts）
```
改过文件后重新扫描：`otto call sources.rescan --wait`。

## 2. 清单

`otto call sources.prep '{"id": "<sourceId>"}'` 返回七项（各带 `ok`）：

| 项 | 怎么完成 |
|---|---|
| `subtitle`（文本层） | `subtitles.previewMany {"sourceIds": [...]}` → 带 `token` 的交给 `subtitles.importMany {"items": [{"sourceId", "token"}]}`。字幕里的 OP/ED 标记同时导入。 |
| `oped` | 导入时没配成对（`opedErrors`）：`oped.identify {"sourceId"}` 仍会给出建议的 `pairs`（`suggest` = OP / ED）和 `errors`；你判断后用 `oped.add {"sourceId", "kind", "start", "end", "via": "confirm", "refs"}` 确认。没有字幕：见 `combine`。 |
| `separation` | `studio.status`（模型列表；`ok` 为 false 就告诉所有者装 PyMSS Studio）→ `assets.tracks {"sourceId"}` 里 `origin: stream` 的轨 → `separation.submit {"assetId", "model"}` → `separation.results {"jobId"}`。 |
| `defaultVocal` | `tracks.setDefault {"sourceId", "role": "vocal", "assetId": "<人声声部>"}`。不分离（对白清楚、或先凑合用）：`tracks.originalAsVocal {"sourceIds": [...]}` 一次把原混音设好，之后分离了再换。 |
| `defaultSfx` | `tracks.setDefault {"sourceId", "role": "sfx", "assetId": "<伴奏声部>"}` |
| `lineSamples` | 从台词段建采样，见主题 `samples`。 |
| `speech` | `speech.preview {"entry": "source", "ids": [...]}` → `speech.submit` 同样参数 → `speech.results {"jobId"}`。需要文本层和一条人声轨。 |

没有固定顺序，也不强制每项都做（没有字幕本来就是正常的）。

**队列**：分离和语音分析在同一条“模型”队列里，一次一个、按提交顺序。分离一集要十几到几十分钟；
先把要的分析提交了再提交大批分离，或者分批提交。没有插队命令；必要时 `jobs.cancel` 排队中的任务、之后再提交。

## 3. 没有字幕时

手动加台词：`segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}`（原素材秒）。
不加台词也能截取、分离、拉平、导出，以及在原素材音轨上做音高检索（主题 `search`）。
