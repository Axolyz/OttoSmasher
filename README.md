# OttoSmasher（新版）

本地运行的音 MAD 素材工作站：从动画原片里检索、试听、截取、分离、拉平、卡拍台词和音效，再交给 REAPER 和视频软件。

- 需求来源：交接包 `~/Documents/OttoSmasher-Rewrite-Handoff/`（不在本仓库）。
- 开发规则：[AGENTS.md](AGENTS.md)
- 架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 界面方案（所有者已确认 v3.3）：[docs/UI_PLAN.md](docs/UI_PLAN.md)，可点原型 [docs/ui/prototype.html](docs/ui/prototype.html)
- 规格疑问与决定：[docs/QUESTIONS.md](docs/QUESTIONS.md)

当前阶段：**2 原片与播放闭环**（等待所有者验收）。

## 开发环境（macOS arm64）

全部装在仓库内（AGENTS.md §4）：

```bash
tools/uv sync                              # Python 3.12 与 Core 依赖 → .venv/
tools/npm install                          # Node 依赖与 Electron → node_modules/
.venv/bin/python tools/fetch_third_party.py # libmpv、mpv 头文件、模型支持文件 → third_party/（校验 SHA-256）
node tools/build-native.mjs                # 编译 mpv 渲染桥
```

模型权重放在开发工作区 `dev-workspace/Models/`（不进 Git）。

## 运行与测试

```bash
OTTO_DEV=1 tools/npm start                 # 构建并启动（开发模式：工具页有任务自检与 mpv 探针）
.venv/bin/python -m pytest core/tests      # Core 单元与进程级测试
tools/npm test                             # 前端单元测试
tools/npm run e2e                          # 用 Playwright 驱动真实 Electron（临时工作区，静音输出）
OTTO_FIXTURES=~/Documents/OttoSmasher-Rewrite-Handoff/fixtures tools/npm exec -- playwright test e2e/real-episode.spec.ts  # 真实素材检查（只读）
node tools/i18n-check.mjs                  # 源码里没有写死的中日文、文案键齐全
```
