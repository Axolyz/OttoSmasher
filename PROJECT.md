# OttoSmasher：项目入口与稳定约定

本文件保存代码不易表达的稳定边界及导航。当前任务、验证证据和下一步只维护在
本地 `STATUS.md`（不纳入公开源码）；产品细则见 [当前要求](docs/CURRENT_REQUIREMENTS.md)。
探索期报告不是默认阅读材料，也不能覆盖后续明确决定。

## 产品边界

- 本地日语音 MAD 素材工作站，帮助用户检索、试听、裁切、拉平、卡拍及导出，保留人工审核和来源追溯。
  没有字幕也应能完成不依赖文本的制作流程；字幕不是导入或取样的前置条件。
- Electron / Ant Design 同窗工作站为主要体验，保留音源和选区；浏览器是兼容入口。
  不再按早期 demo 或默认多窗口设计恢复界面。
- 不建设可分享插件平台；“工具与工作流”页保留空状态。独立字幕预处理和 SubPlz 不并入主工作流。
- 同一分支提供 standard / experiment 启动配置，共享工作区，任务完成或取消后才能切换。
  core 管服务；两版共用无 torch 的 onnx 环境，experiment 额外保留 inference/PyTorch 环境。
- 人声及参考轨分离统一调用用户安装的 PyMSS Studio worker，只运行已经下载完整的模型；不向 Studio 安装依赖，不静默回退内置分离。
- 未接入的新试验放在独立 AudioLab 仓库，每项目独立环境；公共下载缓存可共享，可写 site-packages 不共享。
- 内置 PyMSS、Yohane / Qwen 的实现与权重保留，源码在 archive，默认两版均不导入；只有开发者显式启用后才恢复。
  其他保留/退休模型及默认顺序以当前要求和实际入口为准。

## 不能破坏的约定

- 媒体身份、绑定资产、原片时间映射和派生关系贯穿试听、分析、裁切、保存和导出；不能静默换成原混音。
  声音处理和重新 FA 接收实际资产选区。原片整轨人声准备仍是显式兼容工作流，重新 FA 不触发分离、不换音源。
- 秒、音素、mora、感知节奏音块是不同概念。字幕边界可能有约 0.5 秒误差，不能冒充测量边界；
  字/词/音节级模型结果不能均分为伪音素。pydomino 不加人工猜测的尾音修正规则。
- 统一检索使用相邻、有序音块，先确定邻接再过滤；严格命中与近似排序要区分，未知特征不能充作零。
  普通检索不运行模型、不登记采样；参数细则直接查当前要求与 `speech_query.py`。
- 语音搜索保存完整排序结果、按列表面板高度分页，可固定为 20/50/100 条；有 BPM 只比较近快/近慢两种候选，按含原速偏好的综合分选优。搜索投影可重建，音素/F0 测量不是可随意清理的缓存。
- 日常生成音频使用共享 LAME VBR V0（最高算法质量）音轨，裁切保存区间，模型输入按需解码。用户已接受有损保存及复用压缩前既有测量；不宣称 MP3 与原 WAV 逐样本相等，不为压缩全库重跑模型。原片不转码，导出保持显式格式。
  显式存储迁移可以事务更新资产文件身份与局部偏移，保留采样/来源映射、人工版本和迁移记录；这不是普通编辑修改不可变分析的入口。日常预算不含原片、环境/权重、备份及开发验证副本。
- 模型结果不是人工确认，处理资产不是正式采样；明确保存才登记。
  虚拟文件夹已退役，采用保存筛选器、独立单标签范围与标签表达式的交集。普通裁切按明确轨道角色预填性质（人声=语音、音效=非调谐单音，冲突/未知=未分类），允许修改；不继承父采样性质，拉平只登记最终成品。
- OP/ED 排除标记绑定原片，影响显式字幕采样/批量分析，不禁止手动播放、分离和取样。
- 明确指定 GPU 后不静默降级；设备设置作用于后续任务。不要未经验证就去重或删除 CUDA/ONNX 动态库。
- SAM 模型属于独立的 `独立 SAM-Audio-Deploy 项目` 保存范围，不能随本项目缓存/退休资源清理。

- 字幕导入只登记标记；音效/台词采样独立预览并执行，保留导入记录与删除抑制。字幕采样默认前后各扩展 0.3 秒；标签仍保持原区间。
- 每原片可有多个人声/音效资产、各一个默认轨。同角色共享区段标签；更换默认轨只作用于后续采样，既有测量和采样不换资产。
- CPU 为默认推理。Windows 使用 ONNX DirectML、macOS 使用 ONNX CoreML NeuralNetwork，Linux 保持 CPU；六类模型共用设备策略。实测状态与 provider 支持分开显示，失败不得隐式整模型 CPU 回退。
- FA 原始与人工边界保留；元音/规范化 N 的有效范围是版本化能量派生，不以无 F0 或 CTC blank 判断静音，证据不足保留范围。
- 原片重新定位仅修改文件定位引用；不移动文件、不核对内容或时长、不新增已验证身份。保留既有资产、时间和分析。

## 代码导航（从相关入口追踪，不全库通读）

