# AGENTS.md — OttoSmasher 开发规则

> 在本仓库工作的开发者（人或 AI 代理）都遵守本文件；`CLAUDE.md` 只是指向这里。
> OttoSmasher 是做音MAD 的素材工作台：Electron 界面 + Python Core + 命令行 `otto`。0.1.x 已发布（macOS；Windows 从 0.1.4 起发预览版），所有者在日常使用发布版。
> 本机私有的位置（素材、日常工作区、不要打开的旧目录）写在本地的 `AGENTS.local.md`（不进 Git）。

## 1. 文档地图

开工只需要读本文件和本地的 `STATUS.md`；其余的按需要查。

| 文件 | 回答什么 | 什么时候看 |
|---|---|---|
| `STATUS.md`（本地，不进 Git） | 现在在做什么、没提交的工作、等所有者定的事、下一步 | 每次开工 |
| [docs/DECISIONS.md](docs/DECISIONS.md) | **现在有效的产品与开发决定**，按主题；每条带日期与原始记录 | 改行为、做新功能、拿不准“该怎样”时 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 系统是怎么搭的：进程、代码结构、数据模型、存储、媒体、任务、分发、命令行 | 动到相关部分时 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 准备环境、运行、测试、发布、开发版与发布版并存 | 跑起来、测、构建时 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 当前版本、接下来做什么、未结事项（L 编号） | 挑活、收工时 |
| [docs/spec/](docs/spec/README.md) | 原始需求规格（交接包 01–19，原样）；“规格 06 §6.2”“R4.4”“S11.3”“P6”这类编号 | 查某条规则的原文与数值例子 |
| [docs/history/](docs/history/README.md) | 开发期的过程记录（问答、阶段计划、旧界面方案、原型），只追加不改 | 查旧编号（Q、D、L、阶段、UI_PLAN §）的出处；动对轴或说话人识别前读 `retiming-and-speakers-research.md` |
| [docs/user/](docs/user/README.md)、README、`core/ottosmasher/cli/guide/` | 给用户和 agent 看的说明（写法见 DECISIONS §12） | 改了用户看得到的行为时同步改 |

**冲突时的优先级**：所有者最新的明确答复 ＞ DECISIONS ＞ spec ＞ 现在的应用 ＞ 开发者判断。
发现下位文档和上位冲突，顺手改正下位（spec、history 不改正文：在 DECISIONS 里写清楚）。界面以**现在的应用**为准，旧原型和 history/UI_PLAN 只作出处。

**新代码怎么引用出处**：决定写 `DECISIONS §主题号`，原始需求写 `规格 NN §x` 或 R/S/P 编号，架构写 `ARCHITECTURE §x`，未结事项写 `ROADMAP Lnn`。
代码里已有的旧引用（`QUESTIONS「…」`、`UI_PLAN §x`、`阶段 N`）都能在 history 里查到，不用批量改。

## 2. 工作流程

- **开工**：读本文件 → 本地 `STATUS.md` → `git status`（工作树里可能有别人没提交的修改：保护它们，不 reset、不覆盖）。
- **日常的修 bug、已经定了的事**：直接做，做完验证、本地提交，给所有者一份能照着检查的清单。
- **改变产品行为或基线**（页面职责、交互意图、业务规则、默认处理、算法与参数，见规格 02 §2.6）：先写提议（改什么、为什么、影响什么、几个方案和推荐；规格 02 §2.7 的模板），**等所有者确认**再动手。
- **规格没写清、互相矛盾、或发现规格有错**：先问所有者，不要猜。
- **收工**（会话结束、做完一件事）：
  - 更新本地 `STATUS.md`：只写现在（在做什么、没提交的、等所有者定的、下一步），控制在一屏；做完的事不往里堆，提交说明就是记录。
  - 所有者定了新规矩 → 写进 DECISIONS 对应主题（日期 + 原话要点）；取代了旧决定就直接改那一条。
  - 发现了做不完的事 → ROADMAP §3 加一条 L 编号；结了就删。
  - 改了架构 → 同步 ARCHITECTURE 对应一节（章节号不变，代码注释引用它）。

