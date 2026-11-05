---
name: preparing-subtitles
description: "为 OttoSmasher 准备字幕：清洗文字、修正时间、拆开两人条目、用声纹标说话人，或者在没有字幕时生成带时间的字幕。用于字幕杂乱、中日双语、CC 字幕、段的时间不准、要标说话人，或素材没有字幕时。字幕已经干净就不需要。"
---

# 准备字幕

目标：每个视频一个完全同名的 UTF-8 `.srt`，每条只写一个人说出口的话，时间准确。应用怎么读字幕见 `otto guide prepare`。下面的路径都相对于这个 skill 的文件夹。

## 推荐顺序

做完整流程时，放在同一轮做完，最后只产出一份字幕，因为后面的步骤依赖前面的结果：

1. 分离人声。
2. 核对这个版本的时间轴，修掉整体偏移，因为对齐要求窗口离语音足够近。读 `references/retiming.md`。
3. 把文字洗到只剩说出口的话，因为它就是对齐用的文字。读 `references/cleaning.md`。
4. 给说话人标注做体检。读 `references/cleaning.md`。
5. 拆开两人条目，因为声纹要求每段只有一个人。读 `references/cleaning.md`。
6. 对拆好的句子算声纹，标上说话人。读 `references/speakers.md`。
7. 写成一份最终字幕，检查后只导入一次。之后重新导入不会更新没变的段的说话人。

## 如果只要其中一部分

只读任务需要的部分：

| 任务 | 读 |
|---|---|
| 清理杂乱或双语字幕 | `references/cleaning.md` |
| 修正段或字幕的时间 | `references/retiming.md` |
| 字幕来自别的版本 | `references/cleaning.md`（“核对这个版本的时间轴”） |
| 标每句是谁说的 | `references/cleaning.md`（标注体检），再读 `references/speakers.md` |
| 给没有字幕的素材做字幕 | `references/no-subtitles.md` |

## 开工前

1. 用 `tracks.separatedVocals {"sourceIds"}` 查已有的人声并直接用。缺默认轨就用 `tracks.defaultFromSeparation` 设好。没有人声就先分离，因为拆字幕要听得清。
2. 按总览的要求检查音频工具。
3. 改字幕前都留一份 `backup_` 原件。同名的 `.ass` 可以留着。
