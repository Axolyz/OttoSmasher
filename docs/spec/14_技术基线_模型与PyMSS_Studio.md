# 14 技术基线：模型、PyMSS Studio 接入与已知技术约束

> 【所有者】“模型的选用以及 PyMSS Studio 的接入基本上是定型了，不需要换技术选型。”2026-10-04 又把对齐收敛为只用 pydomino。
> 本文件给出**足以独立重新接入**的契约：文件、版本、校验值、输入输出、前处理、解码和已知的坑。
> 标【定型】的不换；标【建议】的是旧版已验证的选择，换掉要用测试素材做听感和数值对比；其余技术自由选择（§14.10）。

---

## 14.1 定型清单

| 用途 | 选型 | 版本 / 修订 | 工作区内放置路径（建议，可自定） | SHA-256 |
|---|---|---|---|---|
| 语音对齐【定型】 | pydomino 音素转移模型（ONNX）+ 上游 C++ Viterbi 解码 | DwangoMediaVillage/pydomino @ `4930396642fdd85618884c7a209218a628fd3c34` | `models/pydomino/phoneme_transition_model.onnx`（21,937,113 字节） | `ce3f5d7cb39e4fec08ed0380338f10193d5e00b9d032277485fa862075191710` |
| 文本前端【定型】 | pyopenjtalk-plus（含 tsqyomi 读音预测） | `pyopenjtalk-plus[tsqyomi]==0.4.1.post9` | 随运行环境 | — |
| 读音预测模型【定型】 | tsqyomi v4（ONNX） | tsukumijima/tsqyomi-models @ `680596dd2ad2bad59ee5db3741e197cfce79f9b4`，子目录 `v4` | 权重 `models/tsqyomi/model.onnx`（用户放置）；`tokenizer.json`、`metadata.json` 随应用分发 | model `ea7e4f229a4ccb8e6bc0f7037b4dba1452ca794808eabc88b421aa7d62d5b9c8`；tokenizer `6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d`；metadata `829c60584ba33ca6a10fe3697ab62b0210398c93266f743e79b32d85497c9cd6` |
| 音高（F0）【定型】 | FCPE（HiFiShifter 提供的 ONNX） | ARounder-183/HiFiShifter @ `6432687173ae343ef0f2f824695650e877739ee0`，`backend/src-tauri/resources/models/fcpe/fcpe.onnx` | `models/features/fcpe.onnx` | `013b507acd406de122b61ee497300ac6be082511101bc2136b886e48d9737e5d` |
| 拉平声码器【定型】 | PC-NSF-HiFiGAN（HiFiShifter 提供的 ONNX） | 同上修订，`…/models/nsf_hifigan/pc_nsf_hifigan.onnx` 与 `config.json` | 权重 `models/flatten/pc_nsf_hifigan.onnx`（用户放置）；`config.json` 随应用分发 | onnx `c0d5d05b6cfe12e254c82adeed6e52a31449a2d1398e05e1d7234f7dbfd720bb`；config `c3c56efaa5abdf1862224ae8396b17680c78d0b95ab009a31ef5d2f873cf07c2` |
| 人声/三轨分离【定型】 | 外部 PyMSS Studio（用户自装，在 Studio 里配置环境、下载模型） | 观察到的版本 0.0.18（macOS） | 不随应用分发 | — |
| ONNX 推理【建议】 | ONNX Runtime；Windows 用 DirectML 版 | 旧版：`onnxruntime==1.30.0`（非 Windows）、`onnxruntime-directml==1.24.4`（Windows） | — | — |
| 保音高时间伸缩【建议】 | Rubber Band 命令行，R3 引擎 | 4.0.0（GPL） | 随应用 | — |
| 媒体处理【建议】 | FFmpeg / ffprobe（含 libmp3lame） | 旧版 9.0.1 | 随应用 | — |

下载直链（固定到上面的修订，**不要用同名的其他版本或 PyTorch 权重替换**）：

- pydomino：`https://raw.githubusercontent.com/DwangoMediaVillage/pydomino/4930396642fdd85618884c7a209218a628fd3c34/onnx_model/phoneme_transition_model.onnx`
- tsqyomi：`https://huggingface.co/tsukumijima/tsqyomi-models/resolve/680596dd2ad2bad59ee5db3741e197cfce79f9b4/v4/{model.onnx,tokenizer.json,metadata.json}`
- FCPE：`https://raw.githubusercontent.com/ARounder-183/HiFiShifter/6432687173ae343ef0f2f824695650e877739ee0/backend/src-tauri/resources/models/fcpe/fcpe.onnx`
- PC-NSF-HiFiGAN：`https://raw.githubusercontent.com/ARounder-183/HiFiShifter/6432687173ae343ef0f2f824695650e877739ee0/backend/src-tauri/resources/models/nsf_hifigan/pc_nsf_hifigan.onnx`（config.json 同目录）

