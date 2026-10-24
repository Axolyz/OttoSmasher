# 准备原素材（“准备”清单 7 项）

## 0. 先整理文件（用你自己的工具）

应用按文件布局认东西，所以登记前先整理：

* 总文件夹下每个**作品**一个文件夹；作品里怎么分子文件夹都行。
* 字幕和媒体放在一起、**文件名相同**（优先 `.srt`，也可以 `.ass`），**UTF-8** 编码。
* 每行只写实际说出来的日语。删掉翻译、注音假名、译注。
* 说话人写在行首的全角括号里：`（京子）こんにちは`。一行里所有最外层括号都算说话人，
  所以正文里不要留别的括号。只有括号的行是音效：`（足音）`。
* `♪～` 开头 / `～♪` 结尾的行标出 OP / ED（之后会跳过）。
* 和音频同名的图片（`.png`、`.jpg`、`.gif`、视频）会自动绑定为它的画面。
* 用应用的规则检查清理后的一行：`otto call subtitles.ruleTest '{"text": "（京子）こんにちは"}'`。
* 不要删除或移动所有者的媒体文件；要改很多文件时先把计划给所有者看。

## 1. 登记并扫描

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait     # 收编并扫描；不复制文件
otto call sources.list                                     # 所有原素材与计数
otto call works.list
```
改过文件后重新扫描：`otto call sources.rescan --wait`。之后新增的文件也这样收进来。

## 2. 清单

`otto call sources.prep '{"id": "<sourceId>"}'` 显示一个原素材的七项（每项带 `ok`）：

| 项 | 怎么完成 |
|---|---|
| `subtitle`（文本层） | `subtitles.previewMany {"sourceIds": [...]}` → 对每个带 `token` 的行，`subtitles.importMany {"items": [{"sourceId", "token"}]}`。带 `skipped` 的行没有字幕；带 `error` 的要修。单个原素材：`subtitles.importDefault {"sourceId"}`。 |
| `oped` | `oped.identifyMany {"sourceIds": [...]}`（按 ♪ 行识别）。手动：`oped.add`。 |
| `separation` | `studio.status`（模型列表；需要装好 PyMSS Studio——`ok` 为 false 就告诉所有者）。然后 `assets.tracks {"sourceId"}` → `origin: stream` 那条轨的 ID → `separation.submit {"assetId", "model"} --wait` → `separation.results {"jobId"}` 列出各声部。同输入同模型直接返回 `reused`，不起任务。 |
| `defaultVocal` | `tracks.setDefault {"sourceId", "role": "vocal", "assetId": "<人声声部>"}`。本来就是干声的（游戏语音）：`tracks.originalAsVocal {"sourceIds": [...]}` 一次给很多原素材把原混音设好。 |
| `defaultSfx` | `tracks.setDefault {"sourceId", "role": "sfx", "assetId": "<伴奏 / 音效声部>"}` |
| `lineSamples` | 从台词段建采样，见主题 `samples`。 |
| `speech` | `speech.preview {"entry": "source", "ids": [...]}` → `speech.submit`（同样的参数）`--wait` → `speech.results {"jobId"}`。需要文本层，以及一条盖住整句的人声轨。 |

这几项没有固定顺序、也不强制，但在分离出的人声轨上分析效果更好，建采样前应先导入字幕、标好 OP/ED。
分离很慢（每集几分钟，一次一个任务）：全部提交，再一起等。

## 3. 没有字幕时

手动加台词：`segments.checkAdd` → `segments.add {"sourceId", "start", "end", "text"}`（原素材秒）。如果你用自己的语音识别
生成文本，要在本机做，写成同名 `.srt`，再按上面导入。
