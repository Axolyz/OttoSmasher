# 导出

导出文件默认写在工作区里（`Library/Exports`），文件名按应用的命名规则生成；命令返回路径。
`exports.wav` 也支持指定 `directory`，适合把选区交给外部工具。
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

采样没有画面时导出视频会报错（不会生成黑屏视频）；先绑定画面（主题 `combine`）。
卡拍版用的全局 BPM：`rhythm.bpm`（只读），由所有者在应用里设置。

## 给外部工具一段原速音频

```sh
otto call exports.wav '{"assetId": "<assetId>", "start": 2.0, "end": 5.0, "content": "audio", "track": "vocals"}'
```

`start` / `end` 是该资产的局部秒；`assetId` 决定实际音源，`content` / `track` 是导出命名用文字，不会替你选择或分离人声。
结果的 `path` 是导出文件，`reused` 表示是否复用了相同导出。外部时间与原片时间的对应见 `concepts`。