规则：
- 权重**不随应用分发**、不进源码仓库；用户按 README 放到工作区 `models/` 下（不放进程序目录，不要出现 `models/models`）。应用可以提供“打开模型目录 / 检测”入口。
- 非权重的支持文件（tsqyomi 的 `tokenizer.json`、`metadata.json`，PC-NSF-HiFiGAN 的 `config.json`）**随应用分发**（旧版如此，与 15 §15.8 一致），加载时同样校验 SHA-256。
- **普通操作不触发下载**；模型准备是显式动作。下载失败要给出准确的网址和放置路径。
- 加载模型时校验 SHA-256（至少对 pydomino、tsqyomi、FCPE、PC-NSF-HiFiGAN 及其配置）；指纹不符明确报错。
- 文件就位 ≠ 推理已验证（见 §14.7 的实测证据）。
- 已退役、**不要再接入**：narabas、HubertFA、MFA、SOFA、Yohane、Qwen3-ForcedAligner、内置 PyMSS 分离、CDX23、BandIt Plus、SFC、AV-CASS、SAM、CLAP、PANNs、角色聚类、MLX 路径。

## 14.2 文本前端（pyopenjtalk-plus + tsqyomi）

- 调用：`pyopenjtalk.g2p_mapping(text, use_tsqyomi=True, normalize_mode="None")`（规范化由我们自己按 08 §8.2.2 先做，库内规范化关掉），
  得到音素序列以及音素与原文字符范围、词、读音（片假名）的对应。
- tsqyomi 的 ONNX 会话必须由应用统一创建（遵守 §14.7 的设备策略，**不允许 provider 回退**）；初始化时核对修订和 SHA-256。
- **坑**：pyopenjtalk-plus 0.4.1.post9 在导入时会去加载上游旧的读音模型；旧版通过补丁把这次导入改成延迟导入，并在构建时检查“导入时不加载任何模型”。
  新实现要保证：只加载 tsqyomi v4，不加载其他读音模型。
- 用户辞典：编译成 MeCab 用户辞典。每条 CSV 行（旧版格式，可参考）：
  `表记,"","",1,名詞,一般,*,*,*,*,表记,读音,读音,0/<mora数>,*`；编译到临时文件 → 加载验证 → 原子替换；辞典读音受保护。
- 所有对齐共享**同一次**前端结果（批量时一句只算一次）。前端结果的版本 = 前端算法版本 + 辞典版本 + tsqyomi 版本。

## 14.3 对齐：pydomino

- **输入音频**：16 kHz、单声道、float32（从资产按需解码与重采样；多声道取平均）。
- **ONNX 接口**：输入 `input_waveform`，形状 [1, N]；输出 `transition_logprobs`（[1, T, K]）与 `blank_logprobs`（[1, T]）；T 为 10 ms 帧数。
- **音素序列**：逐句转换 08 的结果——清音 `I/U` 改成 `i/u`（原大写另存；清音由上游 tokenizer 按自己的规则重新判定），`sil` 记为 `pau`；
  每句之后追加一个 `pau`（多句上下文之间靠它分隔），整个序列前面再加一个 `pau`，然后合并相邻重复的 `pau`（上游没有 pau→pau 转移）；
  以空格连接交给上游 tokenizer（它会在两端补 `pau`）。输出与送入序列比较时，同样按小写 i/u 比较（见 08 §8.3.2）。
  **重复元音不合并**。只能使用上游 `phoneme_transitions.txt` 里定义过的音素转移；遇到未定义的转移会报错（例如上游没有 `kw`、`gw`）——
  这种情况就是该项分析失败，按 08 §8.3.3 处理。
