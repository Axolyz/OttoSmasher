---
type: desktop-application
summary: 动画语音素材的字幕检索、分离、语音分析、采样、音高拉平与视频导出工作台。
tags: [audio, sampling, desktop, cli]
---

# OttoSmasher-Next

## Purpose and capabilities

本地动画语音采样与音 MAD 制作工具，提供 GUI 和供 agent 调用的 CLI。支持字幕检索、音轨分离、语音与音高分析、采样管理、拉平和音视频导出。

## Entry point

- 开发规则：`AGENTS.md`；本地开发状态：`STATUS.md`。
- 应用操作：`tools/otto guide`，再按需查询 `commands` / `describe`。
- 架构：`docs/ARCHITECTURE.md`；生产任务资料：`docs/PRODUCTION_ARTIFACTS.md`。
- 环境命令：`tools/uv`、`tools/npm`；开发工作区：`dev-workspace/`。

## Dependencies and limitations

依赖项目内 Python/Node 环境、媒体工具及模型；分离通过已有 PyMSS Studio worker 调用。模型与媒体不进 Git。Windows 功能未经实机验收的部分仍待验收。CLI 操作运行中的应用，不直接编辑工作区数据库。

## Location

规范路径为 `/Users/a/Documents/Workspaces/OttoSmasher-Next`。
原路径 `/Users/a/Documents/OttoSmasher-Next` 保留为兼容符号链接：已有素材引用、环境入口和历史脚本仍可能使用它。在这些引用完成迁移前不要删除链接。
