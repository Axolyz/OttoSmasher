# 独立字幕预处理

本流程不导入新字幕、不重新运行音素、量化、音高或角色聚类。
原片和原 SRT 不改动。两套工具分别安装在 `.runtime/envs/sub-align` 与
`.runtime/envs/subplz`；来源与提交固定在
`dependencies/subtitle-preprocessing.sources.json`，Python 依赖分别锁定。

## 命令

首次安装或恢复环境：

```sh
./scripts/setup_subtitle_preprocessing.sh
```

复用 pymss 缓存并补充分离未覆盖的原片区间，生成同一原片时钟上的 16 kHz 人声输入：

```sh
.runtime/envs/core/bin/python scripts/preprocess_subtitles.py prepare
```

分别运行，可加 `--source-id <来源ID>` 处理一集：

```sh
.runtime/envs/core/bin/python scripts/preprocess_subtitles.py sub-align
.runtime/envs/core/bin/python scripts/preprocess_subtitles.py subplz
```

结果位于 `outputs/subtitle-preprocessing/<来源ID>/<工具>/`。`command.json`
保存可直接调用的上游 CLI 参数；`run.log` 保存上游诊断。已完成的输出可续跑跳过。
SubPlz 使用每集独立缓存，避免同名音频误复用其他集的识别结果。

## 清洗是文件转换，不是逐句调用 LLM

- SubPlz 直接读取原 SRT，评估上游对人物名、音效等非朗读文字的原生处理。
- sub-align 读取 `spoken.srt`。本批 12 集共用
  `configs/subtitle-cleaning/kemono-friends.json`，不逐集写正则。
- 本字幕格式中的圆括号用于人物、音效、语言说明、汉字读音。移除标注及音乐符号，
  保留汉字正文；支持一层嵌套括号。未处理的括号会标记，不能当作已确认的朗读文本。
- `cleaning.json` 逐行保存原文、清洗文本、移除内容、原行号和未解决标记。
- 新作品需选择/检查适用的字幕格式配置，不自动套用这部作品的规则。
- 纯非朗读行不交给 sub-align；恢复原文版字幕时保留其原时间，明确不是对齐结果。
- 只有输出行数和文字逐行一致时才恢复原始标注，生成 `preserved-text.srt`；
  上游若合并/拆分/改变文字，则保留原始工具输出，不猜测角色归属。

`input.json` 保留人声音频与字幕指纹、原片时间范围、参与合成的分离缓存指纹。
重叠缓存按固定原片时钟加权合成，不连接或删除时间区间；缺失覆盖报错，不使用混音补齐。
对齐只输出机器估计，不把文件生成成功当成边界准确的证明。结果不适用“完美对齐”标签。

日语音素强制对齐也应使用实际朗读文本。但本轮仅产出独立预处理文件，不改变现有
音素后端或历史分析数据；后续接入时可消费同一清洗产物。

手动下载的两个权重可统一导入并校验官方 SHA-256：

```sh
.runtime/envs/core/bin/python scripts/cache_subtitle_models.py /保存模型的目录
```

模型仓库、固定 revision、文件名和 SHA-256 位于
`dependencies/subtitle-preprocessing.models.json`。首轮已下载 WhisperX 所需的
NLTK `punkt_tab/english` 到 `models/subtitle-preprocessing/nltk_data`；运行器设置
`NLTK_DATA`，不修改用户的全局配置。部分片源容器时长比实际解码音频多 1 ms，
仅对不超过 10 ms 的连续尾端差异截去虚多的容器时长，并在 `input.json` 记录；
不补造声音，不允许内部覆盖缺口。

工具输出另汇集到 `outputs/subtitle-preprocessing/sub-align/` 和
`outputs/subtitle-preprocessing/subplz/`，文件名与原片一致。