- **解码**：使用 pydomino 同一修订里的 C++ 实现（`PhonemeTransitionTokenizer` + `solve_viterbi`），编译成本机扩展（macOS arm64 与 Windows x64 都要能构建）。
  旧版的适配逻辑（建议沿用）：
  - 每个音素最少帧数 = **1**（10 ms；上游示例用 3——为了保留真实的极短音素）；若 `最少帧数 × (音素数 − 1) + 1 > 帧数`，自动降到 `(帧数 − 1) / (音素数 − 1)`；
  - 帧数 < 2 或音素序列为空 → 报错；
  - 输出为相邻接续的区间列表：第 i 个音素的结束 = `times[i] / 100` 秒，下一个从这里开始；最后一个持续到 `采样数 / 16000`。
- **线程**：默认即可（旧版 FCPE/声码器用 intra-op 2 线程）。
- **记录**：模型文件 SHA、解码器版本、最少帧数设置。
- 旧版参考输出（同一模型、同一前端在 YY1-01 人声轨上的结果）：`fixtures/reference/YY1-01_pydomino_fa_old_output.json`，可用于核对新接入是否得到相近结果
  （注意第一条的读音里混进了说话人「チトセ」，那是旧版括号清洗的 bug，正确的对齐文本应为「あなたってば何なの？おジャマします」）。

## 14.4 音高：FCPE

前端与 HiFiShifter 保持一致（线性插值重采样与 STFT）：

1. 单声道，**线性插值**重采样到 16 kHz（采样点数 = round(N × 16000 / sr)）；
2. 两侧各反射填充 432 点（太短时补零到至少 1024 点）；
3. 窗长 1024、步长 160（10 ms）、Hann 窗（numpy `hanning`，对称窗）；取幅度谱；
4. 乘以 Slaney 归一化的 mel 滤波器组（128 带，0–8000 Hz，n_fft 1024；等同 librosa 默认）后取自然对数 `ln(max(x, 1e-9))`；
5. ONNX 输入 `mel`，形状 [1, T, 128]；输出 latent [1, T, B]（B = 360）；
6. 解码：B 个 bin 的中心音分在 `1200·log2(32.7/10)` 到 `1200·log2(1975.5/10)` 之间线性分布（以 10 Hz 为基准）；
   每帧取 argmax 左右各 4 个 bin（共 9 个）按 latent 加权平均音分，F0 = 10 × 2^(音分/1200)；置信度 = 该帧 latent 最大值；
7. 帧时间 = (i × 160 + 80) / 16000 秒；能量 = 该 10 ms 内原始（重采样后）样本平方的均值；
8. “有声”= 置信度 > 0.05 且能量 > 1e-10；**可靠帧** = 有声 且 F0 > 0 且 置信度 ≥ 0.5（使用方统一判定）。

长音频分段：每段 60 秒、两侧各 1 秒上下文，结果拼回连续网格。所有 F0 测量路径（含音高检索索引）统一为各声道平均后线性插值到 16 kHz（10 §10.1，18 D42）；pydomino 输入另用多相重采样。

## 14.5 拉平：PC-NSF-HiFiGAN

`config.json` 关键值：`sampling_rate` 44100、`hop_size` 512、`n_fft` 2048、`win_size` 2048、`num_mels` 128、`fmin` 40、`fmax` 16000、`pc_aug` true。

渲染（每个声道分别做）：

1. 线性插值重采样到 44.1 kHz；长度不足 4 个 hop 时末尾补零到 4 个 hop；
2. 两侧反射填充 (win − hop)/2 = 768 点；2048 窗、512 步长、Hann 窗、幅度谱；乘 Slaney mel（128 带、40–16000 Hz、n_fft 2048）后取 `ln(max(x, 1e-9))`；
3. 第 i 个 mel 帧的时间 = (i × 512 + 256) / 44100；取最近的 FCPE 帧：round((t − 0.005) / 0.01)；
4. F0 赋值：处理区间内、有声、F0 有限且 > 0 的帧 → 目标音高（内部拉平的过渡段：MIDI 域按权重在原音高与目标之间插值）；
   **无声帧 F0 = 0**（无声部分不补音）；区间外的有声帧保持原 F0（反正会被掩码丢弃）；
5. ONNX 输入 `mel` 形状 **[1, 128, T]**（mel 维在前：幅度谱 [T, 1025] 乘滤波器组 [128, 1025] 后转置）与 `f0` [1, T]（Hz）；
   输出 `audio` [1, 1, N]（44.1 kHz），线性插值回原采样率。**注意 FCPE 的 `mel` 是 [1, T, 128]，方向相反**；
6. 采样域掩码拼接（区间外逐样本复制原音频；非整段模式两端 3 ms 线性淡化），检查非有限值。

