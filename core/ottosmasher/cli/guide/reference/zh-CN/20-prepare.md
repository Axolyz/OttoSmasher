# 原素材、字幕与人声

## 登记

应用按文件布局认东西：登记的总文件夹下，第一层子文件夹是**作品**；原素材只记位置，不复制。

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait     # 收编并扫描
otto call sources.list                                     # 所有原素材（work、episode、subtitle_path、counts、audio_streams）
otto call sources.rescan --wait                            # 改过、新加过文件后重新扫描
```
不在总文件夹里的文件也能登记：`sources.add {"paths": [...]}`。登记后就能分离、加台词、分析，结果留在库里、可撤销。

## 应用怎么认字幕

- **关联**：和媒体同一文件夹、**完全同名**的 `.srt` 优先，其次 `.ass`；再其次同名加后缀（`<视频名>.ja.srt`，日语后缀优先），再其次同一文件夹的字幕子文件夹（`Subs`、`Sub`、`Subtitles`、`字幕` 等，不分大小写）里的。只关联，导入要另外做。要求 UTF-8。
- **不读**视频文件里内挂的字幕流；图形字幕（PGS、VobSub）是图片，不是文字。
- **ASS**：所有样式的 Dialogue 都读进来，不按样式区分（双语字幕的中文那条也会变成台词）；`{…}` 特效标签、`<…>` 去掉，`\N` 是换行，Comment 行不读。
- **每一行的解释**（规则在设置里，可改；逐行读，宁可少记、不记错）：
  - 台词行**行首**的括号是这一行的说话人：`（京子）こんにちは`；`（虹夏、リョウ）せーの` = 几个人同时说。名字里嵌套的读音默认去掉：`（京子(きょうこ)たち）` → 「京子たち」。
  - 台词中间的括号从不当人名，只从台词里去掉：`歳納(としのう)京子` → 台词「歳納京子」。
  - 只有括号的一行是音效：`（足音）`（括号里的换行不算换行）。**但下一行是没标注的台词时，音效和说话人都不认**（可能是单独一行写的人名）。
    一条里既有音效行又有台词，就各出一个：一条音效提示 + 一段台词。
  - 没标注的台词行 = 不知道是谁，**从不跟上一行**。一条里**每个台词行都标了**才记说话人（不同的人 = 多人）；有一行没标就不记，
    段上的 `speakersWithheld` 为真。
  - 所以段的 `speakers` 是**确定能读出**的说话人，空 = 不知道，不是“没人说”。完整的标注在段的 `raw`（原字幕这一条的原文；编辑、拆分后仍在，合并后是各段原文连起来）。
    想要每条都有说话人，就先把字幕洗成“一条一个人、每个台词行都标”的写法。
  - `♪～` 开头 / `～♪` 结尾的行标出 OP / ED（`〜` 也认）。
  - `♪（ハミング）` 这样的行会变成只有“♪”的台词，语音分析会报 `frontend-failed`（`empty-text`）。
- **台词文字就是对齐用的文字**：语音分析按它去对齐声音，所以要写实际说出来的话（目前只支持日语）；翻译、注释混在里面会对不准或失败。

查看应用怎么读：

| 想看 | 命令 |
|---|---|
| 一行 | `subtitles.ruleTest {"text": "（京子）こんにちは"}` |
| 任意一个字幕文件（不登记、不导入） | `subtitles.parse {"path", "duration"}`（主题 `primitives`） |
| 已登记原素材的关联字幕，导入前预览 | `subtitles.preview {"sourceId"}` / `subtitles.previewMany {"sourceIds"}`：`segments`、`speakers`（名字和次数）、`hints`（音效）、`oped`、`problems`、`token` |

导入：把预览给的 `token` 交给 `subtitles.import` / `subtitles.importMany {"items": [{"sourceId", "token"}]}`；字幕里的 OP/ED 标记一起导入。
**重新导入**只替换和新字幕时间有交叠的旧对象；时间不交叠的旧段会留下（按规格），要删就用编辑。新字幕碰到**受保护**的旧对象（段被改过、或有手动音素；音效提示被改过或手动加的；OP/ED 人工标过）时，这一条新字幕跳过（预览里 `status: skip`、`reason: protected`）；`options` 里 `replace: false` 则保留所有旧对象，`force` 可以逐条强制替换（`otto describe subtitles.preview`）。
时间和文字都没变的段算“无变化”（`unchanged`），**不更新它的说话人和原文**；要按新字幕从头来，先 `subtitles.clear {"sourceIds"}` 删掉导入的标记
（`subtitles.clearPlan` 先看会删多少；手输的段不删，受保护的默认留下，`protected: true` 才删；一个编辑批次，能撤销），再导入。

OP/ED 类型可在 `options` 中显式指定：`{"opedConfirm": [{"index": 0, "kind": "OP"}]}`。index 是预览 `oped` / `pairs` 的配对序号（从 0 起），不是字幕行号；kind 为 OP 或 ED。用同一份 options 重新预览并导入，适用于独立 OP/ED 片段或需要修正类型推断时。

## 准备清单

`sources.prep {"id"}` 返回七项状态（各带 `ok`）。这是状态摘要，没有固定顺序，也不要求每项都完成（没有字幕本来就是正常的）：

| 项 | 相关命令 |
|---|---|
| `subtitle`（文本层） | 字幕预览与导入（上面）；没有字幕时 `segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}`（原素材秒） |
| `oped` | 导入时没配成对看 `opedErrors`；`oped.identify {"sourceId"}` 给出建议的 `pairs` 和 `errors`；`oped.add {"sourceId", "kind", "start", "end", "via": "confirm", "refs"}` |
| `separation` | 见下一节 |
| `defaultVocal` / `defaultSfx` | `tracks.setDefault {"sourceId", "role": "vocal" / "sfx", "assetId"}`；`tracks.originalAsVocal {"sourceIds"}` 一次把原混音设为人声；`tracks.separatedVocals {"sourceIds"}` 列出已有的人声声部，`tracks.defaultFromSeparation {"sourceIds", "model", "stem"}` 把它一次设为默认人声轨 |
| `lineSamples` | 主题 `samples` |
| `speech` | `speech.preview {"entry": "source", "ids"}` → `speech.submit` 同样参数 → `speech.results {"jobId"}` |

“语音分析”这一项里，文字本身读不出音而失败的段（例如只有“♪”）单独记作读不了，不挡这一项完成。

## 分离与人声轨

- `studio.status`：PyMSS Studio 装没装、有哪些模型（`ok` 为 false 就告诉用户装 PyMSS Studio）。`studio.status {"refresh": true}` 刷新已安装模型列表，不下载权重；子目录文件变化会使缓存失效。保留返回的 stem 名称，角色别名不分大小写。先查 tracks.separatedVocals / assets.tracks，复用已有声部。
- `separation.submit {"assetId", "model"}` 分离整条；加 `start` / `end`（资产秒）只分离一段；`ranges: [[start, end], ...]` 一次分离多段——拼成一个输入一起分离（Studio 按约 22 秒的块推理，短段单独交也按整块算）。结果 `separation.results {"jobId"}`：每个声部一条新音轨，带时间映射。
- 局部分离可传 `localTags` 给新建的声部采样打标签，或传 `useCurrentProject: true` 在提交时加入桌面当前项目。整轨分离不建采样。
  局部分离出来的声部只盖住那一段，人声声部自动带人声角色；**局部分离的每个声部还会自动建一个采样**（整轨分离不建）——这些采样撤销不了，删除要用户确认，多段分离就会建很多个。每次请求都真的分离一遍、生成新的音轨，不会复用已有结果；要重跑前先看 `assets.tracks`，多出来的用 `assets.delete` 删（有采样在用的删不了）。整集分离要十几到几十分钟（长任务的等法见总览“等待长任务”）。
- 默认人声 / 音效轨必须盖住整个原素材，局部声部不能当默认轨。但需要指定音轨的地方都能直接给它：
  `speech.preview` / `speech.submit` 加 `"assetId"` 就用那条轨分析（只分析落在它范围里的段），`samples.create`、`exports.wav`、原始能力也都收 `assetId`。
- 一句台词的音素只有一份，属于原素材的时间线：不论用哪条轨分析，原混音、整轨人声、局部声部上都读同一份。
- 一个文件有多条音频流时，只有“分析音轨”参与（主题 `concepts`）。

## 任务与队列

分离、语音分析、测音高（包括原始能力 `speech.align`、`f0.track`）走“模型”通道，扫描、`text.analyze` 等走“轻量”通道；同时跑几个由设置 `jobs.concurrency_model`（默认 1）/ `jobs.concurrency_light`（默认 2）决定
（`settings.list` 读，`edits.apply` 的 `setting` 实体改）。排队时你和用户提交的任务先于应用自动准备的任务，其余按提交顺序；`jobs.promote` 把排队中的任务提到同一通道最前面
（最近提的在前），运行中的不会被打断。分离成功后中间文件会自动删掉，失败的保留现场。

## 分析成功 ≠ 对得准

对齐只在“段的时间 ± 设置里的容差（`analysis.tolerance_before` / `analysis.tolerance_after`，默认各 0.2 秒；`settings.list` 看当前值）”这个窗口里找，并且总会把整句塞进窗口——
段的边界偏了，音素会被硬拉到旁边的声音上，任务照样成功。边界和实际说话差零点几秒以上时，结果就不可靠（主题 `primitives` 有试验数字）。

## 当前导入与准备状态

`subtitles.parse` 会在 problems 中列出超过 120 秒的条目，导入跳过这些条目。重扫只更新关联、不导入；手动选过或清空过的关联保持用户选择。相同时间和文字的段再导入不会更新说话人和 raw。修订优先使用 edits.apply 更新已有对象，必要时先看 subtitles.clearPlan 再清导入标记。受保护对象按预览结果分别处理。

`sources.prep {"id"}` 返回 subtitle、oped、separation、defaultVocal、defaultSfx、lineSamples、speech 七个顶层键，各自有 ok；没有 items 数组。这些项目显示应用准备状态，内容核验另见 workflow。sources.list 的 counts.speech 是语音性质采样数，counts.analyzed 是其中有可用分析的数量；段数看 counts.lines。

原片含多音轨时 default_audio_stream 决定分析流，不会自动更换默认人声轨。
