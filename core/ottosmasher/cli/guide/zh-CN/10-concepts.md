# 概念

## 对象

| 对象 | 是什么 | 用什么读 |
|---|---|---|
| **原素材**（source） | 登记的一个视频或音频文件，从不复制。属于一个**作品**（第一层文件夹），有一个**素材标识**（集数 / 编号）。 | `sources.list`、`sources.get`、`sources.prep` |
| **声音资产 / 音轨** | 属于原素材的音频：原混音（`origin: stream`）、分离出的声部（`separation`）、拉平或回导的版本。每条有**角色** `vocal` / `sfx`；原素材有一条**默认人声轨**和一条**默认音效轨**。 | `assets.listForSource`、`assets.tracks` |
| **文本层** | 每个原素材的：**段**（说了什么：`text`、`speakers`、`start`/`end`）、**音效提示**、**区段标签**、**OP/ED** 区间。来自字幕或手动输入。 | `textLayer.list` |
| **音素** | 一段的语音分析结果；这个原素材所有含人声的轨共用。 | `speech.forAsset`、`speech.sample` |
| **采样** | 保存在某条资产上的一段区间，有名称、**性质**（`speech` 语音、`pitched` 调谐单音、`unpitched` 非调谐单音、`unclassified` 未分类）、标签、星标、评分。采样读取它的判定区间交叠到的段。 | `samples.list`、`samples.get`、`samples.ids` |
| **固定结果** | 一次节奏或音高检索保存下来的结果。 | `results.list`、`results.page` |
| **任务** | 任何耗时或调用模型的工作（扫描、分离、分析、导出视频）。 | `jobs.list`、事件 `job.updated` |

一个文件可能有多条音频流（正片、解说、别的语言的配音……）。每条都登记成一条 `origin: stream` 的音轨，但原素材只有一条**分析音轨**
（`sources.get` 的 `default_audio_stream` = `streams` 里音频流的 `ordinal`；`sources.list` 的 `audio_streams` 是条数）：
导入字幕、把原混音设为人声、从台词段建采样、播放都用它。登记时按设置里的素材语言找语言标记相同的那条，找不到就取第 1 条——
没有标记、或解说也标成同一种语言时会选错，改它见主题 `combine`；改了不会自动换默认人声轨。
应用的约定是一个原素材只有一条原始音轨：台词段和音素属于原素材的时间线，别的音轨设成人声也会显示同一份音素。
其他音轨要单独用，就抽成单独的文件，作为另一个原素材登记。

## 时间

每个时间值都说明它属于哪个时钟：**原素材秒**（段、OP/ED、采样的 `source_start`/`source_end`）、
**资产局部秒**（采样的 `start`/`end`、分离区间）、**文件秒**（媒体文件内部）。应用负责换算；
通常把应用给你的值原样交回给同一个对象就行。

## 标签

标签是字符串，一般写成 `命名空间:值`。分面：`work:`（来自作品文件夹）、`type:`、人物（`character:` /
`participants:`，来自段的说话人）、`pitch:`，以及**其他**（别的都算，例如 `topic:game`）。采样的**有效标签**
= 本地标签 + 从原素材和所在区段标签继承来的标签。
标签表达式：`NOT` > `AND` > `OR`，可用括号、双引号，`ns:*` 匹配整个命名空间。用 `tags.checkExpr` 检查。

## 修改资料

* 大多数写入走**编辑通道**：原子、可撤销，对象带 `version`。
  `samples.batchEdit`、`tags.globalPlan`、`works.settingsBatch` 这类命令返回带 `batch` 的**预览**；
  你看过之后把 batch 原样交给 `edits.apply`。期间资料变了，`edits.apply` 会拒绝（重新规划）。
* 有些命令直接写入，但同样可撤销（`tracks.setDefault`、`visuals.bind`、`subtitles.importMany` 等）。
* 少数撤销不了，要所有者确认（总览第 6 条）。
* 带 **token** 的两步流程：`samples.plan` → `samples.createPlanned`，`subtitles.preview(Many)` → `subtitles.import(Many)`。
  把 token 交回去；资料变了会报 `*-stale` 错误：重新规划。

## 任务与事件

任务命令返回任务摘要（`id`、`status` = queued / running / succeeded / failed / cancelled / interrupted、`progress`、
`error`、`result`）。用 `--wait`，或 `otto wait job <id>`，或 `otto events --name job.updated` 观察。
检索返回 `{"searchId"}`，以事件 `search.finished` 结束；`--wait` 同样能处理。
批量任务保留逐条结果（`speech.results`、`flatten.results`）；单条失败不会让整批失败。
所有事件：`otto commands --events`。
