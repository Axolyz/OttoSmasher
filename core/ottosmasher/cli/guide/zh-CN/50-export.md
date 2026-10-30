# 导出

导出文件默认写在工作区里（`Library/Exports`；`exports.wav` 可以给 `directory` 写到别处），文件名按应用的命名规则生成；命令返回路径。
需要的话从那里复制出去；不要在工作区里改名或删除。

| 导出什么 | 命令 |
|---|---|
| 采样的 WAV（原声，或按全局 BPM 逐个卡拍） | `exports.samples {"ids": [...], "versions": {"<id>": "stretched"}}` → 路径列表 |
| 单个采样的卡拍版，带清单 | `exports.stretched {"id"}` |
| 任意资产区间的 WAV | `exports.wav` / `exports.range` |
| 采样的**视频片段**（它的画面：同步视频、图片或循环动画） | `exports.video {"id", "version": "original"} --wait` → `video.path` |
| 资产区间的视频片段 | `exports.videoRange {...} --wait` |
| 检索命中 | `hits.export`、`hits.video` |
| REAPER 轨道模板 | `reaper.template`（剪贴板交接只在应用里有） |

WAV 导出（`exports.wav`、`exports.range`、`exports.stretched`、`hits.export`）的结果里除了 `path`、`reused`，还有交给外部工具用的坐标：
`range`（实际导出的资产区间，按源样本取整后）、`sampleRate`、`frames`、`mapping`（文件秒 → 原素材秒；卡拍版是含变速的合成映射）。
`exports.wav` 的 `content` / `track` 只是文件名里的文字，不决定导出哪条声音（由 `assetId` 决定）。
视频导出完成后，路径也写在任务结果里（`jobs.list` 的 `result.path`），事后可以按任务查。

采样没有画面时导出视频会报错（不会生成黑屏视频）；先绑定画面（主题 `combine`）。
卡拍版用的全局 BPM：`rhythm.bpm`（只读），由所有者在应用里设置。