目标音高的计算（11 §11.2）：可靠帧 MIDI = 69 + 12·log2(F0/440)，按置信度（下限 1e-6）加权取中位数（排序后累计权重达到一半的那一帧），再 floor(x + 0.5) 吸附半音；
音名用 `C C♯ D D♯ E F F♯ G G♯ A A♯ B` + 八度（MIDI 60 = C4）。

## 14.6 PyMSS Studio 接入契约

> 以下“Studio 侧”的格式来自对本机 PyMSS Studio 0.0.18 的只读观察，**不是 Studio 官方承诺**；新版要对格式变化做防御（未知字段忽略、缺字段报错）。

### 14.6.1 发现安装与环境

- **安装目录**：设置里可手动指定；留空时自动检测：
  - macOS：`/Applications/Pymss Studio.app`、`~/Applications/Pymss Studio.app`；
  - Windows：`%LOCALAPPDATA%\Programs\Pymss Studio`、`%LOCALAPPDATA%\Programs\pymss-studio`、`%ProgramFiles%\Pymss Studio` 等候选（Windows 默认路径**未实机验证**）。
  - 资源目录依次尝试 `<app>/Contents/Resources`、`<app>/resources`、`<app>`（给的是 `.exe` 时先取其父目录）；以资源目录下存在 `python/worker.py` 为准。
- **数据目录**：设置里可指定；默认 `~/.pymss-studio`（各平台相同）。
- **活动推理环境**：依次找 `<数据目录>/runtime-envs/active-runtime.json`、`<资源目录>/python-runtime/runtime-envs/active-runtime.json`；
  取其中 `pythonPath`（相对路径以该 JSON 所在目录为基准）。都没有 → 报“Studio 没有活动推理环境；请先在 Studio 中完成环境安装”。
  （本机观察：内置运行环境 `backend: "mlx"`、无 torch。）
- **模型目录**：`<数据目录>/settings/app.json` 的 `modelDir`，否则 `<数据目录>/models`。
- **版本**：macOS 读 `Info.plist`；其他平台可能未知。

### 14.6.2 调用方式

- 每次调用起一个**独立子进程**：`<Studio 的 python> <资源目录>/python/worker.py <命令> --payload <请求 JSON 文件路径>`。
  - 只使用命令：`list_models`、`infer`（`health`、`env_info` 可用于诊断）。
  - 子进程环境：`PYMSS_STUDIO_DATA_ROOT` = 数据目录；`PYMSS_MODEL_DIR` = 模型目录；`PYMSS_STUDIO_RUNTIME_ENVS_DIR` = 找到的 `active-runtime.json` 所在目录；
    `PYMSS_STUDIO_ACTIVE_RUNTIME_FILE` = 该 `active-runtime.json` 的路径；`PYTHONNOUSERSITE=1`、`PYTHONUTF8=1`；**删除** `PYTHONPATH`、`PYTHONHOME`。绝不复用或修改 Studio 的 Python 环境，不替它安装依赖。
  - stdin 关闭；stdout 每行一个 JSON 事件，**按 UTF-8 解码**（Windows 默认编码会坏掉日文/中文路径）；stderr 写日志文件。
- **事件**：`{"type", "requestId", "taskId", "timestamp", "payload"}`。用到的：
  - `models`：`payload.models` 为模型列表；
  - `task_started`、`task_stage`（`stage`：validating_input / loading_model / separating / writing_output …）、
    `task_progress`（`stage`、`message`、`done`、`total`）、`task_log`、`task_done`（`files`、`outputs`、`outputDir`、`outputFormat`）；
  - `error`：`{code, message, detail, recoverable}`，code 如 `MODEL_NOT_FOUND`、`MODEL_DOWNLOAD_FAILED`、`DEVICE_CONFIG_INVALID`、`INFERENCE_FAILED`、
    `INPUT_NOT_FOUND`、`INPUT_AUDIO_STREAM_MISSING`、`INPUT_MEDIA_UNSUPPORTED`。
- **失败判定**：退出码非 0，**或出现任何 `error` 事件**（批处理里单个输入失败时 Studio 仍可能以 0 退出）→ 整次调用失败，附错误内容和日志路径。
- **超时**：列模型约 2 分钟；推理按输入时长设置上限（旧版统一 2 小时）。
- **取消**：协议没有取消命令——结束子进程（及其子进程）即可；我们的任务取消必须连带结束它。

### 14.6.3 列出可用模型

