# 软件分发与构建

## 三层边界

1. **公开 Git 仓库**：源码、前端锁文件、模型下载清单、测试、安装与构建脚本。禁止模型、媒体、字幕、数据库、本机配置、环境和缓存入库。`scripts/audit_release_source.py` 在上传和 CI 中检查路径、大小及常见凭据；它导出的 ZIP 明确只是源码。
2. **应用本体**：Electron、前端、Python core、独立无 torch 的 ONNX 运行库、ffmpeg/ffprobe、rubberband、libmpv 与原生适配器。GitHub Actions 在 macOS ARM64 和 Windows x64 分别编译和打包，输出 App ZIP / Windows 便携 ZIP。只使用全新 CI 环境，不打包开发者日常环境。
3. **模型与支持文件**：只分发 standard。包含 ONNX 原生扩展、pydomino 解码器、G2P 辞典、tokenizer、配置与适配代码，排除 ONNX 权重及外部权重数据。用户工作区的 `models/` 保存权重，程序的 `model-support/` 保存预置支持文件；首次使用仅复制缺失的支持文件。PyMSS Studio 仍由用户独立安装，程序不安装或修改其环境。


## 应用与用户数据

- `.app` / Windows 程序目录中的 `resources/software` 只读，包含源码与前端。
- Electron `userData/workspace` 保存数据库、缓存、模型；可用 `OTTO_ROOT` 指定已有工作区。默认不接管源代码安装版工作区。
- Python 用 `OTTO_CODE_ROOT` 读取程序，用 `OTTO_ROOT` 写数据，`OTTO_CORE_ENV` 定位基础媒体运行库，`OTTO_ONNX_ENV` 定位附带推理运行库。
- 首次运行将校验过的 conda-pack 基础环境释放到 `userData/runtimes/<构建ID>`，执行 `conda-unpack` 重定位；后续启动复用。Windows 对固定的 0.9.2 脚本应用一处兼容修正：先只读比较内容，需要修改时才打开写入，避免尝试写入正在使用但实际不需要修改的 Python DLL。替换规则保持上游实现，需要修改但无法写入时仍然报错。此步骤仅解包本机附带文件，不下载或安装模型。
- 应用默认服务端口 18766，源码版仍为 18765，避免二者误连。检查服务构建 ID，不能使用同一工作区的旧版服务冒充新版。
- 不清理用户创建的环境、模型与数据；旧版本运行库目前可在退出应用后手动移除，不在普通媒体缓存清理中混删。

## 构建与验收

工作流：`.github/workflows/build-apps.yml`，支持 `main` 推送、版本标签、手动触发。

每个平台执行：上传内容审计 → 安装 core → 前端与 Python 测试 → 编译 native addon → 打包 core/onnx/player 运行库 → electron-builder → 启动实际打包 App 的冒烟检查。Windows 原生模块还会在 Electron 宿主中先执行加载检查。打包检查清除开发环境的 PATH 和 Python/Conda 环境变量，在带中文和空格的独立路径运行，覆盖新库、API、ffmpeg、libmpv 音频、范围终点。CI 只提取清单锁定的模型支持文件（HubertFA 上游合并归档中仅保留配置/辞典），不打入推理权重，不执行真实语料全量分析。

Actions 的 Artifacts 保存 14 天；普通构建不创建 Release，带明确发布标记的提交按下述门槛自动发布。不申请签名。不将生成的 ZIP 再提交 Git，也无需用 Git LFS 存模型。正式版本可以将通过验收的应用 ZIP 上传 Releases，权重继续使用上游地址与校验清单。

本地构建需准备干净的 core conda 环境（安装当前项目依赖与 conda-pack 0.9.2），Mac 另需 `scripts/setup_player.py` 的 player 环境：

```sh
pnpm --dir desktop install --frozen-lockfile
pnpm --dir desktop build
python scripts/setup_player.py --build-only
python scripts/stage_app.py --core /path/to/clean/core --onnx /path/to/clean/onnx --player /path/to/player
pnpm --dir desktop exec electron-builder --config electron-builder.yml --publish never
python scripts/smoke_packaged_app.py
```

Windows 不传 `--player`，先从 x64 MSVC 环境执行 `scripts/setup_player.py`。

## 推理运行库准备

CI 从全新 conda 环境安装 `dependencies/onnx.in`：Windows 使用 onnxruntime-directml，macOS 使用 onnxruntime；两者不可同时安装。构建器通过固定 pydomino 上游源码编译无 ORT 依赖的解码扩展 `scripts/setup_domino_decoder.py`；前向推理统一走应用会话。`scripts/prepare_model_support.py` 按 SHA-256 清单准备非权重文件。源码安装 `setup_inference.py` 默认只装环境；只有显式 `--with-models` 才下载 tsqyomi。

`stage_app.py` 拒绝 torch/experiment 环境及资源中的权重，运行库归档排除 ONNX 文件；不复制本机工作环境作为正式分发。打包后的 CPU 路径应开箱可运行，模型文件与模型实测状态分别检测。CoreML 用 NeuralNetwork 格式兼容当前动态形状模型，DirectML 使用顺序执行、关闭 memory pattern 且同会话串行。设备设置冻结到任务；实际节点执行由 ORT profile 记录，不能用 provider 列表代替 GPU 实测。

1.0 发布包括完整的 standard ONNX 运行环境，须以此次 Actions 产物与检查结果为准。

## 明确的发行限制

- CI 冒烟检查不是 Windows/DirectML 实机验收，也不能证明视频嵌入、高 DPI、听感和模型质量。
- 首版产物未配置 Apple Developer ID / notarization 或 Windows 签名证书；不能声称已经通过 Gatekeeper / SmartScreen。Mac 签名公证与 Windows 签名应在正式发行阶段接入 Secrets。
- 项目采用 GPL-3.0-or-later，见根目录 LICENSE。Electron、Python 依赖、mpv/ffmpeg/rubberband 的许可证各自有效；正式二进制发行前还需要整理其许可及对应源码提供要求。模型遵从上游许可，不随 App 再分发。

## 1.0 发布流程

正式构建只使用 GitHub Actions。main 上明确带 `[release 1.0.0]` 的发布提交，在 macOS ARM64 与 Windows x64 两个任务全部通过后，由独立发布任务检查产物与启动报告。只有每个平台 ZIP 都严格小于 2,000,000,000 字节才创建 v1.0.0 Release 并上传应用及 SHA256SUMS；失败或超限不发布。不覆盖已有 Release。

本地 `scripts/package_models.py` 按现用模型清单逐一核验和压缩，支持文件有固定校验，不递归打包整个 models。产物在 dist，仅交给维护者另行分发，不随 Git 上传。

实际版本和构建结果见 GitHub Actions 与 Releases；旧 core 包冒烟证据不能当作 1.0 完整推理包的验收。
