# 挑音色与拉平

## 先选一段合适的声音

做可按键演奏的乐器采样时，通常先从语音里选出单个发声音块或合适的元音片段，再拉平。结合想要的音色保留起音和持续段，边界由实际声音决定；整句可以用来找候选，成品选取其中适合演奏的范围。OP/ED 的歌曲也可以通过资产选区建采样。

拉平只改变音高，保留台词和时长：整句话即使变成同一音高，仍会有换字、辅音和停顿。用户要保留整句效果时可以整句拉平；做乐器单音时，先确认选区是需要的发声单元，再考虑音区和每轨候选数。

`samples.metrics {"ids"}` 读取 rmsDb、pitchSpread、voicedDuration 等缓存指标，缺失的用 metrics.prepare 计算。用音频工具比较代表候选；响度差异影响判断时，可以临时副本做等响比较。先完成几份样例，再批量处理。

`flatten.submit` 和 `flatten.submitBatch` 都可传 `localTags` 给新采样打标签，或传 `useCurrentProject: true` 在提交时加入桌面当前项目。重跑失败项时保留原任务的标签。

## 打开、估算和提交

1. `flatten.open {"assetId", "start", "end", "entry": "single", "sampleId"}` 冻结资产局部选区，返回 token、默认值、alignment 和 alignmentIssue。alignment、inner、处理区间用输入局部秒，外选区起点为零。
2. 对齐不可用时，alignmentIssue 给出原因。采样可先看 speech.sample，再按需用 speech.preview、speech.submit 准备 first／vowels 处理需要的音素。
3. `flatten.estimate {"token", "options", "sampleId"}` 读取缓存，返回处理区间和目标音。in-job 表示目标音将在任务中确定，insufficient 会说明还缺什么依据。
4. `flatten.submit {"token", "options", "name", "sampleId"}` 检查冻结输入并启动任务。用 `flatten.results {"jobId"}` 查看逐项结果，`flatten.rerunFailed` 重跑失败项。

## 选项

| 选项 | 含义 |
|---|---|
| range whole | 整个选区改音高，时长保留 |
| range vowels | 改元音和 N 的区间，需要可用音素 |
| range first | 从首个元音／N 起到选区结束，需要可用音素 |
| range inner | 内部平台与过渡，用输入局部秒 |
| target auto | 从处理范围内定音 |
| target edge | 从左／右交界定音，证据不足不换侧 |
| target manual | A4、C#5、B♭3 或 445Hz，纯数字含义不清会拒绝 |


入口 detail/single/batch 的默认值来自 flatten.open 和 settings.list，处理范围和目标音分别选择。`flatten.submitBatch {"ids", "options"}` 使用共同的 auto/edge 选项；不同手动目标音或内区，可以用 `otto run` 逐项调 open / estimate / submit，记下任务 ID 供查看结果。

每次保存会建一个带音高标签的 pitched 采样，并登记拉平音轨；相同音频可能复用。新建不在编辑撤销范围内，需要整理时用 samples.ids/list 的 createdBySession 查创建物，再走现有删除流程。拉平保持原有电平，响度归一另做处理。
