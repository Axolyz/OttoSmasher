---
name: retiming-lines
description: "在 OttoSmasher 里修正台词边界：先粗对再用对齐精修，把外部工具的时间换回原片，并把大量修改合成一次撤销。用于段的时间不准，或分析结果看着不对时。普通的语音分析不需要。"
---

# 对轴

对齐器会把整句塞进给它的窗口，不会自己找这句话在哪。相关数字见 `otto guide primitives`。

## 修一句的边界

1. 用带词时间的转写（例如 audio-mcp 的 `audio_transcribe`）或音量起止，把边界粗对到 0.1–0.2 秒以内。
2. 用 `speech.align` 给出的首尾音素时间精修，它不会写入资料库。窗口前后各留 0.1–0.2 秒，并用分离后的人声，它比原混音稳定。
3. 把段写回去。

对齐结果里 `edges` 接近 0，或者某个音长得离谱（例如 0.8 秒的「ン」），多半是窗口没盖准，或者和别的台词重叠。

## 外部工具的时间换回原片

WAV 导出的结果带 `mapping`，是从文件秒到原片秒的折线。把外部工具给出的时间按它插值即可。
用 `otto run` 跑的脚本可以直接用应用的实现：`from ottosmasher.domain.mapping import Mapping; Mapping.of(m).to_source(t)`。

## 写回

- 改一段：用 `segments.get` 读版本号，再调用 `edits.apply`（实体 `segment`，字段 `start` / `end`）。
- 改很多段：把所有更新放进同一个 `edits.apply` 的 `ops`，一次提交，一次撤销。
- 删除一段：字段写 `{"deleted": true}`。

改了文字或边界的段，原来的分析会停用。除非设置 `analysis.auto_rerun_segments` 开着，否则要重新提交分析。

## 分析结果看着不对

先查这几个原因：字幕有错字、人声轨不对（原混音里有音乐）、段的边界不准。改好后重新分析。拿不准就导出音频听，或者看频谱。
