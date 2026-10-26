# Agent 生产实测：bug 修复记录

2026-10-26 汇总。范围是本轮 bangumi / 杏坛铭生产过程中修复的应用问题，不是全项目 changelog；不推进开发阶段。
此前已有独立 Git 提交、对应测试及部分 STATUS/生产报告记录，但没有统一索引，前两项在 STATUS 中缺少集中条目。本文件补齐索引，不把当时未记录的验证命令臆造为已执行。

## 既有修复

| 本地提交 | 使用时的问题 | 原因与修复 | 对应验证/证据 |
|---|---|---|---|
| 658c410 | 重试批量任务后，逐项结果不能正常恢复 | 重试只复制任务参数，未恢复逐项登记；新任务重建项目行，保留 skipped，不继承旧结果 | test_scheduler.py::test_retry_restores_batch_rows_without_old_results；提交含回归测试 |
| 2b83da3 | CLI 连接偶发在握手阶段失败 | 连接先加入广播集合，事件可能抢在 hello 前发送；改为先发送 hello 再注册广播 | test_agent_link_handshake.py::test_broadcast_during_hello_cannot_overtake_handshake；提交含回归测试 |
| ccd16b4 | 分离几集后磁盘耗尽，远大于 MP3 成品大小 | 成功任务留下输入/输出/转码中间音频；登记成功且 worker 退出后清理，旧成功残留纳入存储清理，失败证据保留 | 当时 scheduler/separation/storage 共 27 通过；生产重跑一集验证回收后恢复其余任务，65 集完成。STATUS 的 2026-10-25 记录 |
| ac551fe | PyMSS 分离任务显示 CPU，用户以为未使用加速 | 原显示取 ONNX 设置；改为显示该任务冻结的 PyMSS requested device，auto 不冒充实际后端，重试使用当前设置 | 当时 API catalog 9、TaskDrawer 2、typecheck/i18n/build 和独立 e2e/separation-device 通过；STATUS 2026-10-25 |
| 4d8c139 | CLI 读取 F0 / 频谱时无法 JSON 序列化 | 二进制 bytes 原样交给 JSON；按 schema 转 base64，Python LinkClient 仍返回 bytes | 当时 integration test_cli 7、unit test_cli_guide 4 通过，生产 measure.f0 smoke 通过；STATUS 2026-10-25 |

## 本轮：Opus 中途解码错位，导致片尾 F0 失败

- 症状：后台任务 d090f5da68954d95ba6f4acb85a7e036 的 f0.measure 状态 succeeded，但 f0=[]，f0Errors 中 chunk=23、range-invalid、duration=null。
- 素材：Bocchi the Rock 2022 S01E06-[1080p][BDRIP][AV1.OPUS].mkv，日语 Opus 原音频流；资产 02d1957347974511a5fe17bfaa396516。只读原视频，未修改媒体。
- 原请求：1379.000–1421.090 秒，48 kHz。全流 68,212,320 个样本，请求终点等于真实流尾，没有超范围。
- 根因：从中途启动 Opus 解码，首帧会重新扣除 pre-skip。此文件首个输出帧剩 648 点，而全流索引对应帧是 960 点。区间解码只按时间戳找帧，把实际首样本仍当成完整帧的起点，偏差 312 点（6.5 ms）。内区间得到晚 312 点的信号，片尾则少读 312 点并报越界；duration=null 来自解码长度检查，不代表资产没有时长。
- 修复：读取首个 ashowinfo 的 nb_samples，按索引帧长度与实际首帧长度差定位真正首样本。时间戳只用于找帧，不用毫秒精度时间戳估算采样点，也不补零或缩短请求。
- 自动验证：增加合成 Opus/MKV 内区间与整段解码逐样本相等的测试；覆盖 ffprobe 和峰值生成两条索引路径、精确 EOF 和真实越界。修复前新增 3 项失败，修复后 test_decode 全部 12 项通过。
- 原素材验证：修复后上述区间得到 2,020,320 个样本，与完整解码的相应切片逐样本相等；单独运行原失败 chunk 的 FCPE，f0Errors=[]，输出 4109×3 帧且全部有限，CPU provider 实测通过。只在 dev-workspace/agent-cli-review 写诊断结果，没有写生产测量库。
- 限制：这是通用区间解码修复，受影响的不仅是 F0。已有导出和测量不会自动重算；本轮没有全库重跑。应用主进程需由所有者重启加载修复。Windows 未验收。
- 现场证据：dev-workspace/agent-cli-review/f0-verification.json（本地，不进 Git）。回归测试进入本次修复提交。

## 尚未作为已修复项的观察

- F0 全部块失败仍可能外层 succeeded：原因是 worker 收集逐块错误并返回结果，调度器按正常返回结束；语音分析附带 F0 失败需要保留对齐结果，但独立 F0 任务的摘要语义值得改进。本轮不改变其状态规则，见根目录提案第 2 项。
- 长连接在长时间外部计算期间可能积压广播：此前采用短连接规避，未在本轮复现或修复。
- 字幕重新导入的替换范围与旧段残留：生产中通过编辑通道处理，尚未确认具体实现根因；提案第 3 项讨论接口语义。
- auto 最终选用的 PyMSS 计算设备：ac551fe 修的是显示来源，不是添加实际设备观测能力。

## 本轮集中复核

2026-10-26，macOS arm64，Python 3.12 / FFmpeg 9.0.2：

```sh
tools/uv run pytest core/tests/unit/test_decode.py core/tests/unit/test_peaks.py core/tests/unit/test_f0store.py core/tests/unit/test_search_service.py core/tests/unit/test_scheduler.py core/tests/unit/test_agent_link_handshake.py core/tests/unit/test_storage.py core/tests/unit/test_separation.py core/tests/unit/test_cli_guide.py core/tests/integration/test_cli.py -q --basetemp dev-workspace/agent-cli-review/pytest-related
```

64 项通过；覆盖本次解码修复和此前五项修复的相关后端/CLI 回归。没有重复运行此前的界面 e2e，未操作所有者界面。原素材 FCPE 验证是单独诊断调用，不是对生产数据库旧任务的重试。
