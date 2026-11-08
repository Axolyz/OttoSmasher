# 核验证据与收尾

## 建立清单

保存 `subtitles.parse` 返回为 parsed.json，把原字幕备份作为输入，计划生成的文件不作为基准。在临时任务目录运行：

```sh
otto run /skill/scripts/review.py scan parsed.json task.json --input backup_original.srt --precision fine --goal "核完全部可疑边界和换人"
```

助手统计原文实际写法，不穷举所有惯例。按来源从每种模式抽例解释，关注独立名字行、dash 换人、读音括号和纯音效行。初始清单包含多行、标注待定／多人、重叠、极短句，这些只是候选；单行边界也可能错。

全片首尾筛查时先保存整轨人声 `exports.wav` 返回为 audio.json，再传 --audio-export audio.json。它只解码一次，用每文件相对阈值标出边界两侧仍有能量的位置，无 gap 也会列入。背景音乐可能误报，弱声可能漏报。其他工具或判断发现的候选通过 --extra-cases cases.json 加入，数组每项含 id、start、end、text、flags。仍按场景抽查正常项，能量筛查不等于完整质量检查。

## 逐项核验

导出整句及相邻上下文：

```sh
otto run /skill/scripts/review.py packet task.json cue:12 --asset-id TRACK_ID --directory /task/evidence
```

上下文包保留 WAV 坐标和映射，不表示已分析或已核。用 audio-mcp 看实际波形／能量曲线、核整句内容。尾音长、相邻句或归属不明时扩大上下文。完整句加减上下文转写可辅助核内容，识别差异和词时间本身都不能当边界。按需结合对齐或声纹。首尾都要看，没有静音也要比较相邻内容。

每项记录 status 为 kept／changed／uncertain，reason 解释，evidence 为 [{path, note}]；修正时另写原片秒的新 start/end 建议。身份未知不取消拆明确轮次的要求。不能用阈值脚本填满所有已核状态，生成上下文包也不等于核验。快速／标准明确实际核了多少，精细核完全部候选。

## 检查与写回

otto run /skill/scripts/review.py check task.json 检查输入指纹、重复项、证据文件存在和待核数。精细档剩 pending 时非零退出。核过仍不确定的继续明确保留。文件存在不能证明真的听过或判断正确。

只把确认的修改放进带版本的 `edits.apply` 批次，或在导入前用于生成最终字幕。修改后统一复查重叠、覆盖、名字及请求范围。不能一律按中点消掉重叠，只保留实际同时发言；不能固定 padding 扩所有句子。检查逐项分析结果并刷新受影响项，准备全绿不等于字幕质量达标。输入版本改变时创建新报告版本，不覆盖旧决定。
