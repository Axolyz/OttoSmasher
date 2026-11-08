# 验证音频工具

## 先发现能力再求助

先找当前暴露的 audio-mcp 工具，没有时看 `otto setup audio --for other`。优先用宿主已有 MCP。CLI 的 view/analyze/timeline/melody 不必先配宿主 MCP；audio-mcp 0.4.0 的转写需要 MCP，字幕 skill 的 scripts/audio_probe.py 提供通用 stdio 客户端，不修改宿主配置也能调用。通过 otto guide preparing-subtitles 找到它的实际目录。

```sh
uv run /path/to/scripts/audio_probe.py requests.json results.json
```

CLI 先查当前语法，不能假定某个版本有转写子命令：
```sh
uvx --from 'audio-mcp[speech]==0.4.0' audio-mcp view --help
uvx --from 'audio-mcp[speech]==0.4.0' audio-mcp analyze --help
```

客户端把返回图片保存到 JSON 输出旁边并打印路径。要用图像查看工具打开这些图片；只读数值不算看过曲线。

对真实短片段跑一次 view，并验证任务需要的能力，字幕内容核对还需 transcribe。每项分别报告已验证／不可用／未测试。view 可用不代表转写可用。空转写只代表没识别出文字，不证明没有声音。

## 先准备短输入

用 exports.wav 导出短资产范围并保存 mapping，或对应用返回的明确原片路径用 ffmpeg 截取。把短文件交给 audio-mcp，避免整集加 start/end 仍先解码整集。内容核验需要整句和相邻上下文，极窄音素窗不适合 ASR。

初次会安装依赖，首次 turbo 转写可能下载约 1.6 GB。新下载的成本明显时先说明。已有完整模型缓存直接复用；确认缓存完整后才用 HF_HUB_OFFLINE=1。下载失败保留错误，检查网络／代理或用户认可的本地模型路径，正常续传。不擅自改全局代理或拼装未经验证的模型缓存。

缺能力时继续独立准备，只求助当前环境确实无法解决的部分。任务授权不代表可以绕过被拒的沙箱。otto status 检查应用自己的模型，不知道宿主的外部 MCP 服务器状态。

## 综合证据

波形和能量只能找可疑切点，不能辨认是谁、尾巴属于哪句。ASR 可核内容，但会漏尖声、幻觉，时间戳也有偏差。对齐器即使遇到错误声音也会把文字塞进窗口。结合真实曲线、原字幕、整句内容、相邻对白，按需加对齐或声纹。加减上下文做 A/B 可以辅助，ASR 输出变化本身也不能作为结论。
