# 与自己的判断和外部工具配合

应用提供资料、声音与计算结果。你可以用自己的检索、文本处理、音频分析工具解释它们，再把需要保留的结论写回应用。
外部工具不需要接管素材库；一次处理也不要求把所有诊断数据存进应用。

## 获取上下文

| 需要的材料 | 入口 |
|---|---|
| 原片路径、音频流与分析音轨 | `sources.get` |
| 已有原声、人声、回导或拉平资产 | `assets.tracks`、`assets.get` |
| 台词及前后文 | `textLayer.list`、`segments.get`；也可直接读原字幕文件 |
| 原混音 | 原媒体路径可用 ffmpeg 只读处理，或使用应用的音频导出 |
| 人声或其他音轨的片段 | `exports.wav`；没有所需声部时可局部分离（主题 `prepare`） |
| 音素、音高和频谱 | `speech.forAsset`、`speech.sample`、`measure.f0`、`spectrum.get` |
| 画面及视频片段 | `visuals.forSample`、`exports.video`、`exports.videoRange` |

音频导出返回可读路径。把该文件交给外部工具；记录导出所用的资产和范围，就能把外部工具得到的时间放回原片（主题 `concepts`）。
需要更长上下文时，直接选择更大的导出或分离范围；不必为观察一段声音先建立采样。

## 把结果写到哪里

| 你要保留的结果 | 写回入口 |
|---|---|
| 一批筛选出的采样类别 | `samples.batchEdit` 的 `addTags` / `removeTags` → `edits.apply` |
| 选中的台词采样 | `samples.plan` → `samples.createPlanned` |
| 任意音轨上的截取范围 | `samples.create`（资产局部秒） |
| 新台词 | `segments.checkAdd` → `segments.add`（原素材秒） |
| 已有台词的文本或边界 | `segments.get` 取版本 → `edits.apply` 的 `segment` 编辑 |
| OP / ED 区间 | `oped.add`（原素材秒） |
| 分析用的原音频流 | `sources.get` 取版本 → `edits.apply` 的 `source.default_audio_stream` |
| 人声 / 音效轨的选择 | `tracks.setDefault`、`tracks.setRole` |
| 外部加工后的音频 | `reimport.preview` → `reimport.commit` |
| 采样画面 | `visuals.bind` |

这些资料修改可撤销。批量编辑返回的 `batch` 是待应用的修改，token 是对应预览的凭据；完整参数查 `describe`。
修改后可读回相关对象继续判断，或用主题 `undo` 的入口撤回。

## 几种组合方式

- 字幕已经合适：导入文本层，结合前后文筛台词，再对选中的段做分析或建采样。
- 处理字幕时需要看清人声：先登记原片、取得已有或新分离的人声，导出相关区间给外部分析工具；字幕处理完成后再导入。
- 只有某个声音值得用：直接局部分离、查看或导出，决定范围后建采样或拉平；无需先补齐整集字幕。
- 想比较乐器素材：读取音高、导出片段，在外部比较频谱或其他特征，把采用的候选打标签，交给所有者试听选择。

这些组合没有固定先后关系。使用已有结果，从当前任务需要的地方接上即可。
