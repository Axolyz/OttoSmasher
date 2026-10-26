# 原素材、字幕与人声

这些是可独立使用的能力。分离不依赖字幕，也不要求先建采样；可以先取得人声供外部工具处理字幕，之后再导入文本层。

## 看当前有什么

| 想知道什么 | 查询入口 |
|---|---|
| 原素材路径、关联字幕、各类对象数量 | `sources.list`、`sources.get` |
| 原音频流、已有分离轨、默认轨 | `sources.get`、`assets.tracks` |
| 已导入的台词、音效、OP/ED | `textLayer.list` |
| 当前准备状态 | `sources.prep` |
| 已提交的任务及结果 | `jobs.list`；分离用 `separation.results`，语音分析用 `speech.results` |

`sources.prep` 的七项是状态摘要，不是必须逐项完成的流程：

| 项 | 对应能力 |
|---|---|
| `subtitle` | 字幕预览与导入，或手动添加文本段 |
| `oped` | 字幕标记，或 `oped.identify` / `oped.add` |
| `separation` | `separation.submit` / `separation.results` |
| `defaultVocal` | `tracks.setDefault` 的 `vocal`；也可用 `tracks.originalAsVocal` |
| `defaultSfx` | `tracks.setDefault` 的 `sfx` |
| `lineSamples` | 从选定的段建采样（主题 `samples`） |
| `speech` | `speech.preview` / `speech.submit` / `speech.results` |

## 登记与文件关联

```sh
otto call roots.add '{"path": "/path/to/root"}' --wait
otto call sources.list
```

登记引用原文件，不复制。总文件夹下每个作品一个文件夹，字幕放在媒体旁。新增或改过文件后，可用 `sources.rescan` 更新扫描结果。

应用读取外部 SRT / ASS，不读取视频内挂字幕。内挂文字字幕可以用外部工具提取；PGS、VobSub 提取后仍是图片，需外部 OCR 才能成为文本。
同名字幕优先级是 `.srt` 高于 `.ass`，完全同名高于 `.ja.srt` 这类语言后缀。整理后的交接格式用同视频名的 UTF-8 `.srt`；修改前留 `backup_` 原件，原 ASS 可以保留。

## 应用怎样读字幕

语音分析目前支持日语，使用文本段里的文字对齐音频。交给它的正文是实际说出的日语；说话人可有可无。
选哪个字幕版本、怎样清洗、是否参考其他字幕或音频，由你按素材决定。

| 文件内容 | 应用的解释 |
|---|---|
| ASS 的 Dialogue | 所有样式都会读入，不按 JP / CN 样式筛选；双语正文可在外部拆出日语 |
| `（京子）こんにちは` | 括号内容是说话人，剩下的是台词 |
| 正文中的括号 | 同样参与说话人提取；说话人内部的嵌套读音默认会去掉 |
| 单独的 `（足音）` | 音效提示 |
| 同条目中的音效括号和台词 | 按说话人加台词读取；需要音效提示时可拆成独立条目 |
| `♪～` / `～♪` | OP/ED 的开始 / 结束标记，`〜` 也识别 |

查看单行解释：

```sh
otto call subtitles.ruleTest '{"text": "（京子）こんにちは"}'
```

查看整个文件的解释：`subtitles.preview {"sourceId"}`，或多集的 `subtitles.previewMany {"sourceIds"}`。
结果包含 `segments`、`speakers`、`hints`、`oped`、`problems`。预览只读；采用时把返回 token 交给对应的 `subtitles.import` / `subtitles.importMany`。

字幕中的 OP/ED 随导入写入；`opedErrors` 和 `oped.identify` 提供未配对情况与候选区间，`oped.add` 可以保存判断结果。
没有字幕时，也可以用 `segments.checkAdd` / `segments.add` 添加某一句，或直接使用分离、截取、拉平、导出和音高检索。

## 取得人声

`studio.status` 提供 PyMSS Studio 状态和模型信息；环境未就绪时可把返回信息交给所有者处理。
`assets.tracks {"sourceId"}` 列出音轨；已有声部可以直接使用，需新分离时向 `separation.submit` 交入音轨的 `assetId` 和模型。
该命令支持 `start` / `end`（输入资产局部秒），可分离整轨或选区；完成后 `separation.results {"jobId"}` 返回声部资产及其时间映射。

人声既能供应用分析，也能通过 `exports.wav` 交给外部工具查看响度、频谱或做转写（主题 `combine`）。
仅取得或导出一条局部人声不需要把它设为默认轨。需要默认人声时用 `tracks.setDefault`；默认轨要求完整覆盖原素材，局部声部不能设成整集默认轨。
原混音也可以通过 `tracks.originalAsVocal {"sourceIds": [...]}` 用作人声。

## 任务与资源

分离、语音分析和音高测量共用模型通道，扫描等使用轻量通道。并行数由 `jobs.concurrency_model` / `jobs.concurrency_light` 设置控制，用 `settings.list` 读取，修改走 `edits.apply` 的 `setting` 实体。
排队时前台任务优先于后台任务，同一优先级按提交顺序；正在运行的任务不会因此被抢占。`jobs.list` 可查看 `kind`、`channel`、`background`、进度和结果。
需要改变排队安排时可取消尚未开始的任务再提交；没有单独的队列排序命令。

存储用 `storage.report` 查看、`storage.clean` 清理（危险操作确认见总览）。分离成品压缩保存，但运行时会产生解码和推理用中间音频；成功任务退出后会清理这些中间音频，失败任务可能保留诊断材料。