- 请求 `{"modelDir": <模型目录>}`；从 `models` 事件取列表。只保留 `downloaded` 为真且 `supported` 不为假的模型
  （Studio 的 `downloaded` 表示权重、配置和辅助文件都齐全）。
- 每个模型：`name`、`aliases`、`configInstruments`（如 `"Vocals|Instrumental"`）、`targetStem`、`category` 等。
  **声部列表** = `configInstruments`，没有则 `targetStem`；字符串按 `/`、`|`、`,` 拆分，**保留原样大小写**。
- 选择：按 `name` 或 `aliases` 精确匹配（例：`becruily_deux` 是 `becruily_deux.ckpt` 的别名，声部 `Vocals|Instrumental`）；能力判断时比较小写。
- 结果可以短时间缓存（模型目录或 worker 变化时失效）。

### 14.6.4 推理请求

```json
{
  "model": "<Studio 规范名>",
  "tasks": [{"taskId": "input-0", "input": "<我们生成的输入 WAV 绝对路径>"}],
  "output": "<本任务输出目录绝对路径>",
  "outputFormat": "wav",
  "selectedStems": ["<所选声部；未选则全部实际声部>"],
  "device": "auto | cpu | cuda | mps",
  "deviceIds": [0],
  "download": false,
  "modelDir": "<模型目录>"
}
```

- `download` **永远为 false**（即使上层误传 true）。`deviceIds` 在选 CUDA 时传设置里的设备号（旧版漏传，Studio 总用 0）。
- 输入：由我们把资产选区解码成 PCM WAV（保持源采样率与声道）。
- 输出（观察）：默认按文件夹布局 `<output>/<输入名>/<输入名>_<stem>.wav`，WAV 浮点；`task_done.outputs` 是 `{path, stem}` 列表。
  我们只信任 `outputs` 里的记录，并核对：路径在本任务输出目录内且存在；**时长与输入一致**（按输出采样率，样本数差 ≤ 1）；所选声部全部产出；
  所有 `taskId` 都有 `task_done`。任何一项不满足 → 不登记任何结果。
- 推理前后各计算一次“模型指纹”（Studio 版本 + 活动环境 JSON + 模型权重/配置/辅助文件 SHA + worker 脚本 SHA），不一致 → 拒绝（模型在任务期间被改了）。
  模型文件取 `list_models` 记录里的 `modelPath`、`configPath`、`auxiliaryPaths`（缺的跳过）。
  指纹记录进资产来源；设备不计入复用身份。
- 输出文件和 Studio 日志保留在任务输出目录，便于排查；登记成功后把声部转成库内正式音轨（13 §13.3.2）。

### 14.6.5 模型能力的判定

- 人声模型：声部（小写）含 `vocals`。
- 三轨模型：声部经别名归一后同时含 对白（speech / dialogue / dialog）、音乐（music）、音效（effects / effect / sfx）。
- 原设置里的默认人声模型不在可用列表时，只提示“原选择 X 未在 Studio 中安装，请选择模型。”，**不自动替换**。

## 14.7 ONNX 推理设备策略

- **默认 CPU**。设置“ONNX 硬件加速”打开时：
  - macOS：CoreML Execution Provider，`ModelFormat = NeuralNetwork`、`MLComputeUnits = ALL`（MLProgram 格式实测编译失败）；
  - Windows：DirectML Execution Provider（设备号可设）；关闭内存模式（mem pattern）、使用顺序执行模式；
  - Linux：只用 CPU。
- 四类 ONNX 模型（pydomino、tsqyomi、FCPE、PC-NSF-HiFiGAN）共用同一策略和同一个会话工厂。
- provider 列表为 [加速 EP, CPU]：允许个别算子落到 CPU，但**请求的加速 EP 没有真正进入会话就报错**（不能整模型静默回退 CPU）。
- 设备设置在任务提交时冻结（13 §13.1.2）。
- **实测证据**：每个会话首次成功推理后，用 ONNX Runtime 的 profiling 统计各 EP 执行的节点数，记为“实测通过 + 节点分布”；失败记为“实测失败 + 原因”。
  按（模型文件、设备设置）保存；设置里显示（13 §13.4）。provider 可用 ≠ 实测通过。
- Windows DirectML 在真实硬件上**从未验收**；实测前一律标为未验收。

## 14.8 卡拍渲染：Rubber Band【建议】

