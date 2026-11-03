<p align="center">
  <img src="assets/brand/logo-1024.png" alt="OttoSmasher" width="160">
</p>

<h1 align="center">OttoSmasher</h1>

<p align="center"><b>本地运行的音 MAD 素材工作站</b></p>

<p align="center">
  <a href="https://github.com/Axolyz/OttoSmasher/releases"><img alt="Release" src="https://img.shields.io/github/v/release/Axolyz/OttoSmasher?include_prereleases&label=release"></a>
  <a href="LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
  <img alt="Platform: macOS (Apple silicon)" src="https://img.shields.io/badge/platform-macOS%2014%2B%20%C2%B7%20Apple%20silicon-lightgrey">
  <img alt="Electron + Python 3.12" src="https://img.shields.io/badge/stack-Electron%20%2B%20Python%203.12-informational">
</p>

从番剧、视频、游戏语音和音效包里找台词和音效：审阅、截取、分离、拉平、卡拍、检索，再交给 REAPER 和视频软件。
全部在本机运行，不上传任何东西。

*OttoSmasher is a local desktop workstation for otoMAD material: review, cut, separate, flatten, beat-stretch and search lines and sound
effects from anime, videos, game voices and sample packs, then hand them off to REAPER and video editors. It also exposes its engine to
LLM agents through a command line. The UI is in Simplified Chinese; speech analysis currently supports Japanese.*

<p align="center">
  <img src="docs/images/sources.webp" alt="原素材页：画面、带说话人的台本、整集时间线（台词段、音效提示、区段标签）" width="100%">
</p>

