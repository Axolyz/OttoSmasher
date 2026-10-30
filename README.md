<p align="center">
  <img src="assets/brand/logo-1024.png" alt="OttoSmasher" width="160">
</p>

<h1 align="center">OttoSmasher</h1>

<p align="center">本地运行的音 MAD 素材工作站</p>

从番剧、视频、游戏语音和音效包里找台词和音效：审阅、截取、分离、拉平、卡拍、检索，再交给 REAPER 和视频软件。

*A local desktop workstation for otoMAD material: review, cut, separate, flatten, beat-stretch and search lines and sound effects from anime, videos, game voices and sample packs, then hand them off to REAPER and video editors. UI in Simplified Chinese; Japanese speech for now.*

> **当前状态**：开发中（阶段 8 / 9 已完成，阶段 10“Windows 与发布”还没开始）。下面写的安装方式是发布版的做法；
> 发布包出来之前，请按 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 从源码运行。

- **用户使用说明（含快速开始）**：[docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- **第三方组件与许可**：[docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)
- **从源码运行、开发与测试**：[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

## 亮点：比以往的做法好在哪

- **审阅、分离、截取、拉平一站完成**：以往要在播放器里找、在 DAW 里切、另开分离工具、再开拉平工具，文件来回导。
  这里原素材（番剧、视频、游戏语音、音效包）只登记位置、不复制不转码；边看边截，分离、拉平的成品自动挂回同一条时间线，采样随时能返回原素材看前后文。
- **节奏归一化（卡拍）**：台词按音块（每个起音）对齐到 BPM 网格，起音核心逐样本保留，只伸缩中间部分、保持音高。
  同一句话可以按“近快 / 近慢”两种密度试听，不用再在 DAW 里一个个手拉。
- **节奏检索**：画一串音块（时值、元音、辅音、相对音高），在整个采样库里找“节奏和发音都对得上”的台词，按 BPM 比较，命中直接按检索时的方案卡拍试听、导出。
- **音高检索**：画几个音高块，在采样里或整条原素材音轨上找唱得 / 说得正好是那几个音的片段；可以忽略八度。
- **REAPER 交接带拉伸标记**：⌘C / Ctrl+C 复制的 REAPER 条目可以是“原声 + 拉伸标记”——粘贴进 REAPER 后卡拍还能继续手调，不是烘焙死的 WAV。
- **能交给 LLM agent 干活**：应用开着时，本机的 agent（Claude Code、Codex 等能跑命令的）可以用命令行 `otto` 调用和界面同一组功能——
  登记、导入字幕、分离、建采样、分析、打标签、检索、导出——需要判断的事（清理字幕、挑台词、没有字幕时找 OP）由它自己做完再写回来。中英双语的说明书 `otto guide` 随附；
  agent 的修改按会话记录、可整批撤回，撤销不了的操作要你在应用里点确认。见[使用说明 §17](docs/USER_GUIDE.md#17-让-agent-操作-ottosmasher)。
- **一切可撤销、可追溯**：资料修改都能撤销；每个采样记得来自哪条音轨的哪一段、用什么方案处理过；导出文件按内容复用、从不被应用删除。

## 能做什么

- **原素材**：番剧集数、视频、游戏语音、音效包……都登记成原素材，按作品分组；原生播放器任意跳转；导入字幕成台词段，标注音效提示和区段标签。
- **采样**：在时间线上框选截取，或按台词段 / 音效提示 / 整个文件批量建；标签、分面、保存筛选器、标签表达式。
- **语音分析**：日语文本前端（pyopenjtalk-plus + tsqyomi 读音预测）+ pydomino 音素对齐；用户辞典；音素边界可以手动修。
- **节奏与卡拍、三大搜索、拉平、人声分离**（调用另外安装的 PyMSS Studio）。
- **交接**：导出 WAV、复制 REAPER 交接、导出视频片段（原声或卡拍，画面同步）、按住 Alt / ⌥ 拖出到 DAW。
- **采样独立化**：把要留的采样存成无损切片后删除原素材，省磁盘。

## 计划中（TODO）

- [ ] **更好地支持人力 VOCALOID 工作流**
  > 在现在的架构下，批量搜特定的音（某个元音、某种辅音 + 元音、某个音高）、乃至半自动生成 UTAU 音源都可以比较轻松地实现，
  > 但开发者并不熟悉这一工作流——需要懂行的大佬来提建议（欢迎开 issue 讲讲你的做法和痛点）。
- [ ] **支持中文、英文的语音分析**（流程与日语相同，需要另选文本前端与对齐模型）
- [ ] **界面多语言翻译**（文案已全部抽成资源文件，加语言不用改业务代码）
- [ ] **以语音聚类为基础的说话人日志**（没有字幕说话人时，按声音自动分出“谁在说”）
- [ ] Windows 实机验收与发布包（阶段 10）

## 系统要求

| | |
|---|---|
| macOS | 14 或更新，Apple Silicon（M 系列芯片） |
| Windows | 10 / 11，x64（**还没在实机上验收**） |
| 磁盘 | 应用约 1 GB；模型约 190 MB；工作区按素材量增长（约 4000 个采样时附带数据约 4 GB，不含原素材本身） |
| 网络 | 只有你点「下载」时才联网（下载模型）；不上传任何东西 |

## 安装（发布版）

1. 从发布页下载对应平台的 ZIP，核对发布说明里写的 SHA-256：
   - Windows（PowerShell）：`Get-FileHash OttoSmasher-*.zip -Algorithm SHA256`
   - macOS：`shasum -a 256 OttoSmasher-*.zip`
2. 解压：
   - **Windows**：解压到任意文件夹（路径里有中文、空格都可以），运行 `OttoSmasher.exe`。
     SmartScreen 提示“已保护你的电脑”时点“更多信息 → 仍要运行”。
   - **macOS**：把 `OttoSmasher.app` 拖进“应用程序”。应用没有经过 Apple 公证，第一次打开会被拦下：
     在 Finder 里右键 → 打开 → 再点“打开”；或者在“系统设置 → 隐私与安全性”里点“仍要打开”。
3. 程序目录只读；你的数据都在**工作区**里，更新应用不会动它。

## 第一次使用

1. **准备模型**（语音分析、读音预测、音高、拉平要用）：设置（Ctrl+, / ⌘,）→ **环境与模型** →「下载缺少的模型」。
   四个文件共约 190 MB，地址固定到定型的版本，下完核对 SHA-256 才放进工作区的 `Models/`。
   下不动时，按面板上写的网址自己下载，再用「从文件导入…」选文件或文件夹（按内容认，文件名不对也行）。
2. **人声分离（可选）**：安装 [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases)
   （免费软件，AGPL-3.0，不随本应用分发）。推荐在 Studio 里下载 **HyperACE v2**（`bs_roformer_voc_hyperacev2`，人声 / 伴奏）
   和 **BandIt v2 multi**（对白 / 音乐 / 音效三轨）两个模型，回到 设置 → **PyMSS Studio** 刷新。不分离也能用其余全部功能。
3. 然后看 [用户使用说明的「快速开始」](docs/USER_GUIDE.md#快速开始)：第一步是在设置里登记**原素材文件夹**。

## 配合 LLM agent 使用

能在你电脑上跑终端命令的 agent（Claude Code、Codex 等）可以通过命令行 `otto` 操作**开着的** OttoSmasher：登记、导入字幕、分离、建采样、分析、打标签、检索、导出，
需要判断的事（清理字幕、挑台词、对轴、找 OP）它自己做完再写回来。agent 的修改按会话记录、可整批撤回；撤销不了的操作要你在应用里点允许。

1. 打开 OttoSmasher → 设置 › **命令行与 agent**：这里写着 `otto` 在哪，可以「安装 otto 命令」，也可以「复制给 agent 的开场白」。
   目前 `otto` 只在从源码运行时可用（仓库里的 `tools/otto`）；发布版的启动器还在做。
2. 把开场白发给 agent，后面接上你的任务。开场白大致是：

   ```
   我电脑上开着 OttoSmasher，请用它的命令行 otto 操作（<otto 的位置>）。
   第一次用的话，从 <REPO_URL>/blob/main/skills/ottosmasher/SKILL.md 下载这个 skill，按你的工具的方式装到当前项目（不要装成全局）；
   你的工具不支持 skill，就把它的内容存进项目的长期说明。
   任务：……
   ```

   skill 只是入口：告诉 agent 怎么找到 `otto`、先看 `otto guide`。说明书本身由 `otto guide` 给出，总是和你装的版本一致，按需要分主题读。
3. 可选：
   - `otto setup playbook`：在工作区生成一份“我的约定”（`Agent/playbook.md`），用平常的话写你的习惯，agent 开工先看它。
   - `otto setup audio --for claude-code|codex|other`：给听不到声音的 agent 接一个音频分析工具（audio-mcp：频谱图、响度、带时间的转写）。

详见 [使用说明 §17](docs/USER_GUIDE.md#17-让-agent-操作-ottosmasher)。

## 发布包里有什么、没有什么

| 随应用分发 | 不随应用分发（为什么） |
|---|---|
| Electron 运行时与界面 | **模型权重**（4 个 ONNX，约 190 MB）——应用里下载或从文件导入。规格要求权重不进安装包；其中拉平声码器 PC-NSF-HiFiGAN 是 CC BY-NC-SA 4.0（非商业）许可，不能和 GPL 程序打包在一起再分发；分开下载也让每次更新应用不用重下模型 |
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
- 你用本程序处理的番剧、字幕、游戏语音、歌曲等素材的版权属于各自的权利人；本程序不附带任何素材。
