# 软件分发与构建

## 三层边界

1. **公开 Git 仓库**：源码、前端锁文件、模型下载清单、测试、安装与构建脚本。禁止模型、媒体、字幕、数据库、本机配置、环境和缓存入库。`scripts/audit_release_source.py` 在上传和 CI 中检查路径、大小及常见凭据；它导出的 ZIP 明确只是源码。
2. **应用本体**：Electron、前端、Python core、ffmpeg/ffprobe、rubberband、libmpv 与原生适配器。GitHub Actions 在 macOS ARM64 和 Windows x64 分别编译和打包，输出 App ZIP / Windows 便携 ZIP。只使用全新 CI 环境，不打包开发者日常环境。
3. **推理环境和模型**：统一 inference 与模型分别保存。应用不包含 PyTorch/ONNX 推理环境或任何模型；它们缺失时模型功能显示依赖缺失，不能把安装 App 等同于所有模型已准备好。环境与模型更新独立于软件更新。Qwen / Yohane 文件和实现暂保留，GUI 入口关闭。

## 应用与用户数据

- `.app` / Windows 程序目录中的 `resources/software` 只读，包含源码与前端。
- Electron `userData/workspace` 保存数据库、缓存、模型及 inference 环境；可用 `OTTO_ROOT` 指定已有工作区。默认不接管源代码安装版工作区。
- Python 用 `OTTO_CODE_ROOT` 读取程序，用 `OTTO_ROOT` 写数据，`OTTO_CORE_ENV` 定位基础媒体运行库。
- 首次运行将校验过的 conda-pack 基础环境释放到 `userData/runtimes/<构建ID>`，执行官方 `conda-unpack` 重定位；后续启动复用。此步骤仅解包本机附带文件，不下载或安装模型。
- 应用默认服务端口 18766，源码版仍为 18765，避免二者误连。检查服务构建 ID，不能使用同一工作区的旧版服务冒充新版。
- 不清理用户创建的环境、模型与数据；旧版本运行库目前可在退出应用后手动移除，不在普通媒体缓存清理中混删。

## 构建与验收

工作流：`.github/workflows/build-apps.yml`，支持 `main` 推送、版本标签、手动触发。

每个平台执行：上传内容审计 → 安装 core → 前端与 Python 测试 → 编译 native addon → 打包基础环境 → electron-builder → 启动实际打包 App 的冒烟检查。检查在带中文和空格的独立路径运行，覆盖新库、API、ffmpeg、libmpv 音频、范围终点。CI 不下载推理模型，不执行真实语料全量分析。

Actions 的 Artifacts 保存 14 天；默认不创建 Release，不申请签名、不自动发布。不将生成的 ZIP 再提交 Git，也无需用 Git LFS 存模型。正式版本可以将通过验收的应用 ZIP 上传 Releases，权重继续使用上游地址与校验清单。

本地构建需准备干净的 core conda 环境（安装当前项目依赖与 conda-pack 0.9.2），Mac 另需 `scripts/setup_player.py` 的 player 环境：

```sh
pnpm --dir desktop install --frozen-lockfile
pnpm --dir desktop build
python scripts/setup_player.py --build-only
python scripts/stage_app.py --core /path/to/clean/core --player /path/to/player
pnpm --dir desktop exec electron-builder --config electron-builder.yml --publish never
python scripts/smoke_packaged_app.py
```

Windows 不传 `--player`，先从 x64 MSVC 环境执行 `scripts/setup_player.py`。

## 推理安装

源码安装沿用 README。打包应用需要在对应平台上准备用户工作区的 `.runtime/envs/inference`、`vendor` 和 `models`；不能跨平台复制 Python 环境。设置 `OTTO_ROOT` 为用户工作区，再用附带 core Python 运行 `resources/software/scripts/setup_inference.py` 和 `prepare_models.py`，安装时需要开发工具和 Git。可直接复用同平台已有工作区，日常任务无需重新安装。这一版不提供模型下载 GUI 或依赖安装器。

## 明确的发行限制

- CI 冒烟检查不是 Windows/CUDA 实机验收，也不能证明视频嵌入、高 DPI、听感和模型质量。
- 首版产物未配置 Apple Developer ID / notarization 或 Windows 签名证书；不能声称已经通过 Gatekeeper / SmartScreen。Mac 签名公证与 Windows 签名应在正式发行阶段接入 Secrets。
- 项目采用 GPL-3.0-or-later，见根目录 LICENSE。Electron、Python 依赖、mpv/ffmpeg/rubberband 的许可证各自有效；正式二进制发行前还需要整理其许可及对应源码提供要求。模型遵从上游许可，不随 App 再分发。

## 本机验证记录（2026-09-23）

Mac ARM64 在独立的中文路径工作区通过了打包 App 启动、基础服务、ffmpeg/ffprobe、libmpv 原生加载和范围音频输出检查。范围测试使用实际 PCM 帧数，避免把合并后的播放进度事件误当作精确终点。Windows 工作流已配置，但尚未在 Actions 上执行；CUDA、视频窗口和高 DPI 仍需 Windows 实机验收。
