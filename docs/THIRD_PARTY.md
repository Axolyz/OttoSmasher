# 第三方组件与许可

OttoSmasher 本身以 **GPL-3.0-or-later** 发布（见 [LICENSE](../LICENSE)）。选 GPL-3.0-or-later 的原因：
随包的 Rubber Band（GPL-2.0-or-later）和带 libx264 的 ffmpeg（GPL）都要求整体以 GPL 兼容的条款分发；旧版也是这个许可（交接包 15 §15.9）。

本页是清单（2026-10-10，按当前锁定的版本）。发布包里会另附各组件的许可全文（阶段 10 打包时由构建脚本收集，放在程序目录的 `licenses/` 下）。

## 一、随应用分发

### 界面（Electron 与前端）

| 组件 | 版本 | 许可 |
|---|---|---|
| Electron（含 Chromium、Node.js） | 44.6.0 | MIT（Chromium 各部分的许可见 Electron 自带的 `LICENSES.chromium.html`） |
| React / React DOM | 19.3.0 | MIT |
| React Aria Components | 1.21.1 | Apache-2.0 |
| zustand | 5.0.15 | MIT |
| lucide-react（图标） | 1.52.0 | ISC |
| @msgpack/msgpack | 3.1.3 | ISC |

### 播放

| 组件 | 版本 | 许可 |
|---|---|---|
| libmpv（mpv 0.36.0 + FFmpeg 6.0，media-kit 的 video-full 构建，不含 GPL 编码器） | v0.7.3 | LGPL-2.1-or-later（阶段 10 复核，ROADMAP L8） |
| mpv 客户端 API 头文件 | 0.36.0 | ISC |

### Core（Python）

| 组件 | 版本 | 许可 |
|---|---|---|
| Python（python-build-standalone） | 3.12 | PSF-2.0 |
| NumPy | 2.5.3 | BSD-3-Clause 等 |
| SciPy | 1.18.1 | BSD-3-Clause |
| ONNX Runtime（Windows 用 onnxruntime-directml 1.24.4） | 1.30.0 | MIT |
| pyopenjtalk-plus（含 OpenJTalk、HTS Engine 与系统辞典） | 0.4.1.post9 | MIT；OpenJTalk / HTS Engine / 辞典为修改版 BSD |
| SudachiPy / SudachiDict-core（tsqyomi 的分词） | 0.7.0 / 20260723.1 | Apache-2.0 |
| tokenizers | 0.22.2 | Apache-2.0 |
| huggingface_hub、hf-xet（tsqyomi 的依赖；本应用不用它下载任何东西） | 1.33.0 / 1.7.0 | Apache-2.0 |
| msgspec | 0.22.0 | BSD-3-Clause |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| protobuf、flatbuffers（ONNX Runtime 的依赖） | 7.36.2 / 25.12.19 | BSD-3-Clause / Apache-2.0 |
| pydantic、PyYAML、httpx、anyio 等间接依赖 | 见 `uv.lock` | MIT / BSD / Apache-2.0 / MPL-2.0（certifi、tqdm） |
| pydomino 的 Viterbi 解码（从源码编译成本机扩展） | @4930396 | MIT |

### 媒体工具

| 组件 | 版本 | 许可 |
|---|---|---|
| FFmpeg / ffprobe（含 libx264、AAC、ProRes 编码器，用于视频片段） | 发布时选定 | **GPL**（带 libx264 的构建） |
| Rubber Band（命令行，R3 引擎，卡拍的保音高伸缩） | 4.x | **GPL-2.0-or-later** |

### 模型的非权重支持文件

| 文件 | 来源 | 许可 |
|---|---|---|
| tsqyomi v4 的 `tokenizer.json`、`metadata.json` | tsukumijima/tsqyomi-models @680596d | MIT |
| PC-NSF-HiFiGAN 的 `config.json` | ARounder-183/HiFiShifter @6432687 | MIT（HiFiShifter 仓库） |

## 二、不随应用分发

### 模型权重（由用户下载：设置 → 环境与模型）

下载前请看清许可；下载即表示你接受该模型的条款。

| 模型 | 用途 | 来源（固定修订） | 大小 | 许可 |
|---|---|---|---|---|
| pydomino `phoneme_transition_model.onnx` | 语音对齐 | DwangoMediaVillage/pydomino @4930396 | 20.9 MB | MIT |
| tsqyomi v4 `model.onnx` | 读音预测 | tsukumijima/tsqyomi-models @680596d | 70.7 MB | MIT |
| FCPE `fcpe.onnx` | 音高测量 | ARounder-183/HiFiShifter @6432687 | 41.3 MB | MIT |
| PC-NSF-HiFiGAN `pc_nsf_hifigan.onnx` | 拉平声码器 | ARounder-183/HiFiShifter @6432687（原作 OpenVPI） | 54.0 MB | **CC BY-NC-SA 4.0**：署名、**非商业**、相同方式共享 |

PC-NSF-HiFiGAN 的非商业条款是它不能和本应用打包在一起再分发的原因之一：GPL 不允许附加“非商业”限制。
用它拉平出来的声音用于商业用途前，请自行确认 OpenVPI 的条款。

### PyMSS Studio（人声 / 三轨分离）

独立的免费软件（[pymss-project/pymss-studio](https://github.com/pymss-project/pymss-studio)，AGPL-3.0）。
本应用只按它的 worker 协议调用（起一个子进程、传请求文件），不修改它的环境、不替它下载模型。分离模型由 Studio 管理，各有各的许可。

### 其他

- PyTorch：不需要。
- 测试素材（番剧原素材、字幕、歌曲、派生音轨）：第三方版权内容，只供本地开发使用，不在仓库里，也不随应用分发。
