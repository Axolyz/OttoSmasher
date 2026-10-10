# 从源码运行、开发与测试

给开发者看的；普通用户看 [README](../README.md) 和 [用户使用说明](USER_GUIDE.md)。

- 开发规则：[AGENTS.md](../AGENTS.md)（环境全部装在仓库内、不进 Git 的东西、提交与授权）
- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)；界面方案：[UI_PLAN.md](UI_PLAN.md)，可点原型 [ui/prototype.html](ui/prototype.html)
- 阶段与遗留事项：[ROADMAP.md](ROADMAP.md)；规格疑问与所有者的决定：[QUESTIONS.md](QUESTIONS.md)
- 需求来源：交接包 `~/Documents/OttoSmasher-Rewrite-Handoff/`（不在本仓库）

## 准备环境（macOS arm64）

全部装在仓库内（AGENTS.md §4）：不用系统的 `uv` / `npm`，用 `tools/uv`、`tools/npm`，它们把缓存和安装目录设到仓库里。

```bash
tools/uv sync                                         # Python 3.12 与 Core 依赖 → .venv/
tools/npm install                                     # Node 依赖与 Electron → node_modules/
.venv/bin/python tools/fetch_third_party.py           # libmpv、mpv 头文件、模型支持文件、pydomino 源码 → third_party/（校验 SHA-256）
tools/uv run --with setuptools python tools/build_domino.py   # pydomino 的 Viterbi 解码扩展 → third_party/native/<平台>/
node tools/build-native.mjs                           # mpv 渲染桥（Electron 原生扩展）
```

开发期使用本机已有的 Homebrew `ffmpeg` / `ffprobe` 与 `rubberband`（只调用，不改动）。

**模型权重**放在工作区的 `Models/` 下；开发工作区是仓库内的 `dev-workspace/`（不进 Git）。
两种办法：启动后在 设置 → 环境与模型「下载缺少的模型」，或手动按 `core/ottosmasher/models/registry.py` 里的直链下载后放进
`dev-workspace/Models/<子目录>/`。四个文件共约 190 MB。

## 运行

```bash
OTTO_DEV=1 tools/npm start          # 构建并启动（开发模式：工具页有任务自检与 mpv 探针）
```

也可以在访达里双击仓库根目录的 `启动 OttoSmasher.command`。

## 测试

```bash
.venv/bin/python -m pytest core/tests                 # Core 单元与进程级测试
tools/npm test                                        # 前端单元测试（vitest）
tools/npm run typecheck                               # TypeScript 类型检查
tools/npm run i18n:check                              # 源码里没有写死的中日文、文案键齐全
tools/npm run e2e                                     # Playwright 驱动真实 Electron（临时工作区、静音输出）
```

- 真实素材（第三方版权内容，只在本地用，不复制进仓库）：设 `OTTO_FIXTURES=~/Documents/OttoSmasher-Rewrite-Handoff/fixtures` 再跑
  pytest 或 `e2e/real-*.spec.ts`；需要模型的测试另要 `dev-workspace/Models`。
- `OTTO_STRICT_API=1`：Core 核对每个命令的返回值与命令目录一致。
- Core 命令改了之后：`.venv/bin/python -m ottosmasher.api.catalog` 重新生成 `docs/api/commands.json` 与 `app/renderer/api/generated.ts`。
- 3 万条合成库的性能测试：`OTTO_PERF_WS=.cache/perf/ws .venv/bin/python -m pytest core/tests/perf -s`。

## 发布（阶段 10）

见 [ARCHITECTURE.md §14](ARCHITECTURE.md) 的分发方案：electron-builder 目录产物（macOS `.app`、Windows 便携目录）各打一个 ZIP（< 2 GB），
随包与不随包的组件见 [THIRD_PARTY.md](THIRD_PARTY.md)。
