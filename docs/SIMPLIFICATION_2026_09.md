# 精简实施记录（2026-09-23）

## 已落地

- 工具与工作流保留空页及导航。移除插件安装/分享/设置/网页桥接/能力发现/组合执行/外部 worker 协议及示例，删除剧情发现、SAM、PANNs、CLAP、角色聚类、长元音/相邻音独立工具、旧 demo。
- OP/ED、DSP 声学属性和原片 BandIt v2 三轨分离移到核心接口；任务调度、媒体来源/时间映射、明确保存和审核标注仍保留。`processed_audio_assets` 继承原处理资产的身份，不依赖插件表。
- 执行了退休模型与专属环境清理，旧量化/试听缓存中嵌入的 MFA/SOFA 引用也已清理。逻辑文件大小合计约 **24.28 GB**；这是删除清单求和，不等同于 APFS 物理释放量。
- 原片、字幕、353 个现有采样及人工标签保留。退休模型结果不再出现在选择器；有其他有效结果就按 narabas、HubertFA、pydomino 选用。
- core + inference 已建立。另计播放器、字幕预处理、SubPlz 环境；统一模型环境无 MLX 包，pymss 显式使用 Torch。
- 同一音块编辑器提供不限节奏/严格节奏/相似排序。相似命中保留偏差、占格冲突、候选和作用范围；右键卡拍使用自身节奏，查询不运行模型。
- 删除短周期自相关辅助及慢放厌恶度；设置增加大数字惩罚度（默认1.0×，即0.045）。设置和算法版本进入索引身份；重建仅复用已有测量。
- Yohane 音节与 Qwen 字符/词独立时间层提供分析、定位、试听，不伪造音素、不参与原音素索引。

- 删除固定200句测试语料调度及旧 CAM++ 适配器；生产批处理只接受明确范围。CLI `analyze phones --json request.json` 使用 source_ids/material_ids 与 backends，默认 narabas；`samples search --json query.json` 和 `rhythm query.json` 共用 GUI 的统一查询协议。
- 已重投影327个采样的旧测量：969份模型投影就绪，11份因没有可继承音素/可量化元音明确失败，1份缺失；未重新调用任何分离或对齐模型。

## SAM 保存

Large 实体迁到 `/Users/a/Documents/SAM-Audio-Deploy/models/sam_audio/sam-audio-large`。四个文件迁移前后大小和 SHA-256 一致，checkpoint 为 14,861,356,211 字节，SHA-256 `ca55418b1d23e8c8a4dcc55f259d9801c8f79da0131a66e525d862c1289e3c4f`。

Base TV、Small TV 及 Hugging Face 实体留在独立项目；未重复下载，未清理独立项目环境/辅助权重。迁移证据：`data/maintenance/sam-relocation.json`。资源删除与缓存清理分别见同目录 `retired-resources.json`、`retired-caches.json`。

## 本机执行证据

统一环境：Torch 2.14.0、transformers 5.17.0、ONNX Runtime 1.30.0。Mac 自动设备：PyTorch MPS，ONNX CPU；ONNX 不支持 MPS，显式选择 MPS 会说明不支持而不静默降级。

| 路线 | 小批结果 | 说明 |
|---|---|---|
| narabas | 两句成功 | 一次初始化，初始化约5.0秒；逐句约0.5/1.6秒 |
| HubertFA | 两句成功 | 一次初始化；首次 ONNX 运行约88.7秒，第二句0.7秒，冷启动仍慢 |
| pydomino | 两句成功 | 整个进程约2.47秒；未加尾音修正规则 |
| Yohane | 两句成功 | 修正本机安装副本后初始化5.25秒，逐句1.40/0.27秒；原生音节 |
| Qwen3 | 两句成功 | 初始化约4.1秒，逐句3.21/0.73秒；原生字符/词 |
| FCPE | 短片成功 | 初始化0.17秒，3秒音频推理0.83秒 |
| 拉平 | 短片成功 | 总计约2.42秒 |
| Deux | 短片成功 | 首次总计52.1秒，含导入/初始化；不是整集耗时 |
| HyperACE | 短片成功 | 总计12.27秒 |
| BandIt v2 | 短片成功 | 总计50.6秒，官方8秒内部窗、1秒步长及TTA；宿主长片按60秒片段、2秒上下文串行执行 |

输入、原始结果、日志保存在 `data/validation/unified-inference/`；统一报告 `validation.json`。这些数字是执行/计时证据，**没有据此得出主观质量排名**。Yohane 另经真实 HTTP 任务接口验证保存和原生试听描述，未增加采样。

Python 217项测试、Node 7项测试、前端构建、Mac libmpv 编译均通过。真实 Electron/libmpv 范围测试覆盖非零媒体偏移、界面线程阻塞、短选区截停、循环及定位退出循环。测试没有重复完整 REAPER 验收。

## 安装与跨平台边界

- `scripts/setup_inference.py` 创建统一环境，应用固定第三方提交和必要补丁；Mac锁文件来自实际验证环境，Windows候选依赖另存，实际安装解析结果写入 `.runtime/inference.windows-x64.resolved.txt`。
- `scripts/prepare_models.py` 是显式安装入口；普通查询不会下载。直接文件下载最多两次；失败报告准确网址和放置路径。模型许可仍以各上游原始许可为准，不随发行包复制权重。
- Windows：`scripts/setup_windows.ps1`、`launch-windows.cmd`、`desktop/native/player_win.cpp`。原生 HWND + libmpv，沿用范围播放、字幕和任务取消接口；媒体依赖、中文路径与 DPI 代码已适配。
- `scripts/package_windows.py` 生成 `dist/windows/OttoSmasher/` 和源码安装 ZIP，仅含允许列表内的代码/说明，不带本机数据库、凭据、模型或环境。不是预装二进制发行版；安装后不要移动虚拟环境目录。
- **没有 Windows/CUDA 实机。Windows 安装、CUDA 推理、原生嵌入、高 DPI 和真实任务树取消全部未验收**。候选依赖不能冒充跨平台锁定成功。Mac 上也不能据测试输出声称音质优于现有模型。

参考：[PyTorch CUDA轮子](https://download.pytorch.org/whl/cu130/torch/)、[libmpv Windows构建](https://github.com/shinchiro/mpv-winbuild-cmake/releases/tag/20260923)、[Yohane](https://github.com/Japan7/yohane)、[Qwen3 ForcedAligner](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)。
