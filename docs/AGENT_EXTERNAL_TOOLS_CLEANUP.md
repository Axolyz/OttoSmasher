# 本轮生产任务的外部工具与清理

2026-10-26，会话 external-tool-cleanup。所有者要求列出本轮新增下载的外部工具并清除；本记录不改变开发阶段。

| 工具 / 模型 | 用途 | 清理结果 |
|---|---|---|
| Xenova/paraphrase-multilingual-MiniLM-L12-v2，revision 2c4055b12046f11709e9df2c122e59ffbdc2f900，量化 ONNX | 日中字幕文本候选匹配 | 权重、tokenizer/config 与 embedding-cache 删除；来源 manifest 另存 |
| mlx-whisper 0.4.3 / MLX 0.32.4 | 本地转写字幕疑点及候选语句，核对内容 | 临时环境与专用依赖缓存删除 |
| mlx-community/whisper-small-mlx，revision 45f3915923c7a79a5a5b5a7d909d39aeb0e5630e | 初步 ASR 与部分人声复核 | 模型删除，转写结果和来源 manifest 保留 |
| mlx-community/whisper-large-v3-turbo，revision a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb | 对疑点进行第二轮本地 ASR 复核 | 模型删除，转写结果和来源 manifest 保留 |
| Matplotlib 3.11.2 | 绘制波形、音高和频谱供检查 | 临时环境及专用绘图库依赖缓存删除；已生成图表保留 |
| Mido 1.3.3 | MIDI 读取工具，处理 p1.mid 的轨道/音高信息 | 临时环境与包缓存删除；MIDI 原件与分析记录保留 |
| RARLAB macOS ARM64 7.23 包内 RAR/UnRAR | 解压新补中文字幕的 RAR；原有解压器不支持这些包的压缩方法 | 解压工具目录和下载压缩包删除；字幕原件保留 |

专用依赖包括 MLX Metal、Torch、Numba/llvmlite、tiktoken、Matplotlib 的字体/图像处理库等。共享的项目依赖没有卸载；NumPy、SciPy、ONNX Runtime、tokenizers 等在本轮之前已属于应用环境。
本机 FFmpeg/ffprobe、原有 bsdtar/7zz、PyMSS Studio、应用的 pydomino/FCPE/拉平模型不是本轮新增外部工具，保留。audio-mcp 之前仅做过调研，没有安装。

## 验证与证据

- 36 个目标目录全部不存在，包括三个临时 uv 环境、三套模型、解压工具目录、句向量缓存及对应包缓存；另清理指向这些目标的缓存链接和专用包索引。
- 目标文件逻辑体积约 4.50 GiB，含环境/缓存副本；这不是精确的磁盘物理释放量。
- 主项目环境 37 个包版本与清理前一致；ottosmasher / numpy / scipy / onnxruntime / pyopenjtalk / tokenizers 导入通过。原有 setuptools 构建环境保留。
- 清理前计划、包版本、来源 manifest、实际结果在 dev-workspace/agent-tool-cleanup/（不进 Git）。
- 原视频、字幕原件、时轴变换、ASR 输出、图表、采样与导出均保留；没有调用应用写操作，没有直接访问生产数据库或 Library 内容。
- 清理后旧外部处理脚本仍可查阅，但重新运行对应模型/工具的步骤需要重新安装或下载。只依赖保存的时轴记录重放字幕不要求这些模型。
