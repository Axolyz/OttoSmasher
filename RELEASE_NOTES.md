OttoSmasher 1.0.0 · standard

本地日语音 MAD 素材工作站。支持原片和采样管理、字幕分批取样、音素/音高分析、节奏与音高检索、截取、拉平、卡拍、外部回导及来源追溯。

- Windows x64 与 macOS Apple Silicon 便携应用，包含 Python、ONNX、媒体工具、播放器及非权重支持文件，不包含 PyTorch。
- ONNX 权重包单独分发。下载应用后按 README 放置模型；分离需另行安装并配置 PyMSS Studio 和其模型。
- CPU 为默认；设置中可选择 Windows DirectML / macOS CoreML，不能将 provider 支持等同于每个模型已完成硬件验收。
- 附件由 GitHub Actions 构建，发布前通过测试、独立工作区启动检查，且每个应用 ZIP 小于 2 GB。SHA256SUMS.txt 用于核验下载。
- 未配置 Apple Developer ID、公证或 Windows 代码签名。Windows GPU、系统 DPI 和不同设备上的主观听感仍需实际反馈；CI 冒烟通过不能替代这些检查。

安装和模型放置步骤见仓库 README。第三方软件与模型保留各自许可证。
