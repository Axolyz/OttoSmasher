# 用你自己的判断和工具，再写回应用

应用是素材库和分析引擎；判断和其他工具由你提供。做法都一样：**读资料 → 自己判断或处理 → 把结论写回应用**。

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

这些都可撤销，并记在你的会话下。

## 拿到原始材料

* 文本：`textLayer.list {"sourceId"}`（段、音效提示、OP/ED）；字幕文件本身。
* 音频：原素材的媒体文件（`sources.list` 的 `path`，可以直接用 ffmpeg 读，**只读**）；或导出：`exports.wav`、`exports.range`（WAV，结果带文件秒 → 原片秒的 `mapping`）、`exports.samples`。
* 画面：`visuals.forSample {"id"}`（画面来自哪个文件、哪一段）；`exports.video`、`exports.videoRange`（视频片段）。
* 分析：`speech.sample`（采样读到的段与音素）、`measure.f0`（音高曲线）。
* 听不到声音时，用你环境里的音频分析工具（例如 audio-mcp 的频谱图、响度、带时间的转写）看导出的 WAV（主题 `notes`）。

## 例子

* **筛台词**：几千行台词不要全读进上下文。先在本地按关键词或规则粗筛出候选，再逐条读候选和前后文判断。
  关键词会误中（例如《兽娘动物园》里的「ボス」是角色、「プレーリー」是动物），判断要看语义。
* **没有字幕时找 OP / ED**：同一部作品每集的 OP / ED 是同一首歌。用 ffmpeg 抽出几集开头几分钟和结尾几分钟的音频，
  互相比对，最长的一段近乎相同的音频就是 OP（或 ED）；再 `oped.add`。对不上的集（换了版本、没有 OP）如实告诉所有者，不要硬标。
* **字幕写法乱**：照主题 `prepare` 第 0 节清理文件，再导入。
* **应用的分析结果看着不对**：先找原因（字幕错字、人声轨不对、段的边界不准），改正后重新分析；拿不准就导出那段音频自己听。

## 让所有者知情

大的或模棱两可的决定（哪些台词算“和游戏相关”、用哪个模型分离、要改多少文件）在写入前给所有者一个简短的总结。
你的修改在应用里显示为“资料已更新”，在「操作历史」里写着你的会话，可以整批撤回。
