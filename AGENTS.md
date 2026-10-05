# AGENTS.md — OttoSmasher 新版开发规则

> 所有在本仓库工作的开发者（人或 AI 代理）都必须遵守本文件。`CLAUDE.md` 只是指向这里。
> 需求来源只有交接包：`~/Documents/OttoSmasher-Rewrite-Handoff/`（README.md、docs/01–19、fixtures/）。
> 架构见 `docs/ARCHITECTURE.md`，界面方案见 `docs/UI_PLAN.md`。

## 1. 禁区

- **不要打开**旧仓库 `/Users/a/Documents/OttoSmasher` 里的任何代码、文档、数据库、配置或数据，
  也不要打开 `~/Documents/OttoSmasher-Handoff-Archive-2026-10-03`。
  唯一例外：阶段 0 已从 `…/dist/OttoSmasher-1.0.0-models/models/` 复制了 pydomino、tsqyomi、features、flatten 四个目录（已完成，不要再碰）。
- 旧版没有兼容义务：不迁移旧数据，不参考旧的表结构、接口、文件布局。
- 不在旧工作区或任何非本项目目录里写东西。开发工作区是仓库内的 `dev-workspace/`（已在 .gitignore）。
- PyMSS Studio（`/Applications/Pymss Studio.app`，数据目录 `~/.pymss-studio`）只按 docs/14 §14.6 的 worker 协议调用，
  `download` 永远为 false；不修改它的环境，不替它装依赖。

## 2. 基线与提问

- 守住产品基线（交接包 docs/02 §2.6）：页面职责、交互意图、业务规则、默认处理与可配置项、算法与参数都按规格实现。
  页面内布局与交互是“半基线”，按 `docs/UI_PLAN.md`（所有者确认后的版本）实现。
- 想改变基线：按 docs/02 §2.7 的模板写提议，**等所有者确认**再动手。
- 规格没写清、互相矛盾、或实现中发现规格有错：**先问所有者，不要猜**。疑问记录在 `docs/QUESTIONS.md`。
- 技术定型（docs/14）不换：对齐只用 pydomino；文本前端 pyopenjtalk-plus + tsqyomi；音高 FCPE；拉平 PC-NSF-HiFiGAN；分离调用 PyMSS Studio。

## 3. 提交与授权

- 每个任务完成并通过相应验证后，在本地提交；**只提交与该任务相关的改动**；保护已有的未提交修改（不 reset、不覆盖别人的改动）。
- **推送、合并、发布必须等所有者明确授权。**
- git 提交身份只在本仓库本地配置（`git config user.name/user.email`，不用 `--global`）。

## 4. 环境隔离（全部在项目内）

- Python 用 uv 建项目内环境（`.venv/`）；uv 的缓存与托管 Python 也放在项目内（`pyproject.toml` 的 `[tool.uv]` 设置 `cache-dir`，
  `uv.toml` 设置 `python-install-dir`）。不改全局 Python/shell 配置，不做全局安装（不用 `pip install --user`、`brew install`、`npm -g`）。
- Node 依赖（如果用到）装在项目里的 `node_modules/`。
- 第三方二进制（libmpv、发布用的 ffmpeg/rubberband 等）由 `tools/` 下的脚本拉到 `third_party/`（gitignored），固定版本并校验 SHA-256；
  **首次拉取某个第三方二进制前，先向所有者说明文件名、来源与大小并获得同意。**
- 开发期使用本机已有的 Homebrew ffmpeg / rubberband 4.0.0（只调用，不改动）。

## 5. 不进 Git 的东西

媒体文件、模型权重、第三方源码与二进制、环境（.venv 等）、生成物（build/dist）、数据库与缓存、凭据。
`fixtures/` 是第三方版权内容：**原地引用（通过环境变量 `OTTO_FIXTURES` 指向交接包的 fixtures 目录），不复制进仓库，不进 Git，
不上传任何在线服务**（包括 ASR/LLM 服务）。单元测试用合成数据复刻同样的模式；需要对照真实素材时只记录文件名、行号与 SHA-256。

## 6. 验证纪律

- 优先单元测试和合成测试（交接包 docs/16 第三部分的做法），再用 fixtures 小批真实素材；**不全库跑模型**。
- “运行成功”不等于“质量好”；没有实测证据不宣称可用；“provider 可用”不等于“实测通过”。
- **Windows 上未实测的功能一律标为“未验收”。**
- 界面自动化或人工点击只补充自动化证明不了的东西；一轮足够的验证通过后就停止重复点击；**不要操作所有者正在使用的应用。**
- 只验收桌面原生应用（macOS arm64 先行，Windows x64 必须可用）。

## 7. STATUS.md（本地文件，已 gitignore）

维护仓库根目录的 `STATUS.md`，阶段结束或交接前必须更新，包含：
- 当前阶段目标；计划与进度；
- 验证命令与结果（注明版本、日期）；
- 未提交的工作；未知项；具体的下一步；
- 每项工作区分“本地实现 / 已验证 / 已提交”。

## 8. 阶段与汇报

- 阶段计划：0 方案 → 1 骨架 → 2 原片与播放闭环 → 3 准备链路 → 4 语音分析 → 5 拉平 → 6 节奏与卡拍 → 7 三大搜索
  → 8 采样库完善 → 9 画面与周边（含采样独立化，刚需）→ 10 Windows 与发布 → 11 附加（P2）。
- 每个阶段结束时停下来，给所有者一份验收清单（对应 docs/16 的条目、怎么运行、该看什么、已知问题），**等确认后再进入下一阶段**。
- 每次汇报说清：做了什么、怎么验证的、结果如何、还有什么没做或不确定。

## 9. 代码约定（阶段 1 起生效，细节随实现补充）

- 用户可见文案一律走文案资源（`src/ottosmasher/i18n/locales/<lang>/*.ftl`），不在代码里写死中文；后端错误返回“错误码 + 参数”。
- 每个时间值都要明确所属时钟（原片秒 / 资产局部秒 / 文件秒 / 采样显示坐标）；换算只走 `domain.mapping` 一处。
- 不静默回退、不静默降级、不静默替换（P6）；未知不是零（P7）。
- 算法按规格的【基线算法】/【基线参数】逐项复现，不顺手“优化”；改变结果的想法先写提议。
