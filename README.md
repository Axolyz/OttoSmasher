# OttoSmasher

本地日语音 MAD 素材工作站：无字幕原片导入、原生连续播放、音轨分离、采样截取与拉平、音素分析、统一音块/节奏检索，以及来源可追溯的导出。

## 启动

macOS Apple Silicon：双击 `启动助手.command` / `启动素材管理器.command`，或 `./otto ui library`。浏览器兼容页为 `http://127.0.0.1:18765/helper/`；libmpv 原生视频仅在 Electron 窗口内嵌入。

第一次安装：`./scripts/bootstrap.sh`，然后 `./scripts/setup_desktop.sh`、`.runtime/envs/core/bin/python scripts/setup_player.py`。环境、权重和媒体都留在项目本地，不修改全局 Python 或 shell 配置。

Windows x64：安装 Visual Studio C++ Build Tools，在 x64 Native Tools 终端进入项目运行 `powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1`；CPU 机器加 `-CpuOnly`。安装后双击 `launch-windows.cmd`。**Windows/CUDA 与原生窗口嵌入尚待实机验收**，不能视为已验证发行版。

## 当前功能

- 原片页：可选字幕关联、OP/ED 标记、整轨人声或 BandIt v2 三轨分离、连续浏览和截取。
- 采样库：性质筛选与文件夹分离；原声/卡拍试听、波形/音高、普通裁切、最终拉平、人工标签和导出。
- 统一语音检索：同一组音块条件，可不限节奏、严格匹配或按节奏相似度排序。普通查询不会运行模型或登记采样。
- 音素模型：narabas 默认，HubertFA、pydomino 备选。Yohane/Qwen 的模型与实现保留，GUI 入口暂时关闭。
- 工具与工作流页保留空状态。旧插件、分享、模型实验面板和 demo 已删除。

当前约束见 [CURRENT_REQUIREMENTS](docs/CURRENT_REQUIREMENTS.md)，部署和验证状态见 [实施记录](docs/SIMPLIFICATION_2026_09.md)。字幕清洗保持独立：[字幕预处理](docs/SUBTITLE_PREPROCESSING.md)，SubPlz 使用 `scripts/subplz`。

## 环境与数据

core 负责服务，统一 inference 负责 PyTorch/ONNX；播放器与独立字幕工具另计。设置中配置设备并运行环境检查。GPU 明确指定后，不自动退回 CPU。模型下载仅在显式安装时执行；失败时按错误中的准确网址、文件名和目录手动补齐。

不将环境、权重、原片或生成物加入 Git。删除登记与删除原文件不是同一操作；保存派生采样必须保持音源和原片时间映射。模型结果不代表人工确认。

## GitHub 构建

[Build desktop apps](.github/workflows/build-apps.yml) 分别构建 Windows x64 便携包与 macOS Apple Silicon App，产物在 Actions 中下载。包含基础运行库，不包含推理环境、权重或用户素材。当前为未签名的测试构建；完整边界、首次启动、推理安装与验收限制见 [分发说明](docs/DISTRIBUTION.md)。

## 许可

本项目采用 [GPL-3.0-or-later](LICENSE)。第三方运行库及模型各自遵从上游许可证。
