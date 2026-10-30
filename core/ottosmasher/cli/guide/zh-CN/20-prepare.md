# 准备原素材（“准备”清单 7 项）

## 0. 先整理字幕文件（用你自己的工具）

**目标**：每集一个和视频**完全同名**的 **UTF-8 `.srt`**，每条只写**实际说出来的话**（目前语音分析只支持日语）——语音分析按这段文字去对齐音频，
翻译、注释和别的文字会让它失败或对不准。能看出说话人就写成行首括号，看不出就不写（字幕组的字幕通常没有说话人，这是正常的，不用硬补）。
应用也能读 `.ass`，但请把洗好的结果写成同名 `.srt`：同名时应用优先用 `.srt`（也优先于 `<视频名>.ja.srt` 这类带后缀的），原来的 `.ass` 不用动。

应用按文件布局认东西：总文件夹下每个**作品**一个文件夹；字幕和媒体放在一起。
应用读字幕的规则：全角括号开头的是说话人 `（京子）こんにちは`（一行里所有最外层括号都算）；只有括号的行是音效 `（足音）`；
`♪～` 开头 / `～♪` 结尾的行标出 OP / ED。用 `subtitles.ruleTest` 看应用怎么读一行：
`otto call subtitles.ruleTest '{"text": "（京子）こんにちは"}'`。
应用不读视频文件里内挂的字幕流：要用的话先提取成同名文件（例如 `ffmpeg -i ep01.mkv -map 0:s:0 ep01.ass`）；图形字幕（PGS、VobSub）提取出来是图片，要先做文字识别。

真实字幕常见的问题（都在文件上改，不要改所有者的原文件——先留一份 `backup_` 前缀的原件，再写同名的干净版本）：
* **字幕组的中日双语字幕**（最常见）：应用读 `.ass` 时会读进**所有样式**的 Dialogue，不按样式区分，中文那条也会变成台词。
  按样式名（`JP` / `CN` 之类）或文字本身只留日语；同一条里用 `\N` 上下排的只留日语那行。去掉 `{\…}` 特效标签、Comment 行、
  只有特效的行（标题字、注释、屏幕文字翻译）。OP/ED 和插入曲的歌词行删掉，再按歌词行的时间写成 `♪～` / `～♪` 标记，或导入后用 `oped.add` 标出。
* 翻译、译注混在正文里 → 删掉。说话人名里的读音 `（京子(きょうこ)たち）` 应用默认会去掉；但正文里的读音 `歳納(としのう)京子！`
  会被当成说话人「としのう」（一行里所有最外层括号都算说话人）→ 在文件里删掉正文的读音括号。
* 一个条目第一行是音效、第二行起才是台词 `（ドアチャイム）\nウワーッ！` → 应用会把音效当成说话人；拆成两个时间相同的条目。
* OP/ED 标记成不了对（例如一个开始后面跟着两个结束）→ 导入后看 `opedErrors`，用 `oped.identify` 的建议确认（第 2 节）。`♪〜` 和 `♪～` 两种波浪号应用都认。
* 哼歌、歌声写成 `♪（ちなつのハミング）` → 会变成一段只有“♪”的台词，语音分析报 `frontend-failed`（`empty-text`）；改成音效行 `（ちなつのハミング）`，或有歌词就写出歌词。
* 字幕文件名和视频不同（多了前缀、语言后缀）→ 写一份同名的。有机器转写（`.ja.srt`）和正式字幕两份时，优先正式字幕（有说话人）。
* **时间轴对不上**：字幕和视频不是同一个版本（例如 TV 版字幕配 BD 视频）时会整体差几秒，或在原来 CM 的位置之后才开始差。
  开头、中间、结尾各抽几句：用 `ffmpeg -ss <秒> -t <秒>` 截出那段音频，用本地语音识别或音量起止核对。整体偏了就平移所有时间，从某处开始偏就从那里起平移。
* 没有字幕：可以在本机做语音识别生成同名 `.srt`；不做也行，见第 3 节。

**洗完先检查再导入**：还没登记就先做第 1 节，已登记、新写了同名文件就先 `otto call sources.rescan --wait`；然后 `otto call subtitles.preview '{"sourceId": "<id>"}'`（只读，不导入）：
`speakers`（说话人和次数；出现台词片段、读音、奇怪的名字 = 还有括号没清干净）、`problems`（读不出时间的块）、
`segments` 里的 `text`（就是要对齐的文字）、`hints`（音效）、`oped`（OP/ED 配对）。有问题就改文件、重新检查。

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

**队列**：分离、语音分析、测音高走“模型”通道，扫描等走“轻量”通道；同时跑几个由设置 `jobs.concurrency_model`（默认 1）/ `jobs.concurrency_light`（默认 2）决定
（`settings.list` 读，`edits.apply` 的 `setting` 实体改）。排队时你和所有者提交的任务先于应用自动准备的任务，其余按提交顺序；运行中的不会被打断，没有插队命令
（必要时 `jobs.cancel` 排队中的任务、之后再提交）。分离一集要十几到几十分钟；成功后中间文件会自动删掉，失败的保留现场。

**分离的范围**：`separation.submit` 可以给 `start` / `end`（资产秒）只分离一段；结果是只盖住这一段的声部，可以导出、截取，但默认人声 / 音效轨必须盖住整个原素材，不能设成局部声部。
**外部音频**：任何音频文件 `sources.add {"paths": [...]}` 登记成原素材后，就能分离、加台词、语音分析，结果留在库里、可撤销。

**重新导入字幕**：只替换和新字幕有时间交叠的旧对象；新字幕里时间不交叠的旧段会留下（按规格）。要清掉就用编辑删除。

**分析成功 ≠ 对得准**：对齐只在“段的时间 ± 设置里的容差（默认前 0.1、后 0.2 秒）”这个窗口里找，并且总会把整句塞进窗口——
段的边界偏了，音素会被硬拉到旁边的声音上，任务照样成功。边界要先大致对准（误差在零点几秒内），再分析。

## 3. 没有字幕时

手动加台词：`segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}`（原素材秒）。
不加台词也能截取、分离、拉平、导出，以及在原素材音轨上做音高检索（主题 `search`）。
