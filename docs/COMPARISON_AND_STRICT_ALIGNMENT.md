# Demo 0.4：200 句对照与整句严格卡拍

本轮使用现有 12 集素材，无需 MIDI。网页仍是分析 helper demo，桌面多窗口和 DAW 文件拖出未在本轮迁移。

## 固定共同测试集

`data/alignment/comparison-200-v1/manifest.json` 固定 200 个目标句：保留旧 24 句，补入 176 句；每集 16 或 17 句。清单与模型失败一起保存，不用替补样本抬高成功率。

相邻字幕间隔小于 1.15 秒时纳入完整邻句，上下文一起做人声分离和对齐。各模型共用同一版 pymss / HyperACE v2 人声，派生单声道 PCM16 输入（HubertFA/MFA/narabas 16 kHz，SOFA 44.1 kHz）。目标句按文本音素归属提取；MFA 按完整词序列归属，归属不确定时明确失败。上下文连接使用句号，避免 MFA 把相邻句拼成带下划线的单词。目标裁切前后留约 50 ms，受相邻语音边界约束；未裁切上下文始终保留，可点“前后文人声”复核。

选样包括 91 句文本密度较高候选、64 句长音候选、88 句鼻音候选、86 句促音候选、88 句多行字幕、50 句表达性标点候选。标签可重叠，均是选样线索，**不等于已人工确认快语速、喊声或真实停顿**。本轮排除重叠字幕，尚未覆盖多人同时说话的可靠分配。

2026-09-12 完整处理快照（单位：句）：

| 后端 | 成功导入 | 失败 | 待处理 | 含 <20 ms 音素 | 含 spn |
|---|---:|---:|---:|---:|---:|
| HubertFA | 200 | 0 | 0 | 169 | 0 |
| MFA | 168 | 32 | 0 | 7 | 44 |
| SOFA Test2_Plus | 200 | 0 | 0 | 177 | 0 |
| narabas-v0（修正 CTC 解码） | 200 | 0 | 0 | 198 | 0 |

MFA 32 次失败中，23 句未产出 TextGrid，8 句输出词序列不能无猜测地归属到上下文，1 句词跨越目标句边界。MFA 原始日志实际导出 177/200，再由归属检查拒绝 9 句。`spn` 和极短音素统计针对成功导入的目标句；不把未知字典词等同于可靠音素。

上述数字是运行与异常统计，**不是边界精度排名**。本轮没有人工参考边界；不能据成功率、音素数量或完整时间戳宣布新模型更准。尤其 narabas 的极短音素很多，需重点听检。

## 依赖和模型处理

