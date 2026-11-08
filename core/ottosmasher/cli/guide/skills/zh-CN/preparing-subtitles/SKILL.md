---
name: preparing-subtitles
description: "为 OttoSmasher 准备字幕，清洗文字、跨版本对轴、拆说话轮次、识别说话人，或为无字幕素材打轴。用于 CC、双语、杂乱字幕及时间／说话人处理；字幕已符合任务要求时不用。"
---

# 准备字幕

每个指定视频交付完全同名的 UTF-8 SRT，文字为实际说出口的内容，时间用原片秒，一条对应一个连续说话轮次。同时发言允许重叠。即使不知道名字，明确换人仍要拆开。应用解析及导入行为见 otto guide prepare。

## 先明确任务约定

按 otto guide workflow 确认一次范围、精度和完成条件，沿用用户明确要求。发现并真实验证任务需要的音频能力，见 otto guide audio。通过 `tracks.separatedVocals` / `tracks.defaultFromSeparation` 复用已有人声，缺失时按需分离。改前备份字幕。计划前读对应引用，示例不穷举 CC 写法。

## 参考路线与必要依赖

1. 用开头、中间、结尾代表音频核对版本偏移和剪辑差异，读 references/retiming.md。
2. 清洗对齐文字，统计本来源实际 CC 标注写法，读 references/cleaning.md，保留数量与解释。
3. 先解决先后换人，再建立声纹参考；身份命名与轮次边界独立判断。需要补名字时读 references/speakers.md。
4. 筛查首端、尾端、换人不明和重叠，结合完整上下文按约定范围核验，读 references/verification.md。精细档每个可疑项都要有保留／修正／仍待定的结论。
5. 检查最终文件解析后导入，按请求补采样。复用已有采样和分析，核对逐项结果与搜索覆盖。导入后修正优先改已有对象，不把全部删除重建当日常修复方法。

路线描述必要依赖，不规定固定工具调用序列。材料需要时选更好的方法，保留它满足约定的依据。名字可待定，明确轮次仍应拆开。实验阈值不升级为硬规则，可疑信号不自动改边界。

## 部分任务

| 任务 | 引用 |
|---|---|
| 清字／解释 CC 标注 | cleaning.md |
| 对轴／其他版本字幕 | retiming.md 和 cleaning.md |
| 识别说话人 | cleaning.md 标注体检，再 speakers.md |
| 没有字幕 | no-subtitles.md |
| 可疑边界核验与批量收尾 | verification.md |

## 可复用助手

路径相对本技能目录。scripts/speaker_embed.py 算声纹，分类与命名由你判断。scripts/audio_probe.py 在宿主未接 MCP 时调用 audio-mcp。scripts/review.py 统计解析结果、可选音频筛查、导出上下文包并检查证据与漏项，不修改字幕或应用，也不能证明主观质量。用法与限制见 verification.md。