> **状态**：第一个公开版本（0.1，macOS）。功能已经齐全并有自动化测试，但还年轻——遇到问题欢迎[提 issue](https://github.com/Axolyz/OttoSmasher/issues)。

## 目录

- [亮点](#亮点)
- [功能一览](#功能一览)
- [截图](#截图)
- [系统要求](#系统要求)
- [安装](#安装)
- [第一次使用](#第一次使用)
- [配合 LLM agent 使用](#配合-llm-agent-使用)
- [从源码运行](#从源码运行)
- [项目结构](#项目结构)
- [路线图](#路线图)
- [参与贡献](#参与贡献)
- [致谢](#致谢)
- [许可](#许可)

## 亮点

- **审阅、分离、截取、拉平一站完成**：以往要在播放器里找、在 DAW 里切、另开分离工具、再开拉平工具，文件来回导。
  这里原素材只登记位置、不复制不转码；边看边截，分离、拉平的成品自动挂回同一条时间线，采样随时能返回原素材看前后文。
- **节奏归一化（卡拍）**：台词按音块（每个起音）对齐到 BPM 网格，起音核心逐样本保留，只伸缩中间部分、保持音高。
  同一句话可以按“近快 / 近慢”两种密度试听，不用再在 DAW 里一个个手拉。
- **节奏检索**：画一串音块（时值、元音、辅音、相对音高），在整个采样库里找“节奏和发音都对得上”的台词，按 BPM 比较，命中直接按检索时的方案卡拍试听、导出。
- **音高检索**：画几个音高块，在采样里或整条原素材音轨上找唱得 / 说得正好是那几个音的片段；可以忽略八度。
- **REAPER 交接带拉伸标记**：⌘C 复制的 REAPER 条目可以是“原声 + 拉伸标记”——粘贴进 REAPER 后卡拍还能继续手调，不是烘焙死的 WAV。
- **能交给 LLM agent 干活**：应用开着时，本机的 agent（Claude Code、Codex 等）可以用命令行 `otto` 调用和界面同一组功能，
  需要判断的事（清理字幕、挑台词、对轴、找 OP）由它自己做完再写回来；它的修改按会话记录、可整批撤回，撤销不了的操作要你在应用里点允许。
- **可撤销、可追溯**：资料修改都能撤销；每个采样记得来自哪条音轨的哪一段、用什么方案处理过；导出文件按内容复用、从不被应用删除。

## 功能一览

| 领域 | 能做什么 |
|---|---|
| 原素材 | 番剧、视频、游戏语音、音效包都登记成原素材，按作品分组；原生播放器任意跳转；导入字幕成台词段，标注音效提示和区段标签 |
| 采样 | 在时间线上框选截取，或按台词段 / 音效提示 / 整个文件批量建；标签、分面、保存筛选器、标签表达式 |
| 语音分析 | 日语文本前端（pyopenjtalk-plus + tsqyomi 读音预测）+ pydomino 音素对齐；用户辞典；音素边界可以手动修 |
| 卡拍与检索 | 节奏归一化、节奏检索、音高检索、单音指标筛选 |
| 处理 | 拉平（PC-NSF-HiFiGAN 重合成定音）、人声分离（调用另外安装的 PyMSS Studio，可整集或只分离几段） |
| 交接 | 导出 WAV、复制 REAPER 交接、导出视频片段（原声或卡拍，画面同步）、按住 ⌥ 拖出到 DAW |
| 存储 | 采样独立化：把要留的采样存成无损切片后删除原素材，省磁盘 |

完整说明见 [用户使用说明](docs/USER_GUIDE.md)（含五种常见场景的快速开始）。

## 截图

**采样库与详情区**：左边是采样列表（每行带画面缩略图和音块），右边是选中采样的画面、波形（音素、mora、音高曲线）、语音分析结果，以及节奏与卡拍的对照。

<img src="docs/images/library-detail.webp" alt="采样库：采样列表与详情区（波形、音素、音高曲线、节奏与卡拍）" width="100%">

| 节奏检索：画音块（前导辅音、元音、音高） | 检索结果：命中的位置与匹配度 |
|---|---|
| <img src="docs/images/rhythm-search.webp" alt="节奏检索浮层：画音块并设置条件"> | <img src="docs/images/search-results.webp" alt="检索结果与详情区"> |
| **任务抽屉**：分析、分离、拉平都在后台排队，agent 提交的任务带标记 | **拉平台**：选处理范围和目标音高，重合成成一个定音的单音 |
| <img src="docs/images/tasks.webp" alt="任务抽屉：后台任务列表"> | <img src="docs/images/flatten.webp" alt="拉平台：外选区、处理范围与目标音高"> |

## 系统要求

| | |
|---|---|
| 系统 | macOS 14 或更新，Apple 芯片（M 系列）。Windows 暂不发布（代码里保留了 Windows 的路径，但没有在实机上验收；[欢迎来维护](#windows-版招维护者)） |
| 磁盘 | 应用约 1.2 GB（含模型）；工作区按素材量增长（约 4000 个采样时附带数据约 4 GB，不含原素材本身） |
| 网络 | 不需要；不上传任何东西 |
| 可选 | [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases)（人声分离；分离模型由它自己下载） |

## 安装

1. 从 [发布页](https://github.com/Axolyz/OttoSmasher/releases) 下载 `OttoSmasher-<版本>-macos-arm64.zip`，核对发布说明里写的 SHA-256：
   ```
   shasum -a 256 OttoSmasher-*.zip
   ```
2. 解压，把 `OttoSmasher.app` 拖进“应用程序”。
3. **第一次打开前，在终端里运行一次：**
   ```
   xattr -dr com.apple.quarantine /Applications/OttoSmasher.app
   ```
   然后双击打开。应用只做了本机签名（ad-hoc），没有经过 Apple 公证，不运行这一句 macOS 会拦下它（提示“无法验证开发者”或“已损坏”）。
   这句只是去掉下载时加上的“来自网络”标记；每次下载新版本替换后都要再运行一次。
   （不想用终端也可以：双击一次被拦下后，到“系统设置 → 隐私与安全性”最下面点“仍要打开”。）
4. 程序目录只读；你的数据都在**工作区**里（默认 `~/文稿/OttoSmasher Workspace`），更新应用不会动它。

## 第一次使用

1. **模型**：发布版带着全部四个模型（对齐、读音预测、音高、拉平），不用下载；设置 → **环境与模型** 里能看到它们都就绪。
2. **人声分离（可选）**：安装 [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases)（免费软件，AGPL-3.0，不随本应用分发）。
   推荐在 Studio 里下载 **HyperACE v2**（`bs_roformer_voc_hyperacev2`，人声 / 伴奏）和 **BandIt v2 multi**（对白 / 音乐 / 音效三轨），
   回到 设置 → **PyMSS Studio** 刷新。不分离也能用其余全部功能。
3. 看 [使用说明的「快速开始」](docs/USER_GUIDE.md#快速开始)：第一步是在设置里登记**原素材文件夹**。

## 配合 LLM agent 使用

能在你电脑上跑终端命令的 agent（Claude Code、Codex 等）可以通过命令行 `otto` 操作**开着的** OttoSmasher。

1. 设置 › **命令行与 agent**：这里写着 `otto` 在哪，可以「安装 otto 命令」（之后终端里直接输入 `otto`；应用换了位置要重装一次），
   也可以「复制给 agent 的开场白」。
2. 把开场白发给 agent，后面接上你的任务。开场白大致是：
   ```
   我电脑上开着 OttoSmasher，请用它的命令行 otto 操作（<otto 的位置>）。
   第一次用的话，从 https://raw.githubusercontent.com/Axolyz/OttoSmasher/main/skills/ottosmasher/SKILL.md 下载这个 skill，
   按你的工具的方式装到当前项目（不要装成全局）；你的工具不支持 skill，就把它的内容存进项目的长期说明。
   任务：……
   ```
   [skill](skills/ottosmasher/SKILL.md) 只是入口：告诉 agent 怎么找到 `otto`、先看 `otto guide`。说明书本身由 `otto guide` 给出，总是和你装的版本一致。
3. 可选：
   - `otto setup playbook`：在工作区生成一份“我的约定”（`Agent/playbook.md`），用平常的话写你的习惯，agent 开工先看它。
   - `otto setup audio --for claude-code|codex|other`：给听不到声音的 agent 接一个音频分析工具（[audio-mcp](https://pypi.org/project/audio-mcp/)：频谱图、响度、带时间的转写）。

命令分两层：**业务命令**操作资料库（原素材、采样、编辑与撤销），**原始能力**只做计算（日语对齐、读音分析、测音高、按应用规则读字幕文件），
声音可以是任意文件。详见 [使用说明 §17](docs/USER_GUIDE.md#17-让-agent-操作-ottosmasher)。

## 从源码运行

所有依赖都装在仓库目录里（`tools/uv`、`tools/npm`），不改动系统环境。需要 macOS（Apple 芯片）、Homebrew 的 `node`、`ffmpeg`、`rubberband`。

```bash
git clone https://github.com/Axolyz/OttoSmasher.git && cd OttoSmasher
tools/uv sync && tools/npm install
.venv/bin/python tools/fetch_third_party.py            # libmpv、模型支持文件等（固定版本，核对 SHA-256）
tools/uv run --with setuptools python tools/build_domino.py && node tools/build-native.mjs
OTTO_DEV=1 tools/npm start                             # 第一次启动后在 设置 → 环境与模型 下载模型
```

测试、打包发布包与开发约定见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。

## 项目结构

```
app/        Electron 主进程、preload（原生播放：libmpv 渲染桥）、React 界面（renderer/）
core/       Python 3.12 的 Core：领域模型、SQLite 资料库与编辑通道、任务调度、语音分析与检索引擎、命令行 otto（cli/）
e2e/        Playwright 驱动真实 Electron 的端到端测试
skills/     给 LLM agent 的入口 skill
tools/      仓库内的 uv / npm、第三方文件拉取、原生扩展构建、macOS 打包（package_mac.py）
docs/       使用说明、架构、路线图、决定记录、第三方许可、命令目录（api/commands.json）
```

界面与 Core 之间只走一套命令（`docs/api/commands.json`，约 170 条，带参数 / 返回 Schema 与错误码表）；命令行 `otto` 用的也是同一套。
架构细节见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 路线图

- [ ] **更好地支持人力 VOCALOID 工作流**
  > 在现在的架构下，批量搜特定的音（某个元音、某种辅音 + 元音、某个音高）、乃至半自动生成 UTAU 音源都可以比较轻松地实现，
  > 但开发者并不熟悉这一工作流——需要懂行的大佬来提建议（欢迎开 issue 讲讲你的做法和痛点）。
- [ ] **支持中文、英文的语音分析**（流程与日语相同，需要另选文本前端与对齐模型）
- [ ] **界面多语言翻译**（文案已全部抽成资源文件，加语言不用改业务代码）
- [ ] **以语音聚类为基础的说话人日志**（没有字幕说话人时，按声音自动分出“谁在说”）
- [ ] Windows 版（[招维护者](#windows-版招维护者)）

开发进度与遗留事项见 [docs/ROADMAP.md](docs/ROADMAP.md)。

## 参与贡献

- **问题与建议**：请[开 issue](https://github.com/Axolyz/OttoSmasher/issues)，附上系统版本、复现步骤，以及工作区 `Data/Logs/` 下的相关日志（注意别带上你不想公开的素材路径）。
- **代码**：开发约定在 [AGENTS.md](AGENTS.md)（人和 AI 代理通用）；提交前跑一遍 [DEVELOPMENT.md](docs/DEVELOPMENT.md) 里的测试。
  现行的设计决定在 [docs/DECISIONS.md](docs/DECISIONS.md)（原始需求规格在 [docs/spec/](docs/spec/README.md)），改变既定行为前请先开 issue 讨论。
- **不要提交任何素材**（番剧、字幕、游戏语音等）；测试用合成音频，真实素材只在本地通过环境变量引用。

### Windows 版：招维护者

OttoSmasher 基于 Electron，界面、Python Core 和用到的模型本身都是跨平台的；代码里也一直保留着 Windows 的路径
（进程管理、命名管道、播放器与原生扩展的构建脚本），只是没有在实机上构建、验收过。
作者自己只用 Mac，没有精力构建和维护 Windows 版。**如果你愿意负责 Windows 版的构建、测试和发布，非常欢迎**——
请开 issue 打个招呼。还没验证过的地方大致是：libmpv 的来源与播放器原生扩展、pydomino 扩展的编译、
结束进程树、剪贴板交接给 REAPER、`otto` 命令行（见 [docs/ROADMAP.md](docs/ROADMAP.md) 的 L9、L26、L47）。

## 致谢

本项目站在这些项目之上：
[pydomino](https://github.com/DwangoMediaVillage/pydomino)（音素对齐）、
[pyopenjtalk-plus](https://github.com/tsukumijima/pyopenjtalk-plus) 与 [tsqyomi](https://huggingface.co/tsukumijima/tsqyomi-models)（日语文本前端与读音预测）、
[FCPE](https://github.com/CNChTu/FCPE) 与 [HiFiShifter](https://github.com/ARounder-183/HiFiShifter)（音高、模型转换）、
[OpenVPI](https://github.com/openvpi) 的 PC-NSF-HiFiGAN（拉平声码器）、
[Rubber Band](https://breakfastquay.com/rubberband/)（保音高伸缩）、[mpv](https://mpv.io/)（播放）、
[FFmpeg](https://ffmpeg.org/)、[ONNX Runtime](https://onnxruntime.ai/)、[Electron](https://www.electronjs.org/)、[React Aria](https://react-spectrum.adobe.com/react-aria/)，
以及 [PyMSS Studio](https://github.com/pymss-project/pymss-studio)（人声分离）。完整清单与各自的许可见 [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md)。

## 许可

OttoSmasher 以 **GNU General Public License v3.0 或更新版本（GPL-3.0-or-later）** 发布，全文见 [LICENSE](LICENSE)。
你可以自由使用、修改和再分发本程序；再分发（包括改过的版本）时要同样以 GPL 发布并提供源码；本程序不提供任何担保。

- 随包的第三方组件各有许可（Rubber Band 与带 libx264 的 FFmpeg 是 GPL，其余见清单），分发时保留它们的声明；发布包里的 `licenses/` 收着这些文件。
- **模型权重**是单独的组件，各按上游许可随包分发：对齐、读音预测、音高为 MIT；**拉平声码器 PC-NSF-HiFiGAN 是 CC BY-NC-SA 4.0，只能用于非商业用途**，
  不属于本程序的 GPL 部分——商业再分发前请删掉 `Contents/Resources/models/flatten/`，见 [THIRD_PARTY.md](docs/THIRD_PARTY.md)。
- 你用本程序处理的番剧、字幕、游戏语音、歌曲等素材的版权属于各自的权利人；本程序不附带任何素材。
