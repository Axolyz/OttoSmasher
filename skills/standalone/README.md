# 音 MAD 素材预处理 skills

两个独立的 [Agent Skills](https://agentskills.io/specification)，给番剧这类日语语音素材做预处理。不需要安装任何软件，能运行命令的 agent（Claude Code、Codex 等）都能用。

| Skill | 做什么 |
|---|---|
| `preparing-subtitles` | 洗字幕、修时间、拆两人条目、用声纹标说话人（实验性），没有字幕时生成带时间的字幕（工具没有定型）。可以走完整流程，也可以只做其中一步 |
| `finding-op-ed` | 比对多集音频，找出片头曲和片尾曲 |

## 安装

把 `zh-CN/`（中文）或 `en/`（英文）里需要的文件夹，复制到你的 agent 读取 skill 的位置，比如项目里的 `.claude/skills/` 或 `.agents/skills/`。

## 需要什么

- **查看音频的工具：** 比如 [audio-mcp](https://pypi.org/project/audio-mcp/)。没有听觉的 agent 全靠它判断声音。
- **ffmpeg。**
- **强制对齐器：** `preparing-subtitles` 要用。这些数字是用 [pydomino](https://github.com/DwangoMediaVillage/pydomino) 测的，只支持日语。
- **分离好的人声：** 推荐先分离，比如用 PyMSS Studio。
- **uv：** 标说话人的声纹脚本要用，第一次运行会下载 PyTorch 和模型，共几百 MB。

## 使用前请知道

这些方法来自作者自己的探索，主要在少数几部番剧上试过，数字只能当参照，换作品要重新校准。它们不保证结果正确，重要的内容请人工核对。

它们来自 [OttoSmasher](https://github.com/Axolyz/OttoSmasher)。那个项目把这些流程和素材库、人工审阅接在了一起。
