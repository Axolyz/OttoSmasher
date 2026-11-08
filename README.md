<p align="center">
  <img src="assets/brand/logo-1024.png" alt="OttoSmasher" width="160">
</p>

<h1 align="center">OttoSmasher</h1>

<p align="center">本地运行的音 MAD 素材工作站</p>

<p align="center">简体中文 | <a href="README.en.md">English</a></p>

<p align="center">
  <a href="https://github.com/Axolyz/OttoSmasher/releases"><img alt="Release" src="https://img.shields.io/github/v/release/Axolyz/OttoSmasher?include_prereleases&label=release"></a>
  <a href="LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue"></a>
</p>

OttoSmasher 是一个音 MAD 素材工作站。它可以从番剧、视频、游戏语音和音效包中统一管理台词、采样和音效，一站式完成截取、人声分离、拉平和卡拍(卡节奏)，并支持按节奏或音高检索整个素材库，最后把结果交给 DAW 或视频软件。Claude Code、Codex 等 agent 也可以通过命令行操作它，完成洗字幕、挑台词、选音色这类需要判断的工作；不接 agent，它也是一个能独立使用的素材工作站。

OttoSmasher 不生成音乐，也不替你创作。它负责让素材处理和素材管理少一些重复劳动，选什么、怎么编、想表达什么，仍然由你决定。

**当前项目仍处于早期版本，Windows 版为预览版，可能存在 BUG 或不稳定的问题。**

