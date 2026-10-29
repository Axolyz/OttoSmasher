# Production artifacts

2026-10-29 按个人工作环境架构，将完整项目迁至 `Workspaces/OttoSmasher-Next`。原目录保留兼容链接；媒体与应用存储随项目原样移动，没有直接编辑数据库或 Library 内容。

## 保留位置

生产资料留在已忽略的 `dev-workspace/agent-*` 中，保持脚本、输入、判断依据和输出的原有相对关系。这些目录是本项目的历史任务资料，不是跨项目临时文件收纳处。脚本中有历史路径和具体任务参数，不能视为通用工具直接重跑，尤其是导入、建采样和提交任务脚本。

| 目录组（省略 agent- 前缀） | 保留用途 |
| --- | --- |
| bangumi-subtitles、bangumi-jimaku | 字幕原件线索、清洗和匹配脚本、时轴变换与回放记录 |
| bangumi-audio-check、bangumi-finalize、subtitle-realign | ASR/音频核验依据、疑点处理、后续修正、导入记录 |
| subtitle-organize | 字幕原件归档位置和迁移清单 |
| antan-search、antan-search-2、antan-arrange、antan-samples | 候选筛选、编排与分离任务记录 |
| antan-finish、antan-midi、yuruyuri-jaan | 采样、音高与音色分析、拉平、人工验收用音频与结果 |
| xtm-video | 导出脚本与音视频对应记录 |
| separation-fixes、cli-review、tool-cleanup | Bug 证据、F0 验证和已移除外部工具的清单 |

逐目录文件数、体积和脚本列表见本地 `dev-workspace/agent-artifacts-inventory.json`。字幕原件的人类浏览入口仍为 `bangumi/下载字幕原件汇总.txt` 和各片源目录下的版本文件夹。用户要求保留的时轴变换原文件未清除。

最终交付的 `xtm3rd01/rap sample` 与 `xtm3rd01/inst sample` 属于用户创作工程，本次未移动。

## 临时产物与外部工具

`agent-cli-review/pytest-decode`、`pytest-related` 是可重新生成的测试产物，已迁到系统临时目录；具体位置记录在上述本地清单，可由系统清理。测试结论、修复代码和真实素材验证证据仍保留。以后一次性调试和测试产物使用临时目录，不继续加入历史生产资料。

本次检查 `/Users/a/.local/share/vault-study/` 的目录、工具文件及项目相关文本引用，未发现本会话的 OttoSmasher 脚本或产物，未动其他项目的资料。此前新增外部下载工具的清理记录见 `AGENT_EXTERNAL_TOOLS_CLEANUP.md`。

## 路径兼容与验证

保留旧路径兼容链接，避免破坏应用已存素材绝对路径、虚拟环境入口和历史记录。迁移后已验证旧路径解析、Python 包导入、`tools/otto guide` 和 Git 状态。没有启动或关闭用户应用，也未进行应用运行时验收。