## 3. 提交与授权

- 每件事做完、验证过就在本地提交；**只提交与这件事相关的改动**。提交说明用中文，写清做了什么、为什么、怎么验证的。
- **可以随时推任何分支（包括 `main`），不用逐次问**（所有者 2026-11-03）；不用 `--all` / `--mirror` / `--tags`，标签只在发布时推这一版的。
- **构建发布包、发 GitHub Release 也一样：所有者明确说要构建 / 要发布才做**；发布由开发者用 `gh` 完成，步骤见 DEVELOPMENT「发布」。
- git 提交身份只在本仓库本地配置（`git config user.name/user.email`，不用 `--global`）。

## 4. 环境隔离（全部在项目内）

- **Python 一律用 `tools/uv`**（例如 `tools/uv sync`）：托管 Python 装到 `.uv-python/`、缓存放 `.uv-cache/`、环境放 `.venv/`，并禁止往 `~/.local/bin` 写可执行链接。
  直接用系统的 `uv` 会写到用户目录。不改全局 Python/shell 配置，不做全局安装（不用 `pip install --user`、`brew install`、`npm -g`）。
- **Node 一律用 `tools/npm`**（例如 `tools/npm install`、`tools/npm run build`）：npm 缓存、Electron 二进制、node-gyp 头文件、Playwright 浏览器都放在仓库内 `.cache/`。
  npm 11 只运行 `package.json` 的 `allowScripts` 里批准过的安装脚本（目前是 electron、esbuild）。
- 原生扩展、pydomino 扩展、第三方二进制（libmpv 等）的拉取与编译见 DEVELOPMENT「准备环境」；都固定版本、校验 SHA-256（`tools/third_party.json`），产物在 `third_party/`（不进 Git）。
  开发需要的依赖可以直接装（所有者 2026-10-05），仍然只装在项目内。
- macOS 开发期用本机 Homebrew 的 ffmpeg / rubberband（只调用，不改动）；发布包和 Windows 都用 `third_party/media-tools` 里固定版本的。

## 5. 不进 Git 的东西

- 媒体文件、模型权重、第三方源码与二进制、环境（.venv 等）、生成物、数据库与缓存、凭据、本地的 `STATUS*.md` 和 `AGENTS.local.md`。
- **测试素材（规格里的 `fixtures/`、所有者的原片）是第三方版权内容**：原地引用（环境变量 `OTTO_FIXTURES`），**不复制进仓库，不进 Git**。
  单元测试用合成数据复刻同样的模式；需要对照真实素材时只记文件名、行号与 SHA-256。
- **开发时可以把真实素材发给在线服务**（ASR/LLM、云端机器、远程调试用的电脑等）：所有者 2026-11-03 撤销了原来“不上传任何在线服务”的禁令。真实素材测试不放云端（合成测试覆盖了逻辑，传输不划算）：平时在 Mac 上跑，Windows 首发前在所有者的电脑上跑一次（开发者判断，所有者 2026-11-03 同意）。
  应用给用户的 agent 说明书里同样**不写**禁止外发的规定，用户的数据由用户自己决定（DECISIONS §12）。

## 6. 验证纪律

- 先单元测试和合成测试，再用真实素材小批验证；**不全库跑模型**。怎么跑见 DEVELOPMENT「测试」。
- 提交前跑和改动相关的测试，e2e 只跑相关的文件；动到 Core 命令、文案、界面时跑对应的目录检查、`i18n:check`、typecheck。
- **全量 e2e 只在正式更新版本号之前跑**（所有者 2026-11-04），一般提交不跑，汇报里说明跑了哪些就行。
- “运行成功”不等于“质量好”；没有实测证据不宣称可用；“provider 可用”不等于“实测通过”。
- **Windows 上没实测的功能一律标“未验证”**：云端测过的（合成素材）可以说云端通过；真实素材、DirectML、PyMSS Studio、声音、REAPER 要在实机上验过才算；发布说明里如实写没验证的部分。
- 界面自动化或人工点击只补充自动化证明不了的东西；验证够了就停。

## 7. 和所有者沟通