- 旧版用命令行：`rubberband -q -3 -D <目标秒数（12 位小数）> <输入> <输出>`（R3 引擎、保音高、按精确目标时长）；输出再截/补到精确帧数。
- 每个“桥”单独伸缩，核心区逐样本复制（09 §9.5.2）；校验核心未被改动。
- 换成库调用或其他实现可以，但要通过：核心逐样本不变、起音落在目标拍（±1 样本）、桥两端无咔哒声、主观听感不劣于旧版。

## 14.9 已知技术约束与经验（不是要求，是踩过的坑）

| 主题 | 经验 |
|---|---|
| 播放 | Chromium/网页解码器无法可靠播放 HEVC Main10 + FLAC 的 MKV；旧版试过整集代理（首次 46 秒）、HLS 分片（要等转换、缓存累积），最终在 Electron 里嵌入 **libmpv**（mpv 0.41；macOS 用 NSOpenGL 子视图，Windows 用原生 HWND）。范围截停用 mpv 的结束点/AB 循环由引擎完成；外挂声部用外部音轨 + 音频延迟；字幕用 OSD 覆盖层画在画面内；关闭 mpv 自带字幕。原生视图在网页之上，要处理遮挡与裁剪。视频解码在 macOS 可用 VideoToolbox（实测为硬解 + 拷贝） |
| 原生视图 | 每 ~80 ms 按布局和缩放同步原生视图位置；被弹窗/下拉/抽屉盖住时隐藏；切页暂停；Windows 的旧接口不支持裁剪，部分可见时整块隐藏 |
| 时钟 | 播放状态约 50 ms 轮询一次，两次之间按速率插值；换源时用代次号丢弃旧事件 |
| Windows 路径 | 中文路径、空格、方括号；运行库解包要支持中文路径；子进程输出按 UTF-8 解码；长路径；符号链接需要特权（不要依赖） |
| 进程 | 取消要结束整个进程树；Windows 上不要用 `kill(pid, 0)` 探活（0 在 Windows 上是 CTRL_C_EVENT）；退出应用时任务的处理要两平台一致 |
| 打包 | 旧版用 conda-pack 打包运行环境，Windows 需要对 conda-pack 0.9.2 的重定位做兼容处理（只读比较，确需修改才写，上游变化则失败）；macOS 原生模块要去掉绝对 rpath 并做 ad-hoc 签名 |
| 服务连接 | 旧版是 Electron + 本地 Python HTTP 服务（源码 18765 / 打包 18766 端口），靠“工作区根 + 构建 ID + 代码指纹”避免连到旧服务；服务只接受本机 Host 与同源请求 |
| MP3 | 依赖 LAME/Xing 头做无缝解码；随机读取要预滚（旧版预滚 2 秒再丢弃）；编码延迟约 1105 样本（ffprobe 显示起点 0.025 秒） |
| 显示 | 所有者用 1920×1080、缩放 100%/125%；高 DPI 下原生视图的物理像素换算 |

## 14.10 可以自由选择的技术

- 应用框架（旧版：Electron + React + Ant Design 6 + WaveSurfer）、后端语言与进程模型（旧版：Python + FastAPI + SQLite + 多个 conda 环境）、
  数据库与存储格式、IPC/API 形式、任务队列实现、测试框架、构建与打包方式。
- 约束只有：满足 macOS arm64 与 Windows x64 桌面应用的全部功能（原生视频播放、拖出文件到 DAW、写 REAPER 剪贴板格式、调用外部 Studio 进程）、
  §14.1 的定型选型、15 的非功能要求。
- 不需要浏览器版；不需要 standard/experiment 双版本；不需要 PyTorch 运行环境（定型模型全部是 ONNX，分离在 Studio 里）。
- 进程模型与数据库要按“三大搜索”的性能目标规划（约 3 万条 × 3 秒采样，常见查询 30 秒内；15 §15.2）。
- 选界面框架和后端接口时要支持界面国际化（文案资源、错误码 + 参数、本地化格式化；15 §15.7）。

## 14.11 中文与英文采样（后续，留接口）

- 所有者明确项目之后会支持中文和英文采样，流程与日语相同（08 §8.9）。本节的定型清单**只针对日语**：
  文本前端（pyopenjtalk-plus + tsqyomi）和对齐（pydomino）都是日语专用；FCPE、PC-NSF-HiFiGAN、PyMSS Studio、Rubber Band 与语言无关。
- 新版应把“文本前端 + 对齐器 + 核心音素集合”按语言做成可替换的一组；新语言用哪个前端与对齐模型，届时由所有者另行定型，本轮不选、不接入。