| 关注点 | 入口 |
| --- | --- |
| 数据库、工作区、核心 API | `src/ottosmasher/workspace.py`、`ui_catalog.py`、`sample_catalog.py`、`sample_api.py` |
| 主界面、采样详情、原片页 | `desktop/src/Workstation.tsx`、`Workspace.tsx`、`SourcesWorkspace.tsx` |
| 波形选区、播放、字幕 | `desktop/src/MediaTimeline.tsx`、`TimelineSelection.ts`、`NativeMedia.ts`；`desktop/electron/player.cjs`、`playback-range.cjs`、`subtitles.cjs`；`desktop/native/` |
| 原片准备、人声、OP/ED、音轨 | `src/ottosmasher/source_vocals.py`、`opening_scan.py`、`sound_assets.py`；`desktop/src/SoundTracks.tsx`、`OpeningMarkers.tsx` |
| 任务、对齐批处理、推理设备 | `src/ottosmasher/operation_jobs.py`、`job_worker.py`、`alignment_batch.py`、`inference_runtime.py`；`scripts/*worker.py` |
| 音块/节奏检索、命中及派生节奏 | `src/ottosmasher/speech_query.py`、`speech_hits.py`、`sample_rhythm.py`、`rhythm_index.py`；`desktop/src/RhythmSearch.tsx`、`SpeechHits.tsx` |
| 采样音源、裁切、拉平、缓存 | `src/ottosmasher/sample_audio.py`、`sample_ops.py`、`sample_flatten.py`、`cache_storage.py`；`desktop/src/StorageSettings.tsx` |
| 环境、模型准备 | `scripts/setup_inference.py`、`fetch_sources.py`、`prepare_models.py`；`dependencies/` |
| 打包、首次启动、发布检查 | `.github/workflows/build-apps.yml`、`scripts/stage_app.py`、`audit_release_source.py`、`smoke_packaged_app.py`；`desktop/electron/distribution.cjs` |

## 运行与发布入口、易错点

- 启动/安装见 [README](README.md)；当前基础应用分发、构建命令与验证范围见
  [DISTRIBUTION](docs/DISTRIBUTION.md)。测试入口：`tests/`、`desktop/tests/*.test.cjs`，前端构建为 `pnpm --dir desktop build`。
- `OTTO_CODE_ROOT` 是程序位置，`OTTO_ROOT` 是可写工作区，`OTTO_CORE_ENV` 是基础运行库。
  软件更新不能覆盖工作区数据；源码服务默认 18765，打包 App 默认 18766，构建 ID 用于避免误连旧服务。
- 源码 Python 服务不会随磁盘代码自动更新。`service_version.py` 在服务启动时快照代码指纹，
  `./otto ui ...` 检测到旧服务才安全重启 HTTP 进程；不能把新前端搭配旧后端的结果当成当前版本验证。
- Windows 原生模块要使用 Electron 的宿主链接/延迟加载设置；运行库解包要支持中文路径。
  conda-pack 0.9.2 的 Windows 重定位兼容处理见 `scripts/relocate_windows_runtime.py` 及其测试，不能跳过错误求通过。
- libmpv 负责范围截停，前端进度不能作为声音停止的精确依据。原生音频冒烟检查不能替代视频嵌入、GPU、高 DPI 或听感验收。
- 代码采用 GPL-3.0-or-later，第三方与权重各有许可；权重/环境可以作为构建附件，但不能因此进入 Git 源码历史。
  当前产物与未来推理包的区别、尚未确认的分发方案留在 STATUS，不把讨论中的提议当成已实现功能。

## 统一素材与编辑边界

- 四个核心概念是原片、声音资产、时间标注、采样。AssetSelection 使用资产局部半开区间，来源映射与采样显示坐标明确区分。裁切共享资产，处理创建资产，父采样删除不删除来源。
- 区段标签按 source/group/asset 明确范围与正长度交叠动态求值；采样本地标签不自动提升。处理后测量不能用来源测量冒充。
- 业务编辑统一导出、预览、事务应用和版本化撤销；常用时间/制作编辑以波形与表单为主，JSON 作为高级入口，不提供可写 SQL 或原始数据库控制台。
- G2P 保留重复元音，三模型共用 pyopenjtalk-plus/tsqyomi 与工作区辞典版本。仅允许改对齐文本、辞典与已有音素时间；不增删或改写音素标签，不从能量自动插音或裁辅音。
- 图片、同步视频与局部循环动画都是正式画面绑定，音频为主时钟。不同步动画不伪装成来源同步视频；PV 输出保留映射清单。
- 独立 F0 检索的结构、严格条件、近似漏检及验证命令见 [PITCH_SEARCH](docs/PITCH_SEARCH.md)。完成状态和尚未验收项只写入 STATUS。

- 搜索规则与已完成结果集合分开；固定结果成员/顺序持久化，任务和索引变化不自动搜索。独立版媒体、分析、后台任务分离，画面暂停时不得通过逐帧重复 seek 维持同步。

- 拉平弹窗冻结音源与外选区；首元音/N 起拉平包含之后有声辅音，旧 vowels 请求仍只处理元音/N。交界定音默认左侧，向内 100 ms，证据不足不自动换侧；预览不运行模型。
- 外部回导仅使用选区起点，按导入文件时长计算终点并核验实际资产边界，保留对应来源映射，不要求原选区等长。
