# 挑音色与拉平

## 先明确产物形态

乐器音源先确认要单个音／元音还是整句、目标音区、起音／持续段需求、每轨候选数。整句拉平仍有辅音和多次发音。拉平只改音高，不会自动切出一个元音，也不做响度归一。要单音时先定位元音、截取可用范围、核对发音，再拉平。即使从台词建采样会跳过 OP/ED，也可通过资产选区使用歌曲素材。

`samples.metrics {"ids"}` 读取已有 rmsDb、pitchSpread、voicedDuration 等指标；missing/stale 不是零。metrics.prepare 才会明确排入缺失测量。音频工具比较代表候选，音高和频谱数字不能独自证明音色适合。必要时临时副本做响度匹配试听，保留原产物。少量端到端样例符合要求后再批量创建。

## 打开、预览和提交

1. `flatten.open {"assetId", "start", "end", "entry": "single", "sampleId"}` 冻结资产局部范围，返回 token、默认值、alignment 和 alignmentIssue。alignment、inner、处理区间的时钟为输入局部秒，外选区起点为零。
2. alignmentIssue 解释缺段、分析不可用、窗口覆盖不足、冲突、音轨无人声角色。采样先看 speech.sample，再按需 speech.preview、speech.submit。不能为绕过缺分析而把用户要的元音处理换成整句。
3. `flatten.preview {"token", "options", "name", "sampleId"}` 校验输入和选项，返回缓存预估、输出时长、最多新建对象数。不跑模型或任务。不知道的目标仍为 in-job，证据不足仍为 insufficient。预览不创建对象，也不能保证声音好听。
4. flatten.submit 用同样参数提交任务，flatten.results 读逐项结果，flatten.rerunFailed 按原选项只重试失败项。

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

入口 detail/single/batch 的默认值见 otto describe flatten.open 和 settings.list。改范围不自动改定音。`flatten.submitBatch {"ids", "options"}` 保留共同 auto/edge 选项，不收 manual 或 inner；`flatten.submitMany {"items": [{"id": "sampleId", "options": {"range": "whole", "target": "manual", "manual": "C4"}}]}` 支持逐项选项，最多 500 项，一个任务逐条失败，rerunFailed 保留每个失败项原选项，不必改全局设置。

成功产物登记一条拉平音轨和一个 pitched 采样，带音高标签。相同音频可能复用，但显式保存每次都建采样。新建不能撤销；samples.ids/list 的 createdBySession 查创建物，再用现有删除预览和用户确认。先预览少量实验。完整返回结构用 otto describe 查。
