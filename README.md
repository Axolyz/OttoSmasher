# OttoSmasher

本地运行的音 MAD 素材工作站：从动画原片里找台词和音效、试听、截取成采样，做语音分析、卡拍、拉平、人声分离，
再把结果交给 REAPER 和视频软件。

*A local desktop workstation for otoMAD material: find, audition and cut lines and sound effects from anime episodes,
align them, stretch them to a beat, flatten pitch, and hand them off to REAPER and video editors. UI in Simplified Chinese; Japanese speech for now.*

> **当前状态**：开发中（阶段 8 / 9 已完成，阶段 10“Windows 与发布”还没开始）。下面写的安装方式是发布版的做法；
> 发布包出来之前，请按 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 从源码运行。

- **用户使用说明**：[docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- **第三方组件与许可**：[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)
- **从源码运行、开发与测试**：[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## 能做什么

- **原片**：登记动画原片（MKV / MP4 等，原片不复制、不转码），原生播放器任意跳转；导入字幕成台词段，标注音效提示和区段标签。
- **采样**：在时间线上框选、截取成采样；按台词段或音效提示批量建采样；标签、分面、保存筛选器、标签表达式。
- **语音分析**：日语文本前端（pyopenjtalk-plus + tsqyomi 读音预测）+ pydomino 音素对齐；用户辞典；音素边界可以手动修。
- **节奏与卡拍**：音块、停顿与语段；按全局 BPM 卡拍（保音高伸缩，起音核心逐样本保留）。
- **三大搜索**：节奏检索、音高检索、单音的音色 / 瞬态筛选。
- **拉平**：把一句台词拉成一个音高（PC-NSF-HiFiGAN 声码器）。
- **分离**：调用另外安装的 PyMSS Studio 分离人声 / 三轨。
- **交接**：导出 WAV、复制 REAPER 交接（剪贴板）、导出视频片段（原声或卡拍，画面同步）、拖出到 DAW。
- **采样独立化**：把要留的采样存成无损切片后删除原片，省磁盘。

## 系统要求

| | |
|---|---|
| macOS | 14 或更新，Apple Silicon（M 系列芯片） |
| Windows | 10 / 11，x64（**还没在实机上验收**） |
| 磁盘 | 应用约 1 GB；模型约 190 MB；工作区按素材量增长（约 4000 个采样时附带数据约 4 GB，不含原片） |
| 网络 | 只有你点「下载」时才联网（下载模型）；不上传任何东西 |

## 安装（发布版）

1. 从发布页下载对应平台的 ZIP，核对发布说明里写的 SHA-256：
   - macOS：`shasum -a 256 OttoSmasher-*.zip`
   - Windows（PowerShell）：`Get-FileHash OttoSmasher-*.zip -Algorithm SHA256`
2. 解压：
   - **macOS**：把 `OttoSmasher.app` 拖进“应用程序”。应用没有经过 Apple 公证，第一次打开会被拦下：
     在 Finder 里右键 → 打开 → 再点“打开”；或者在“系统设置 → 隐私与安全性”里点“仍要打开”。
   - **Windows**：解压到任意文件夹（路径里有中文、空格都可以），运行 `OttoSmasher.exe`。
     SmartScreen 提示“已保护你的电脑”时点“更多信息 → 仍要运行”。
3. 程序目录只读；你的数据都在**工作区**里，更新应用不会动它。

## 第一次使用

1. **准备模型**（语音分析、读音预测、音高、拉平要用）：打开 设置（⌘,）→ **环境与模型** →「下载缺少的模型」。
   四个文件共约 190 MB，地址固定到定型的版本，下完核对 SHA-256 才放进工作区的 `Models/`。
   下不动时，按面板上写的网址自己下载，再用「从文件导入…」选文件或文件夹（按内容认，文件名不对也行）。
2. **人声分离（可选）**：安装 [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases)
   （免费软件，AGPL-3.0，不随本应用分发），在 Studio 里装好推理环境、下载分离模型（例如 `bs_roformer_voc_hyperacev2`），
   回到 设置 → **PyMSS Studio** 刷新。不分离也能用其余全部功能。
3. 然后按 [用户使用说明](docs/USER_GUIDE.md) 从“添加原片”开始。

## 发布包里有什么、没有什么

| 随应用分发 | 不随应用分发（为什么） |
|---|---|
| Electron 运行时与界面 | **模型权重**（4 个 ONNX，约 190 MB）——应用里下载或从文件导入。规格要求权重不进安装包；其中拉平声码器 PC-NSF-HiFiGAN 是 CC BY-NC-SA 4.0（非商业）许可，不能和 GPL 程序打包在一起再分发；另外分开下载也让每次更新应用不用重下模型 |
| 播放组件（libmpv）与渲染桥 | **PyMSS Studio**——独立的软件（AGPL-3.0），有按显卡区分的多个版本，自带环境和模型管理，由你自己安装 |
| Python 运行时与 Core 依赖（ONNX Runtime、NumPy、SciPy、pyopenjtalk-plus 与它的辞典等） | **PyTorch**——不需要（定型模型都是 ONNX） |
| 媒体工具 ffmpeg / ffprobe、Rubber Band | 你的素材 |
| 读音预测的 tokenizer / metadata、声码器的 config（小的非权重支持文件） | |

详细清单与各组件的许可见 [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)。

## 许可

OttoSmasher 以 **GNU General Public License v3.0 或更新版本（GPL-3.0-or-later）** 发布，全文见 [LICENSE](LICENSE)。

```
OttoSmasher
Copyright (C) 2026 OttoSmasher contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
```

意思是：你可以自由使用、修改和再分发本程序；再分发（包括改过的版本）时要同样以 GPL 发布并提供源码；本程序不提供任何担保。
- 随包的第三方组件各有许可（Rubber Band 是 GPL，ffmpeg、mpv 等见清单），分发时保留它们的声明。
- **模型权重**遵守各自上游的许可，由你自己下载；**PC-NSF-HiFiGAN 只能用于非商业用途**。
- 你用本程序处理的动画、字幕、歌曲等素材的版权属于各自的权利人；本程序不附带任何素材。
