# 用你自己的判断和工具，再写回应用

应用是素材库和分析引擎；判断和其他工具由你提供：你读资料、自己判断或处理，需要留下的结论写回应用。

## 写回的地方

| 你的结论 | 写回 |
|---|---|
| 这些采样属于某一类（话题、角色、语气……） | `samples.batchEdit {"ids", "fields": {"addTags": [...]}}` → `edits.apply` |
| 这句台词该建成采样 | `samples.plan` → `samples.createPlanned`（主题 `samples`） |
| OP / ED 在这里 | `oped.add {"sourceId", "kind": "OP" / "ED", "start", "end"}`（原素材秒） |
| 这里说了一句话（字幕没有） | `segments.add`；改已有的段：`segments.get` 拿版本 → `edits.apply`（实体 `segment`） |
| 原素材该用哪条音频流（分析音轨） | `sources.get` 拿 `version` → `edits.apply`（实体 `source`，字段 `default_audio_stream`） |
| 用哪条音轨当人声 / 音效 | `tracks.setDefault`、`tracks.setRole` |
| 处理过的音频要放回素材库 | `reimport.preview {"assetId", "start", "path"}` → `reimport.commit` |
| 一张图或一段视频当采样的画面 | `visuals.bind {"ownerType": "sample", "ownerId", "path"}` |

都记在你的会话下。修改（标签、段、OP/ED、默认轨、画面）可以撤销；新建的采样（`samples.plan` / `samples.create`）、回导的音轨撤销不了，只能删除（要用户确认）。

回导时可给 `reimport.commit` 传 `localTags`（如 `["project:dil"]`），随新采样一起保存。命令行不读取桌面的当前项目。

## 拿到原始材料

* 文本：`textLayer.list {"sourceId"}`（段、音效提示、OP/ED）；字幕文件本身。
* 音频：原素材的媒体文件（`sources.list` 的 `path`，可以直接用 ffmpeg 读，**只读**）；或导出：`exports.wav`、`exports.range`（WAV，结果带文件秒 → 原片秒的 `mapping`）、`exports.samples`。
* 画面：`visuals.forSample {"id"}`（画面来自哪个文件、哪一段）；`exports.video`、`exports.videoRange`（视频片段）。
* 分析：`speech.sample`（采样读到的段与音素）、`measure.f0`（音高曲线）。
* 听不到声音时，用你环境里的音频分析工具（例如 audio-mcp 的频谱图、响度、带时间的转写）看导出的 WAV（主题 `notes`）。

## 让用户知情

大的或模棱两可的决定（哪些台词算“和游戏相关”、用哪个模型分离、要改多少文件）在写入前给用户一个简短的总结。
你的修改在应用里显示为“资料已更新”，在「操作历史」里写着你的会话，可以整批撤回。

## 继续查方法

精度选择见 `otto guide workflow`，音频接入见 otto guide audio。核对声音时结合原文、完整句子和相邻对白，转写用于检查内容和粗定位。选台词可读 picking-lines，挑单音及拉平见 `otto guide flatten`。
