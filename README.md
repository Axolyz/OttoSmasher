<p align="center">
  <img src="assets/brand/logo-1024.png" alt="OttoSmasher" width="160">
</p>

<h1 align="center">OttoSmasher</h1>

<p align="center">本地运行的音 MAD 素材工作站</p>

<p align="center">
  <a href="https://github.com/Axolyz/OttoSmasher/releases"><img alt="Release" src="https://img.shields.io/github/v/release/Axolyz/OttoSmasher?include_prereleases&label=release"></a>
  <a href="LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
</p>

OttoSmasher 帮你从番剧、视频、游戏语音和音效包里找台词和音效。你可以边看边截取，分离人声、拉平音高、按 BPM 卡拍，也可以按节奏或音高在整个素材库里检索，最后把结果交给 REAPER 或视频软件。

应用在本机运行，界面有简体中文和英文，语音分析目前只支持日语。

*OttoSmasher is a local desktop workstation for otoMAD material. Review, cut, separate, flatten, beat-stretch and search lines and sound effects from anime, videos, game voices and sample packs, then hand them off to REAPER and video editors. The interface is in Simplified Chinese and English; speech analysis supports Japanese. Runs on macOS (Apple silicon) and Windows 10/11 x64.*

<p align="center">
  <img src="docs/images/sources.webp" alt="原素材页：画面、带说话人的台本、整集时间线（台词段、音效提示、区段标签）" width="100%">
</p>