- [SOFA Test2_Plus](https://github.com/Greenleaf2001/SOFA_Models/releases/tag/JPN_Test2_Plus) 是歌声训练检查点。保存对应 release 字典、hparams 和 SHA；使用 OpenJTalk 生成音素，按检查点词表验证，再送入 `NoneG2P`，不额外在每个音素之间插静音。检查点把 `cl/pau/sil` 映射到 SP，I/U 归到 i/u。这与逐假名套字典的前端不同，转换规则明确记录。权重限制商用。
- [narabas-v0](https://github.com/darashi/narabas) 使用官方 ONNX 发射结果。官方原始解码输出保存在 `upstream_baseline`；本地有序 CTC Viterbi 输出单独保存在 `phones`，处理 blank、重复标签、BOS/EOS。保留原始 `cl`。代码 MIT；权重未找到明确许可，本轮仅本地实验。
- HubertFA 保留原生 TextGrid 和 G2P，`cl` 与静音的合并限制仍然存在。MFA 保留原生 IPA、词和 TextGrid。
- `processing_provenance` 保存输入转换规则、派生音频 SHA、字典／符号表 SHA；模型 SHA、原文件指纹、分离人声 SHA 和上游版本随分析、方案及导出传递。
- 新模型使用 `.runtime/envs/sofa` 隔离环境，两个模型分进程顺序运行。Rubber Band 4.0.0 及动态库位于 `.runtime/rubberband`；当前安装脚本针对 Apple Silicon Mac，未验证 Windows。

```sh
.runtime/envs/core/bin/python scripts/setup_comparison.py
./otto compare --prepare
./otto compare --backend sofa
./otto compare --backend mfa --retry
```

已有原始结果默认保留（包括失败）；`--retry` 明确重跑指定后端全部目标。MFA 以完整批次运行，输入、词典和模型未变时复用已有批次；同一导入不重复创建分析或使方案失效。音频、人声、模型、日志、清单和导出均留本地，不进入 Git。

## 检索与严格卡拍是两个操作

检索仍采用原素材的有序对应、统一语音倍率和可调整长停顿。结果卡显示“点 1 ← 音 3 a i”；详情中查询块、节奏单元和原始音素共享颜色与编号。不猜测汉字到读音的逐字映射。

严格方案固定所有命中点，其余点按原顺序一对一放入同一种网格。网格候选为 1、1/2、1/4、1/8、1/16、1/3、1/6、1/12 拍；固定命中点可以不在该网格上。音块覆盖区不许额外起音，空白处可补点。所有原始节奏单元保留，包括查询前后的台词和负拍弱起。

有序动态规划考虑间隔改变、倍率跳变与位置偏移，真实长静音优先吸收伸缩。没有 0.5–2.0 的严格变形硬上限。搜索保留每层有限候选与最多 192 个状态，因此 `search_complete=false`，不能声称全局最优或证明所有无解。单句上限 128 个节奏单元，渲染上限 10 分钟。

去重后最多三种：原节奏优先、较疏规则节奏、三连音解释；若无不同解释，不补假方案。表格显示全部源点、目标拍、命中／自动标记及实际间隔倍率。**卡拍后零位置误差不回写原检索分数。**

## 周期和 mora 对照

对合并后的起点强度构造 100 Hz 包络，按连续语音段做约 2/4 秒窗口的 Fourier 与自相关分析。长停顿分段，不要求跨段相位一致；保留多个周期及半／倍速关系。不足四个起点、短到缺少重复周期时标记证据不足。分析对象是起点强度随时间的变化，不是音频 F0。

依据：[librosa Fourier tempogram 方法说明](https://librosa.org/doc/0.11.0/generated/librosa.feature.fourier_tempogram.html)。这里采用轻量局部包络实现，并非把 librosa 的音乐 BPM 估计直接当成语速真值。

读音和 mora 来自 OpenJTalk；只有音素序列可以可靠按顺序对应时才保存 mora 索引。不生成逐 mora 时间戳。`ちいい` 可为 3 mora、1 节奏单元，连续元音、ei/ou 和附着鼻音仍遵循原合并规则。促音计数可以影响相邻节奏单元之间的 mora 数，不凭计数新增起点。

三种模式共享同一渲染器：基础算法；周期辅助（默认）；周期＋mora 弱辅助。当前周期和 mora 用于**候选网格方案排序**，不是移动音素边界，也不重新做每个网格内部的 DP。弱项可能不改变最终顺序，界面允许出现相同方案。

## 严格音频、预览与导出

当前模型起点左右约各 8 ms 原声核心直接拷贝到目标采样帧，相邻起点太近则缩小核心。核心间采用 [Rubber Band 离线保音高伸缩](https://breakfastquay.com/rubberband/code-doc/classRubberBand_1_1RubberBandStretcher.html)，交叉淡化在核心外；确认的静音独立调整。前缀与后缀保留，负拍用文件前置偏移表示。

准确落位只保证**当前标记对应的原声音频位置**。模型若把元音起点找错，渲染器不会自动纠正。核心外音素结束边界是编辑映射估计，不是二次检测结果。原声样本核心相同也不代表强变速整体听感自然。

`plan_id` 标识保存的完整方案，内含 `analysis_id`、`rhythm_id`、模型／音频来源版本、全部源秒到目标拍映射、网格、形变量、辅助依据和原检索 witness。分析或人工分组改变后旧方案拒绝使用。

接口：

- `GET /api/alignment-backends`、`GET /api/alignment-comparison`、`GET /api/comparison-cues`
- `POST /api/cues/{id}/match`：在同句切换模型后重算原节奏对应。
- `POST /api/cues/{id}/quantization-plans`：独立生成严格方案。
- `POST /api/cues/{id}/preview`：`strict / strict_overlay / strict_rhythm` + `plan_id`。
- `POST /api/cues/{id}/export`：同一个 `plan_id`；不重新猜映射。
- `GET /api/cues/{id}/audio?variant=vocals&analysis_kind=sofa&context=true`：未裁切上下文。

无点击 WAV 预览与导出使用相同音频文件；严格导出另附 `diagnostic-clicks.wav` 纯点击轨，点击声和 TextGrid 使用渲染器返回的同一映射。原始近似播放保留作对照。

## 验证

自动测试覆盖真实 PCM 核心样本逐帧相等、脉冲、强变速、长静音、首尾与负拍、音块排除冲突、全部点顺序、方案去重、修改分组／分析后失效、重复 CTC 标签和 BOS/EOS、周期半／倍速及跨停顿相位、短句证据不足、长音 mora、共享上下文人声缓存、无模型／混音静默回退、预览和导出的样本一致性。

```sh
.runtime/envs/core/bin/python -m pytest -q
.runtime/envs/core/bin/python -m ruff check src scripts tests
.runtime/envs/core/bin/python scripts/verify_models.py
.runtime/envs/core/bin/python scripts/validate_strict.py
```

`outputs/validation-v04/` 保存真实素材的技术验证结果与试听索引。浏览器播放与导出链路验证不能代替主观听检，也不能作为模型精度结论。

本轮自动测试 55 项通过。真实素材验证涵盖 4 句 × 4 后端、29 个渲染方案，均检查输出 WAV 的原声核心样本与预览／导出文件一致性；2 个句子／模型组合在切换辅助算法后改变首选目标位置，其余可生成组合未改变。音块冲突和 MFA 归属失败作为反例保留。

浏览器验收：在本机页面切换同句四模型、三种辅助模式，播放严格音频／叠加节拍／纯节拍和完整上下文，验证导出成功。长句详情面板改为独立滚动，避免播放按钮被超长内容推到不可达位置。最终页面未记录 JavaScript 错误。
