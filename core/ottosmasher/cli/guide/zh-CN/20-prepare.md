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

- **关联**：和媒体同一文件夹、**完全同名**的 `.srt` 优先，其次 `.ass`；再其次同名加后缀（`<视频名>.ja.srt`，日语后缀优先），再其次同一文件夹 `Subs` / `字幕` 子文件夹里的。只关联，导入要另外做。要求 UTF-8。
- **不读**视频文件里内挂的字幕流；图形字幕（PGS、VobSub）是图片，不是文字。
- **ASS**：所有样式的 Dialogue 都读进来，不按样式区分（双语字幕的中文那条也会变成台词）；`{…}` 特效标签、`<…>` 去掉，`\N` 是换行，Comment 行不读。
- **每一行的解释**（规则在设置里，可改）：
  - 全角括号里的是说话人：`（京子）こんにちは`。一行里**所有**最外层括号都算，所以正文里的读音 `歳納(としのう)京子` 会被当成说话人「としのう」；
    说话人名里嵌套的读音默认去掉：`（京子(きょうこ)たち）` → 「京子たち」。
  - 只有括号的行是音效：`（足音）`。一个条目第一行是音效、第二行是台词时，整条按“说话人 + 台词”读，音效会被当成说话人。
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
**重新导入**只替换和新字幕时间有交叠的旧对象；时间不交叠的旧段会留下（按规格），要删就用编辑。

## 准备清单

`sources.prep {"id"}` 返回七项状态（各带 `ok`）。这是状态摘要，没有固定顺序，也不要求每项都完成（没有字幕本来就是正常的）：

| 项 | 相关命令 |
|---|---|
| `subtitle`（文本层） | 字幕预览与导入（上面）；没有字幕时 `segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}`（原素材秒） |
| `oped` | 导入时没配成对看 `opedErrors`；`oped.identify {"sourceId"}` 给出建议的 `pairs` 和 `errors`；`oped.add {"sourceId", "kind", "start", "end", "via": "confirm", "refs"}` |
| `separation` | 见下一节 |
| `defaultVocal` / `defaultSfx` | `tracks.setDefault {"sourceId", "role": "vocal" / "sfx", "assetId"}`；`tracks.originalAsVocal {"sourceIds"}` 一次把原混音设为人声 |
| `lineSamples` | 主题 `samples` |
| `speech` | `speech.preview {"entry": "source", "ids"}` → `speech.submit` 同样参数 → `speech.results {"jobId"}` |

“语音分析”这一项里，文字本身读不出音而失败的段（例如只有“♪”）单独记作读不了，不挡这一项完成。

## 分离与人声轨

- `studio.status`：PyMSS Studio 装没装、有哪些模型（`ok` 为 false 就告诉所有者装 PyMSS Studio）。
- `separation.submit {"assetId", "model"}` 分离整条；加 `start` / `end`（资产秒）只分离一段。结果 `separation.results {"jobId"}`：每个声部一条新音轨，带时间映射。
  局部分离出来的声部只盖住那一段。同一段分离两次会得到两份，不复用。整集分离要十几到几十分钟（长任务的等法见总览第 5 条）。
- 默认人声 / 音效轨必须盖住整个原素材，局部声部不能当默认轨。但需要指定音轨的地方都能直接给它：
  `speech.preview` / `speech.submit` 加 `"assetId"` 就用那条轨分析（只分析落在它范围里的段），`samples.create`、`exports.wav`、原始能力也都收 `assetId`。
- 一句台词的音素只有一份，属于原素材的时间线：不论用哪条轨分析，原混音、整轨人声、局部声部上都读同一份。
- 一个文件有多条音频流时，只有“分析音轨”参与（主题 `concepts`）。

## 任务与队列

分离、语音分析、测音高走“模型”通道，扫描等走“轻量”通道；同时跑几个由设置 `jobs.concurrency_model`（默认 1）/ `jobs.concurrency_light`（默认 2）决定
（`settings.list` 读，`edits.apply` 的 `setting` 实体改）。排队时你和所有者提交的任务先于应用自动准备的任务，其余按提交顺序；运行中的不会被打断，没有插队命令
（必要时 `jobs.cancel` 排队中的任务、之后再提交）。分离成功后中间文件会自动删掉，失败的保留现场。

## 分析成功 ≠ 对得准

对齐只在“段的时间 ± 设置里的容差（默认前 0.1、后 0.2 秒）”这个窗口里找，并且总会把整句塞进窗口——
段的边界偏了，音素会被硬拉到旁边的声音上，任务照样成功。边界要先大致对准（误差在零点几秒内），再分析（主题 `primitives` 有试验数字）。