现在是早期版本（0.1；Windows 是预览版）。遇到问题请[提 issue](https://github.com/Axolyz/OttoSmasher/issues)。

## 功能

| 领域 | 能做什么 |
|---|---|
| 原素材 | 只登记位置，不复制、不转码；按作品分组；导入字幕成台词段，标注音效和区段 |
| 采样 | 在时间线上框选，或按台词、音效提示、整个文件批量创建；用标签、星标和筛选器整理 |
| 语音分析 | 日语音素对齐，可以用辞典修读音，也可以手动修边界 |
| 卡拍 | 按 BPM 对齐每个音头，保留音高和起音，只伸缩中间部分 |
| 检索 | 画一串音块找节奏和发音相近的台词；画音高块在采样或整条音轨上找音 |
| 处理 | 拉平成单一音高；调用另外安装的 PyMSS Studio 分离人声 |
| 交接 | 导出 WAV 和视频片段；拖出到 DAW；复制到 REAPER 时带拉伸标记，删掉标记就回到原声 |
| 省磁盘 | 把要留的采样存成无损切片后，可以删除整集原素材 |
| agent | Claude Code、Codex 等本机 agent 可以通过命令行 `otto` 操作应用；修改按会话记录，可以整批撤回 |

## 截图

采样库：左边是采样列表，右边是画面、波形、语音分析和卡拍对照。

<img src="docs/images/library-detail.webp" alt="采样库：采样列表与详情区（波形、音素、音高曲线、节奏与卡拍）" width="100%">

| 节奏检索：画音块 | 检索结果：命中的位置与匹配度 |
|---|---|
| <img src="docs/images/rhythm-search.webp" alt="节奏检索浮层：画音块并设置条件"> | <img src="docs/images/search-results.webp" alt="检索结果与详情区"> |
| **任务抽屉**：分析、分离、拉平都在后台排队 | **拉平台**：选范围和目标音高 |
| <img src="docs/images/tasks.webp" alt="任务抽屉：后台任务列表"> | <img src="docs/images/flatten.webp" alt="拉平台：外选区、处理范围与目标音高"> |

## 系统要求

| | |
|---|---|
| 系统 | macOS 14 或更新（Apple 芯片）；Windows 10 / 11 x64（预览版，有 DirectML 显卡加速，没有独显时用 CPU） |
| 磁盘 | 应用约 1.2 GB（含模型）；约 4000 个采样时工作区附带数据约 4 GB，不含原素材 |
| 网络 | 应用本身不需要 |
| 可选 | 分离人声需要 [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases) |

## 安装

### macOS

1. 从[发布页](https://github.com/Axolyz/OttoSmasher/releases)下载 `OttoSmasher-<版本>-macos-arm64.zip`，并核对发布说明里的 SHA-256：
   ```
   shasum -a 256 OttoSmasher-*.zip
   ```
2. 解压，把 `OttoSmasher.app` 拖进“应用程序”。
3. 第一次打开前，在终端运行：
   ```
   xattr -dr com.apple.quarantine /Applications/OttoSmasher.app
   ```
   应用只做了本机签名，没有经过 Apple 公证，所以不运行这一句会被 macOS 拦下。每次下载新版本后都要再运行一次。也可以在被拦下后，到“系统设置 → 隐私与安全性”点“仍要打开”。

### Windows（预览版）

1. 从发布页下载 `OttoSmasher-<版本>-windows-x64.zip`，用 `Get-FileHash OttoSmasher-*.zip` 核对 SHA-256。
2. 解压到任意文件夹，运行 `OttoSmasher.exe`。包没有签名，SmartScreen 拦下时点“更多信息 → 仍要运行”。

你的数据都在工作区里（默认是“文稿”下的 `OttoSmasher Workspace`），更新应用不会动它。

## 开始使用

第一次用，跟着[入门教程](docs/user/tutorial.md)走一遍。全部说明在[用户说明](docs/user/README.md)。

想让 agent 代劳，把这段话发给它：

```
请用命令行 otto 操作我电脑上的 OttoSmasher：先运行 otto status 和 otto guide，应用没开就运行 otto open。
任务：……
```

详细说明见[让 agent 操作 OttoSmasher](docs/user/agents.md)。

## 参与开发

问题和建议请[开 issue](https://github.com/Axolyz/OttoSmasher/issues)，并附上系统版本、复现步骤和工作区 `Data/Logs/` 下的相关日志。发日志前检查一下，别带上不想公开的素材路径。

- 从源码运行、测试、打包：[DEVELOPMENT.md](docs/DEVELOPMENT.md)
- 开发约定（人和 AI 代理通用）：[AGENTS.md](AGENTS.md)
- 系统结构：[ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 现行决定：[DECISIONS.md](docs/DECISIONS.md)，改变既定行为前请先开 issue 讨论
- 计划：[ROADMAP.md](docs/ROADMAP.md)

请不要提交任何素材（番剧、字幕、游戏语音等）。测试用合成音频，真实素材只在本地通过环境变量引用。

如果你熟悉人力 VOCALOID 工作流，欢迎开 issue 讲讲你的做法和痛点：批量找特定的音、半自动生成 UTAU 音源都可能做，但开发者不熟悉这一流程。

## 致谢

本项目用到了 [pydomino](https://github.com/DwangoMediaVillage/pydomino)、[pyopenjtalk-plus](https://github.com/tsukumijima/pyopenjtalk-plus)、[tsqyomi](https://huggingface.co/tsukumijima/tsqyomi-models)、[FCPE](https://github.com/CNChTu/FCPE)、[HiFiShifter](https://github.com/ARounder-183/HiFiShifter)、[OpenVPI](https://github.com/openvpi) 的 PC-NSF-HiFiGAN、[Rubber Band](https://breakfastquay.com/rubberband/)、[mpv](https://mpv.io/)、[FFmpeg](https://ffmpeg.org/)、[ONNX Runtime](https://onnxruntime.ai/)、[Electron](https://www.electronjs.org/)、[React Aria](https://react-spectrum.adobe.com/react-aria/) 和 [PyMSS Studio](https://github.com/pymss-project/pymss-studio)。完整清单和各自的许可见 [THIRD_PARTY.md](docs/THIRD_PARTY.md)。

## 许可

OttoSmasher 以 [GPL-3.0-or-later](LICENSE) 发布。你可以自由使用、修改和再分发；再分发时要同样以 GPL 发布并提供源码。本程序不提供任何担保。

- 随包的第三方组件各有许可，发布包的 `licenses/` 里收着这些文件。
- 模型权重是单独的组件。对齐、读音预测、音高模型为 MIT；拉平声码器 PC-NSF-HiFiGAN 是 CC BY-NC-SA 4.0，只能用于非商业用途，商业再分发前请删掉 `Contents/Resources/models/flatten/`。
- 你处理的番剧、字幕、游戏语音、歌曲等素材的版权属于各自的权利人。本程序不附带任何素材。