- 用中文、平白的话；少用术语，必须用时顺带解释。
- 要所有者拍板时：给两三个选项，各自的代价说清楚，写明推荐哪个、为什么。所有者常常成批地简短回答。
- 汇报说清：做了什么、怎么验证的、结果如何、还有什么没做或不确定；最后给一份能照着检查的清单（在哪看、该看到什么）。
- 所有者的原话是决定的依据：记进 DECISIONS 时保留要点。

## 8. 禁区与数据安全

- **不要打开**旧版仓库和交接包存档里的任何东西（位置见 `AGENTS.local.md`）。旧版没有兼容义务，不参考它的表结构、接口、文件布局。
- **不要操作所有者正在使用的应用**（`/Applications` 里的发布版和它的日常工作区）。开发版只用仓库里的 `dev-workspace/`；要用真实资料复现问题，用 `tools/clone-workspace` 克隆一份（DEVELOPMENT「开发版与发布版并存」）。
- 只在本项目目录里写东西（开发工作区、克隆都在仓库里且不进 Git）。
- **发布以后，数据库迁移必须保留已有数据**：新迁移写新文件（`store/migrations/00NN_*.sql`，只增不改旧文件），在所有者真实资料的克隆上验证过再发布；不能“清空重来”。
- PyMSS Studio 只按 worker 协议调用（规格 14 §14.6），`download` 永远为 false；不修改它的环境，不替它装依赖。

## 9. 代码约定

- **技术定型不换**（规格 14）：对齐只用 pydomino；文本前端 pyopenjtalk-plus + tsqyomi；音高 FCPE；拉平 PC-NSF-HiFiGAN；分离调用 PyMSS Studio。其余选择见 ARCHITECTURE。
- **Core 命令**：在 `core/ottosmasher/core/server.py` 的 `_register` 登记（作用类别 + 参数/返回类型 + 一句英文说明 + `layer`），参数与返回写成 `core/ottosmasher/api/types.py` 里的 TypedDict；
  改完运行 `tools/uv run python -m ottosmasher.api.catalog` 重新生成 `docs/api/commands.json` 与 `app/renderer/api/generated.ts`（测试检查是否最新）。
  前端 `call()` 不写类型参数，按命令名推断；不在页面里手写 Core 返回值的接口。新错误码登记到 `core/ottosmasher/core/errors.py` 的 `ERRORS` 并在 zh-CN.json、en.json 都加 `error.<码>`。
  给 agent 用的命令同步改说明书（`core/ottosmasher/cli/guide/reference/`，中英各一份）；提到这个命令的 skill 也要改（`guide/skills/{en,zh-CN}/`，测试核对两份逐节对应）。
- 用户可见文案一律走文案资源（`app/renderer/i18n/locales/<lang>.json`，`t(key, 参数)`；只翻译文字，数字日期用统一格式），不在代码里写死中文；加文案要中文、英文一起加（`i18n:check` 核对键和参数）；
  `core/` 的代码（注释和文档字符串以外）不写中日文字面量（`i18n:check` 检查）；Core 错误返回“错误码 + 参数”。
- 每个时间值都要明确所属时钟（原片秒 / 资产局部秒 / 文件秒 / 采样显示坐标）；换算只走 `domain.mapping` 一处。
- 不静默回退、不静默降级、不静默替换（P6）；未知不是零（P7）。
- 算法按规格的【基线算法】/【基线参数】复现，不顺手“优化”；改变结果的想法先写提议。
- **界面控件只从 `app/renderer/components/` 取**（所有者 2026-10-07）：按钮、输入、列表（统一选择规则）、右键菜单、锚定小面板、表格、分段选择、条件块、批量条、进度条、空状态、确认框、工作台等。
  页面里不许手写这类控件（包括原生 `<input type="checkbox">`、自己拼的菜单或弹层）；缺了先补进组件库并加到组件样张页，再在页面里用。界面的统一规则见 DECISIONS §13。
- 引擎层（`media`、`lang`、`models`、`domain`、`algo`）不引用资料库与 Core（ARCHITECTURE §15.6，`test_engine_boundary` 检查）。
