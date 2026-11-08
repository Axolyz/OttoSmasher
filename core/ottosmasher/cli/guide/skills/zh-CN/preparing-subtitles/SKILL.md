---
name: preparing-subtitles
description: "为 OttoSmasher 准备字幕：清洗文字、跨版本对轴、拆说话轮次、识别说话人，或为无字幕素材打轴。用于 CC、双语、杂乱字幕及时间／说话人处理；已经符合要求的部分可以直接复用。"
---

# 准备字幕

为指定视频准备完全同名的 UTF-8 SRT，文字写实际说出口的内容，时间用原片秒。一条放一个人连续说的话；同时发言可重叠，未知名字留空。应用的解析和导入方式见 otto guide prepare。

## 开始前

读 otto guide workflow，选定范围和精度，沿用用户已有要求。按 otto guide audio 试好需要的音频工具。用 `tracks.separatedVocals` / `tracks.defaultFromSeparation` 查找和复用已有的人声，缺失时再分离。改字幕前留备份。

## 参考路线

1. 从开头、中间、结尾取代表音频，核对版本偏移和剪辑差异。见 references/retiming.md。
2. 清洗对齐文字，统计并理解当前来源的标注习惯。见 references/cleaning.md。
3. 将先后换人的条目拆开，再建立声纹参考。轮次确定后即可拆分，名字可以稍后补。见 references/speakers.md。
4. 核对首尾、换人疑点和重叠。精细档逐项留下保留、修正或待定的结论，其他条目按场景抽查。见 references/verification.md。
5. 检查最终解析结果后导入，按请求补采样，复用已有分析。导入后的小修正可直接编辑已有对象；收尾时查看逐项结果和搜索覆盖。

这条路线说明了先后依赖，工具和顺序可按素材调整。实验参数可以作为起点，换作品时结合实际声音重新判断。

## 只做其中一步

| 任务 | 引用 |
|---|---|
| 清字／解释 CC 标注 | cleaning.md |
| 对轴／其他版本字幕 | retiming.md 和 cleaning.md |
| 识别说话人 | cleaning.md 标注体检，再 speakers.md |
| 没有字幕 | no-subtitles.md |
| 可疑边界核验与批量收尾 | verification.md |

## 附带脚本

路径相对本技能目录。scripts/speaker_embed.py 计算声纹，供你分组和命名；scripts/audio_probe.py 让未接 MCP 的宿主调用 audio-mcp。字幕统计方法根据当前来源选择，用法见 references/verification.md。