下载：[发布页](https://github.com/Axolyz/OttoSmasher/releases)（macOS Apple 芯片、Windows 10 / 11 x64）。安装步骤见[安装](#安装)。

<table>
  <tr>
    <td width="50%"><img src="docs/images/library-detail.webp" alt="采样库：采样列表与详情区（波形、音素、音高曲线、节奏与卡拍）"></td>
    <td width="50%"><img src="docs/images/sources.webp" alt="原素材页：画面、带说话人的台本、整集时间线（台词段、音效提示、区段标签）"></td>
  </tr>
</table>

## 工作流推荐

对动画、人声视频这类语音素材的推荐工作流是：

1. 按作品整理素材文件夹，把同名字幕放在视频旁边（见[文件夹和字幕的写法](docs/user/reference.md)）
2. 在 OttoSmasher 中登记文件夹，同名字幕会自动关联，再点一下导入
3. 分离人声，并设为默认人声轨（需要另外安装 PyMSS Studio 并手动下载模型）。背景不干净的素材如果跳过这一步，后面的语音分析基本不能用
4. 把台词批量建成采样，并进行语音分析
5. 按节奏或音高检索采样，按 BPM 卡拍试听
6. 把结果复制到 REAPER，或导出 WAV、视频片段

当然，OttoSmasher 也支持其他用法：

1. 一边审阅原片一边手动挑选中意的台词，不批量建采样
2. 不分离人声、没有字幕乃至非日语的素材也可以截取、分离、拉平和按音高检索
3. 导入游戏语音包、音效包乃至乐器单音，按音高、瞬态或音色筛选

第一次使用请看[入门教程](docs/user/tutorial.md)。完整说明见[用户说明](docs/user/README.md)。

## 配合 agent 使用

Claude Code、Codex 等能在本机运行命令的 agent 可以通过命令行 `otto` 操作 OttoSmasher，调用的是和界面相同的功能。应用负责存资料、分离、分析、检索和导出这些确定的工作；洗字幕、对轴、挑台词、挑音色这些需要判断的工作可以交给 agent。agent 也可以出编排方案，但我们目前更推荐它做上游的素材处理，选择和创作留给人。

目前作者推荐至少使用 DeepSeek v4 flash 或 GLM 5.3 Flash 这一智力等级的模型 + Coding Agent 工具，需要注意的是 Windows 下由于系统原因，很多 Agent 工具为了能在现有架构下运行 `otto` 命令只能开 Full Access 模式，不然会撞沙箱。

MacOS + Codex(沙箱) + GPT 6.1 Sol 是本项目的推荐 Agent 配置，也是作者实际工作时采用的配置。实测 DeepSeek Harness (Full Access) 的可用性在完成基础任务时已经较高，但是如字幕预处理以及采样选择的这类需要判断和组合工具的复杂任务效果不能保证，作者已经优化过一轮，但仍然不能保证效果像 GPT 一样好。

把下面的话发给 agent，后面接上任务即可。

操作软件和资料库：

```
请用命令行 otto 操作我电脑上的 OttoSmasher：先运行 otto status 和 otto guide，应用没开就运行 otto open。
任务：……
```

让 agent 按内置方法论预处理字幕，可以接着这样说（把路径和精度换成自己的）：

```
任务：请按 preparing-subtitles skill 及其相关参考文档，预处理【视频文件夹】的字幕；正确字幕源是【字幕路径】，以【视频版本】为时间轴基准。按【快速／标准／精细】精度，完成清洗、对轴、必要的换人拆行和说话人标注，复用已有分离人声。先接好并试用任务需要的音频工具，最后把 UTF-8 SRT 按视频同名放在旁边，再导入 Otto。原字幕留备份，告诉我哪些地方还拿不准。
```

三档精度和可补充的信息见用户手册的[按方法论预处理字幕](docs/user/agents.md#按方法论预处理字幕)。

只做音频计算，不碰资料库：

```
请用命令行 otto 做一次音频计算，应用没开就运行 otto open。
只用原始能力：用 otto commands --layer primitive 查命令，用法看 otto guide primitives。不要读写资料库，也不用看其他说明。
任务：……
```

- **能力开放，流程不写死**：音素对齐、读音分析、音高测量、检索、分离和拉平都是独立的能力。应用本体只做确定性的计算，agent 结合上下文自己组织流程，也可以写脚本批量调用。
- **数据由应用管理**：原片、音轨、台词、音素、采样和标签都在结构化的资料库里，agent 需要时查询，不用把它们塞进上下文，也不用自己管一堆文件。
- **可以查看和撤回**：agent 对资料的修改按会话记录，可以在应用的操作历史中查看，也可以整批撤回。新建的采样和音轨不能撤回，可以删除。
- **能“听”声音**：接上音频工具 audio-mcp 后，agent 可以看频谱、量响度、做带时间的转写。
- **可用于预处理任务或其他的复杂语音分析任务**：洗字幕、对轴、按说话人分组等对后续处理至关重要的预处理任务有内置 skill，是作者自己摸索出来的方法论，都是工作区里的文件，可以依照自己的喜好直接修改，也可以添加自己的做法。

详细说明见[让 agent 操作 OttoSmasher](docs/user/agents.md)。

## 功能介绍

### 边看边截取

可以一边播放一边在时间线上框选，也可以从台本中的一句台词直接建立采样。台词可以按文字或读音搜索，跨集也能找到某句话在哪。每个采样都记得自己的来源，可以随时返回原素材查看前后文。

### 批量建采样

可以把一整季的台词一次建成采样，也可以按音效提示或整个文件批量创建。OP 和 ED 里的台词会自动跳过。采样只记录音轨上的一段区间做映射，不会新建文件，所以建得再多也不会多占多少空间。

### 语音分析

把日语台词转成音素和读音，再找出每个音素在音频里的时间范围，通常称之为"音素对齐"。读音不对可以用用户辞典修正，边界不准时可以人工修正。

### 卡拍

卡拍把原语音的节奏通过微调对齐到 BPM 网格，同时尽量保留语音中固有的节奏感，不让声音走形。其大致原理是：

1. 根据音素对齐找出每个音块（一个元音或拨音）的起音到下一个音块的起音之间的时长，再把这些时长的比例归一化成较小的整数比（可以调节参数使得整数比倾向于更小）。
2. 嵌入 BPM 网格时自动选择最接近原语速的嵌入密度，避免大幅拉伸改变原素材宏观上的播放速度。
3. 起音前后最多 8 毫秒原样保留，所以咬字和音头不会被拉糊；两个起音之间用 Rubber Band R3 保音高伸缩。
4. 用句中的停顿优先吸收多出来的时间。

每句话可以试听不同密度的方案，也可以手动调整每块占几格。不填 BPM 时，会按原语速卡拍。

### 节奏检索

画一串音块，每块可以指定元音、辅音、音高和响度，在整个采样库中查找对得上的采样。命中结果可以直接卡拍试听，也可以导出或复制到 REAPER。

| 画音块并设置条件 | 查看命中的位置与匹配度 |
|---|---|
| <img src="docs/images/rhythm-search.webp" alt="节奏检索浮层：画音块并设置条件"> | <img src="docs/images/search-results.webp" alt="检索结果与详情区"> |

### 音高检索

画几个音高块，在采样或整条音轨上查找音高正好是这几个音的片段，可以忽略八度。可用于辅助原音系音 MAD 的制作。

### 导出

可以导出原声或卡拍后的 WAV，也可以从采样库直接拖出 WAV 到 DAW 中。用复杂手段在外部处理好的声音可以放回原来的位置 (称为"回导")，成为一条新音轨，也能关联到原画面和原标签。

### 复制到 REAPER

采样按 Ctrl+C / ⌘C 复制，到 REAPER 里粘贴，每个音头都已经自动挂好了拉伸标记，不用再一个个手动找音头、打标记，可以直接拖动标记调整。

可以选择两种方式：

- 已卡拍：粘贴的 item 已经按照卡拍的方式调过拉伸标记了。如果指定了相应的 BPM，拉伸标记也会完全卡在 REAPER 某个倍数的 BPM 网格里，方便进一步编辑。如果删除所有标记就回到原声。
- 原声：只在每个音头放拉伸标记，保持原来的节奏，方便自己卡拍。

一次复制多条时，它们会在同一轨上依次排开，每条之间空一小节。

### 人声分离(及任意 pymss 模型处理)任务

调用另外安装的 PyMSS Studio，可以分离整集，也可以只分离几段。模型要预先在 Studio 里手动下载，人声分离方面，普通动画和视频场景下推荐 HyperACE v2（`bs_roformer_voc_hyperacev2`），是稳定且高性能的社区基线模型，歌曲环境下推荐Becruily deux(`becruily_deux`)，能以少量噪声为代价较好地保证人声高频不丢失。分离结果是原素材上的新音轨，设为默认人声轨后，之后建的采样和语音分析都会用它。

此功能亦可调用任何 pymss 中已安装的模型对音频进行处理，并保存为相应的音轨名称。

### 拉平

把一段语音的音高拉平到同一个音，台词内容不变，由 PC-NSF-HiFiGAN 声码器重新合成。可以处理整段、只处理元音、从首个元音开始，或者只拉平中间、保留首尾；目标音高可以自动确定，也可以手动指定。成品是一条新音轨，并会生成一个有明确音高的采样。

| 拉平：选择范围和目标音高 | 任务抽屉：分析、分离、拉平都在后台排队 |
|---|---|
| <img src="docs/images/flatten.webp" alt="拉平台：外选区、处理范围与目标音高"> | <img src="docs/images/tasks.webp" alt="任务抽屉：后台任务列表"> |

### 整理采样

标签可以从作品、字幕说话人和区段标注自动继承，也可以手动添加。支持星标、标签表达式和按作品、人物、音高等条件筛选，常用的条件可以存成筛选器。批量修改前会先显示前后对比，资料修改都可以撤销。

### 音效包和乐器单音

音效包和乐器单音可以批量建成采样，有明确音高的按音名检索，打击和音效可以按起音时间、亮度、噪声倾向等指标筛选（单音筛选为实验功能，效果可能很差，目前更推荐用 Agent 接入）。

### 独立化

把要保留的采样存成无损切片，画面存成视频片段。之后即使删除整集原素材，这些采样也能继续播放、导出和读取语音分析结果，只是不能再返回原素材查看前后文。

### 人力 VOCALOID 工作流

按照现在项目的成熟度，批量裁切拼字的音素、乃至半自动生成 UTAU 音源都可以轻松实现，但开发者不熟悉人力 VOCALOID 工作流所以不知道怎么做到软件里，如果你是一位熟悉上述工作流的音 mader，非常欢迎提这方面的开发思路。

## 系统要求

| | |
|---|---|
| 系统 | macOS 14 或更新（Apple 芯片）；Windows 10 / 11 x64（预览版，支持 DirectML 显卡加速，没有独显时使用 CPU） |
| 磁盘 | 应用约 1.2 GB（含模型）；约 4000 个采样时工作区附带数据约 4 GB，不含原素材 |
| 语言 | 界面支持简体中文和英文；语音分析目前只支持日语 |
| 人声分离 | 需要 [PyMSS Studio](https://github.com/pymss-project/pymss-studio/releases) |

## 安装

### macOS

1. 从[发布页](https://github.com/Axolyz/OttoSmasher/releases)下载 `OttoSmasher-<版本>-macos-arm64.zip`，并核对发布说明中的 SHA-256：
   ```
   shasum -a 256 OttoSmasher-*.zip
   ```
2. 解压后把 `OttoSmasher.app` 拖入“应用程序”。
3. 第一次打开前，在终端运行：
   ```
   xattr -dr com.apple.quarantine /Applications/OttoSmasher.app
   ```
   应用没有经过 Apple 公证，不运行这条命令会被 macOS 拦下。每次下载新版本后都需要重新运行。也可以在被拦下后，到“系统设置 → 隐私与安全性”点击“仍要打开”。

### Windows（预览版）

1. 从[发布页](https://github.com/Axolyz/OttoSmasher/releases)下载 `OttoSmasher-<版本>-windows-x64.zip`，用 `Get-FileHash OttoSmasher-*.zip` 核对 SHA-256。
2. 解压到任意文件夹，运行 `OttoSmasher.exe`。安装包没有签名，SmartScreen 拦下时点击“更多信息 → 仍要运行”。

## 常见问题

### 数据存放在哪里？

都在工作区中，默认是“Documents”下的 `OttoSmasher Workspace`。生成的音轨和导出文件在其中的 `Library/`。

### 更新会丢失数据吗？

不会。替换应用不会改动工作区。新版本需要升级数据库时，会先自动备份到 `Data/Backups/`。

### 会复制或修改我的原素材吗？

不会。OttoSmasher 只记录原素材的位置，也不会删除磁盘上的原始文件。

### 需要联网吗？

应用本身不需要。发布版自带全部模型；人声分离的模型由 PyMSS Studio 下载。不过如果让使用云端模型的 agent 接入本应用，它读到的台词和音频可能会被上传，是否这样使用由你决定。

### 不分离人声、没有字幕或者素材不是日语，能用吗？

能用，基础功能都不受影响：登记和播放、在时间线上截取、人声分离、整段拉平、音高检索、标签整理，以及导出 WAV 和视频片段。

但很多高级功能依赖干净的人声和音素对齐，受到的影响可能很大：

| 情况     | 受影响的功能                                                                                                                                                               |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 没有分离人声 | 语音分析可以直接跑在原混音上，但有背景音乐或音效时，音素对齐的错误率会大幅上升，结果基本不能用。卡拍、节奏检索和 REAPER 的拉伸标记都建立在对齐结果上，会跟着出错。音高测量也容易被伴奏干扰，进而影响音高检索和自动定音。agent 的对轴、拆分多人字幕和声纹分组同样需要干净的人声。原本就是干声的素材（如游戏语音）不用分离。 |
| 没有字幕   | 没有台词段，就不能从台词批量建采样、搜索台词、按人物筛选，也做不了语音分析，因此卡拍、节奏检索、REAPER 的拉伸标记和只拉平元音都用不了。可以手动逐句输入台词，或者让 agent 用语音识别生成字幕；机器转写会有错字，时间戳可能会漂移，重要的句子需要手动修改。                                 |
| 不是日语   | 字幕可以导入，也可以按文字搜索和批量建采样。但语音分析目前只支持日语，所以卡拍、节奏检索、REAPER 的拉伸标记和只拉平元音同样用不了。agent 也用不了应用的对齐和读音分析能力。                                                                         |

## 已知问题

- Windows 下部分 agent（如 DeepSeek Harness）的受限沙箱会拦住本地命名管道连接，提示 Access denied。使用 Codex 以外的 LLM agent 时，目前建议在宿主中开启 **Full Access**。
- audio-mcp 首次转写需要下载模型（turbo 约 1.6 GB），需有合适的网络环境。CPU 转写长音频较慢，可以先提取短片段再分析。
- Windows 下 Alt 拖到资源管理器需先松开 Alt 再放。
- 更具体的未结事项见[路线图](docs/ROADMAP.md)。
- Skill 系统未经过精细打磨，导致 DeepSeek 这类相对低智能的 Agent 在本项目下处理复杂任务的表现可能还是较差。总之再次重申 MacOS + Codex(沙箱) + GPT 6.1 Sol 是本项目推荐配置，也是作者大部分时间下采用的配置。 Windows 下 DeepSeek Harness (Full Access) 的可用性在完成基础任务时已经很高，但是如字幕预处理以及采样选择的这类需要判断和组合工具的复杂任务效果不能保证。

## 问题反馈

问题和建议请[提交 issue](https://github.com/Axolyz/OttoSmasher/issues)，并附上系统版本、复现步骤和工作区 `Data/Logs/` 下的相关日志。

## 致谢

本项目使用了 [pydomino](https://github.com/DwangoMediaVillage/pydomino)、[pyopenjtalk-plus](https://github.com/tsukumijima/pyopenjtalk-plus)、[tsqyomi](https://huggingface.co/tsukumijima/tsqyomi-models)、[FCPE](https://github.com/CNChTu/FCPE)、[HiFiShifter](https://github.com/ARounder-183/HiFiShifter)、[OpenVPI](https://github.com/openvpi) 的 PC-NSF-HiFiGAN、[Rubber Band](https://breakfastquay.com/rubberband/)、[mpv](https://mpv.io/)、[FFmpeg](https://ffmpeg.org/)、[ONNX Runtime](https://onnxruntime.ai/)、[Electron](https://www.electronjs.org/)、[React Aria](https://react-spectrum.adobe.com/react-aria/) 和 [PyMSS Studio](https://github.com/pymss-project/pymss-studio)。完整清单和各自的许可见 [THIRD_PARTY.md](docs/THIRD_PARTY.md)。

## 许可

OttoSmasher 基于 [GPL-3.0-or-later](LICENSE) 发布，可以自由使用、修改和再分发；再分发时需要同样以 GPL 发布并提供源码。本程序不提供任何担保。

- 随包的第三方组件各有许可，相关文件在发布包的 `licenses/` 中。
- 模型权重是单独的组件。对齐、读音预测、音高模型为 MIT；拉平声码器 PC-NSF-HiFiGAN 是 CC BY-NC-SA 4.0，只能用于非商业用途，商业再分发前请删除 `Contents/Resources/models/flatten/`。

## 参与开发

该部分内容为开发者提供，普通用户可以跳过。

- 从源码运行、测试、打包：[DEVELOPMENT.md](docs/DEVELOPMENT.md)
- 开发约定（人和 AI 代理通用）：[AGENTS.md](AGENTS.md)
- 系统结构：[ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 现行决定：[DECISIONS.md](docs/DECISIONS.md)
- 计划：[ROADMAP.md](docs/ROADMAP.md)

## 友情链接

- [HiFiShifter](https://github.com/ARounder-183/HiFiShifter)（我要在这里催更一下拉伸标记功能，将在更新后第一时间适配）
- [HachiShifter](https://github.com/openhachimi/HachiShifter)（之后对人力 VOCALOID 工作流的适配会以这个项目为主要适配对象）

