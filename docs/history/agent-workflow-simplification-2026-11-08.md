# 工作流改动复查与收紧

日期：2026-11-08，接续 [第一轮评估](agent-workflow-review-2026-11-08.md)。第一轮记录保留当时快照，下面记录按所有者补充意见做的调整。

## 方法与脚本的分工

真实字幕有各种格式和标注习惯。先理解当前来源，再决定怎样统计和核验；方法中的例子提供起点，应用的导入规则检查最终格式。机械代码负责数据契约、传输、数学换算和状态，内容含义、换人及声音质量由 agent 结合上下文判断。

固定候选规则会影响检查范围，因此撤回通用筛查助手，改为按来源选择临时统计方法。任务记录以方便继续工作为准。

## 新增机械部分的处置

| 部分 | 复查结论与处理 |
|---|---|
| review.py 的括号正则与 labelled/unlabelled 模式 | 删除。有限分类加上 app parser 的 line 筛选，可能漏掉尚未理解的输入；统计改为按来源选择方法 |
| 同一助手的 0.2 秒短句、10 ms 能量、分位数门槛和 40 ms 邻域 | 删除。这些阈值影响候选选择，适合在具体素材上试用和调整 |
| 同一助手的 cue ±1 s 音频包、证据清单和 check | 随助手删除。音频导出与换算用已有 exports.wav、Mapping，任务记录自行选择形式 |
| 字幕统计、拆行、边界和声纹指引 | 保留并调整。先读原文、样式和轨道，再用声音核实理解，按当前写法统计；起止和换人结合上下文判断 |
| speaker_embed.py | 本轮及上轮沿用原脚本。它接受明确时间段、输出向量及短片段提示，供 agent 分组和命名；补零用于满足模型最短输入 |
| audio_probe.py | 保留。传递指定的 MCP 调用，保存响应、错误和图片；用 SDK by_alias 序列化为标准协议字段 isError，模型沿用环境或请求选项 |
| LinkClient.iter_results 与 --wait | 合用一种分页实现，逐页保留全部成功和失败条目 |
| 公共 argparse 参数、BOM、JSON 与等待输出 | 保留公共参数覆盖修复、UTF-8 BOM 支持、JSON 传参提示和安静等待；进度由 --progress 开启，临时 session note 用于交互终端 |
| LinkClient.from_env 与 jobs.get | 复用同种运行实例发现规则；直接按 ID 查任务，解决最近 500 项窗口漏任务的问题 |
| jobs.summaries、会话创建物与 samples.metrics | 保留读取能力，复用现有任务字段、调度顺序、actor_session 和缓存有效性规则 |
| spectrum.get.frequencies | 保留，复用数学函数返回行中心频率，供解释 log/mel 数据 |
| Studio 模型缓存 | 保留嵌套文件身份及显式刷新，修复子目录新增文件后列表不更新的问题。stem 和模型管理继续由 Studio 提供 |
| flatten.alignmentIssue | 保留，给出既有不可用分支的原因；选项和算法沿用原实现 |
| flatten.preview | 删除包装接口及相应类型、测试。用已有 open、estimate 获取选区和缓存估算，提交时校验输入，成品另作试听 |
| flatten.submitMany 及重试分支 | 删除。不同参数的逐项任务用 otto run 组合 open / estimate / submit；共同参数继续用 submitBatch。worker 沿用原持久化格式；两接口均未发布 |
| 连接权限特判 | 撤回新增的 PermissionError 分支。公共说明改为中性文字，保留原始 reason；权限接法放在 README |
| Windows PATH 检测 | 按所有者说明作为旧开发版残留处理，撤回 where.exe 调用、辅助函数、字段、文案和专用测试 |
| 长菜单与缩放 | 保留共享弹层限高、内部滚动和原生缩放键。去掉额外的 [-4,4] 限制，沿用 Electron 范围 |
| 中英 separation 主题 | 并回 prepare 的既有分离小节 |
| 自动更新与清理 | 沿用原 skill 同步机制：移除未修改的旧内置文件，保留用户修改。日用资料和权限设置保持原样 |

## 文档与已知问题

README 中英版增加已知问题，记录 Windows IPC、外部音频工具成本和其他使用限制。按所有者反馈，Windows 上使用 Codex 以外的 LLM agent，目前建议由用户开启 Full Access；其他宿主的效果留待实测。

未实现的增强继续留在 ROADMAP。DECISIONS、ARCHITECTURE、用户说明和中英指南同步更新，现行接口以指南为准。

## 验证结果与后续

沿用现有 pytest、CoreProc、fake_studio、Vitest 和 Playwright 的相关测试。随功能撤回的测试覆盖已删除的助手、API 和 PATH 分支，原产品测试和缺陷回归继续保留。

本轮 pytest 104 项、Vitest 12 项、Playwright 3 项通过，API 目录、typecheck、i18n:check 和 git diff --check 通过。真实 audio-mcp 0.4.0 的 view／analyze 调用成功；首项文件缺失、次项成功时，逐项结果仍保存，最终退出 1。

Windows 实机、第三方宿主 Full Access、较低能力模型遵循、ASR 和真实字幕全流程质量留待后续验证。
