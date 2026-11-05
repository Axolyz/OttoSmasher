# 从源码运行、开发与测试

给开发者看的；普通用户看 [README](../README.md) 和 [用户说明](user/README.md)。

- 开发规则与**文档地图**：[AGENTS.md](../AGENTS.md)（先读它：每份文档回答什么、什么时候查）
- 架构：[ARCHITECTURE.md](ARCHITECTURE.md)；现行决定（含界面规则）：[DECISIONS.md](DECISIONS.md)；路线图与未结事项：[ROADMAP.md](ROADMAP.md)
- 原始需求规格：[spec/](spec/README.md)（文档与代码里“规格 xx §y”“R4.4”“S11.3”指它）；过程记录：[history/](history/README.md)

## 准备环境（macOS arm64）

全部装在仓库内（AGENTS.md §4）：不用系统的 `uv` / `npm`，用 `tools/uv`、`tools/npm`，它们把缓存和安装目录设到仓库里。

```bash
tools/uv sync                                         # Python 3.12 与 Core 依赖 → .venv/
tools/npm install                                     # Node 依赖与 Electron → node_modules/
.venv/bin/python tools/fetch_third_party.py           # libmpv、mpv 头文件、模型支持文件、pydomino 源码 → third_party/（校验 SHA-256）
tools/uv run --with setuptools python tools/build_domino.py   # pydomino 的 Viterbi 解码扩展 → third_party/native/<平台>/
node tools/build-native.mjs                           # mpv 渲染桥（Electron 原生扩展）
```

macOS 开发期使用本机已有的 Homebrew `ffmpeg` / `ffprobe` 与 `rubberband`（只调用，不改动）。libmpv 是编好的压缩包（`tools/third_party.json`），要换版本时改 `tools/build_libmpv_macos.sh`，推送后由云端重新编译（`.github/workflows/build-libmpv.yml`），再把产物传到 Release `third-party-1`。

**模型权重**放在工作区的 `Models/` 下；开发工作区是仓库内的 `dev-workspace/`（不进 Git）。
两种办法：启动后在 设置 → 环境与模型「下载缺少的模型」，或手动按 `core/ottosmasher/models/registry.py` 里的直链下载后放进
`dev-workspace/Models/<子目录>/`。四个文件共约 190 MB。

### Windows（x64）

日常不需要 Windows 电脑：推送后云端自动在 Windows 上构建、测试、打包（`.github/workflows/windows.yml`）。要在实机上开发时：装 [uv](https://docs.astral.sh/uv/)、Node 26、Git for Windows、Visual Studio 的 C++ 桌面开发组件，然后在 Git Bash 里运行上面同样的命令（把 `.venv/bin/python` 换成 `.venv/Scripts/python.exe`），再把媒体工具加进 PATH：`third_party/media-tools/ffmpeg/bin`、`third_party/media-tools/rubberband`。没有界面的机器用 `.venv/Scripts/python.exe tools/fetch_models.py` 下载模型。

**云端查问题**：`gh run list` / `gh run view <id> --log-failed` 看结果；`gh run download <id> -n e2e-results` 取失败截图（`failure.png`）和 Core、任务日志。卡死时单跑一个测试并导出全部线程的调用栈（写进工作区的 `Data/Logs/hang-dump.log`）：`gh workflow run windows.yml --ref <分支> -f spec=e2e/xxx.spec.ts`。

## 运行

```bash
OTTO_DEV=1 tools/npm start          # 构建并启动（开发模式：工具页有任务自检与 mpv 探针）
```

也可以在访达里双击仓库根目录的 `start OttoSmasher.command`。

## 测试

```bash
.venv/bin/python -m pytest core/tests                 # Core 单元与进程级测试
tools/npm test                                        # 前端单元测试（vitest）
tools/npm run typecheck                               # TypeScript 类型检查
tools/npm run i18n:check                              # 源码里没有写死的中日文、文案键齐全
tools/npm run e2e                                     # Playwright 驱动真实 Electron（临时工作区、静音输出；默认看不见窗口，不抢前台、不挡鼠标，要看窗口设 OTTO_E2E_FOREGROUND=1）
```

- 真实素材（第三方版权内容，不复制进仓库、不进 Git，见 AGENTS §5）：设 `OTTO_FIXTURES=<素材目录>` 再跑
  pytest 或 `e2e/real-*.spec.ts`；需要模型的测试另要 `dev-workspace/Models`。
- `OTTO_STRICT_API=1`：Core 核对每个命令的返回值与命令目录一致。
- Core 命令改了之后：`.venv/bin/python -m ottosmasher.api.catalog` 重新生成 `docs/api/commands.json` 与 `app/renderer/api/generated.ts`。
- 3 万条合成库的性能测试：`OTTO_PERF_WS=.cache/perf/ws .venv/bin/python -m pytest core/tests/perf -s`。

## 发布

macOS（Apple 芯片）本地构建，Windows（x64 预览版）云端构建，两个 ZIP 发到同一个 GitHub Release（所有者说要发才发）；除 PyMSS Studio 外模型随包。

```bash
.venv/bin/python tools/package_mac.py   # 先把小版本号加一并提交、打本地标签，再构建 → out/release/OttoSmasher.app、OttoSmasher-<版本>-macos-arm64.zip、.sha256、RELEASE_NOTES.md
OTTO_PACKAGED_E2E=1 tools/npm exec -- playwright test e2e/packaged.spec.ts   # 发布包冒烟：清空环境变量、中文与空格路径、随包模型、播放、otto 路径
```

**构建前先跑全量 e2e**（所有者 2026-11-04）：`tools/npm run e2e` 全部通过后才更新版本号。一般提交只跑相关的文件。

**版本号**（所有者 2026-10-31）：每次构建自动把小版本号加一（`package.json`、`package-lock.json`、`pyproject.toml`、`core/ottosmasher/__init__.py`、`uv.lock` 一起改），
提交“版本 x.y.z（构建）”并打**本地**标签 `vx.y.z`；要求没有未提交的修改（包对应一个提交）。`--no-bump` 按当前版本重新构建。
`RELEASE_NOTES.md` 由 `tools/release_notes.md` 模板生成，“这一版的改动”列出相对上一个版本的提交（上一个标签；没有标签时找上一个“版本 …”提交），发布前可以手改。

**发到 GitHub**（所有者 2026-10-31：构建和发布由开发者用 GitHub CLI 做，但**只在所有者明确说要构建 / 要发布时才做**）：
1. 推 `main`，再**只推这一版的标签**：`git push origin vx.y.z`（不用 `--tags`，旧的本地标签不一定要公开）。标签打在构建用的那个提交上，
   Release 因此对应包里的代码。
2. 发布说明 `out/release/RELEASE_NOTES.md`（不进 Git）：“这一版的改动”是按提交说明自动列的，改成用户看得懂的几条，**发之前给所有者过目**（所有者可能自己改）；
   核对 SHA-256 与 `.sha256` 文件一致（`shasum -a 256 out/release/OttoSmasher-*.zip`）。安装步骤、已知限制来自模板，模板过时就改 `tools/release_notes.md`。
3. 发布（第一行标题去掉，GitHub 上 Release 的标题就是它）：
   ```bash
   tail -n +3 out/release/RELEASE_NOTES.md > <临时目录>/notes.md
   gh release create vx.y.z --verify-tag --title "OttoSmasher x.y.z" --notes-file <临时目录>/notes.md --latest \
     out/release/OttoSmasher-x.y.z-macos-arm64.zip out/release/OttoSmasher-x.y.z-macos-arm64.zip.sha256
   ```
   发之前 `gh release list` 看一眼有没有同一个标签的草稿（所有者可能在网页上起过草稿）。

**Windows 包**由云端构建（`tools/package_win.py`）。macOS 构建加好版本号、打好标签并推送之后，标签会自动触发 Windows 工作流；`package` 任务（含发布包冒烟）通过后，会把 ZIP 和 `.sha256` 传到这个标签的 Release 草稿（没有草稿就新建，已经发布的不动）。之后把 SHA-256 填进发布说明的 `{windows_sha256}`，再把发布说明更新到草稿。Windows 还要在所有者的电脑上过一遍真实素材、DirectML、PyMSS Studio、声音和 REAPER（大版本时）；真实素材不放云端（AGENTS §5）。

构建前要有：上面“准备环境”的全部产物（`.venv`、`third_party/`、mpv 渲染桥、pydomino 扩展）、`dev-workspace/Models` 里四个模型（脚本按 SHA-256 核对）、
本机 Homebrew 的 `ffmpeg` / `ffprobe` / `rubberband`（脚本把它们连同依赖的动态库复制进包，改成包内相对路径）。
包是 ad-hoc 签名、没有公证（没有 Apple 开发者证书），README 写了用户第一次打开的办法。
布局与原因见 [ARCHITECTURE.md §14](ARCHITECTURE.md)，随包组件与许可见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 开发版与发布版并存（所有者 2026-10-31）

同一台电脑上既装着发布版日常使用、又在源码里修 bug 时：

- **只在身份上区分，行为一样**：源码运行叫 **OttoSmasher Dev**（窗口标题、程序坞角标 “Dev”、界面缓存在 `~/Library/Application Support/OttoSmasher Dev`），
  顶栏在页面标题旁显示当前工作区（两个版本都显示，悬停看完整路径与版本）。两者的其余差别（默认工作区、Python、模型、媒体工具的位置）
  都在 `app/main/main.ts` 与 `app/main/paths.ts` 的“源码运行 / 发布版”分支里；不要在开发版里藏功能、改默认值或让结果只在一边出现。
- **数据分开**：发布版用 `~/Documents/OttoSmasher Workspace`（日常资料），源码运行用 `dev-workspace`（测试数据）。**不要让开发版打开日常工作区**：
  开发版的表结构常常更新，打开就会把它升级，旧的发布版就打不开了。同一个工作区不能被两个 Core 同时打开（工作区锁，后开的报错退出）。
- **在真实资料上复现 bug**：`tools/clone-workspace [名字]` 把日常工作区 APFS 克隆到 `dev-workspace-clones/<名字>/`（几秒、几乎不占空间；数据库用在线备份，应用开着也一致；
  删掉原实例的 agent 端点与锁），再按它打印的命令用 `OTTO_WORKSPACE=… tools/npm run dev` 启动开发版。用完删掉那个文件夹。
  `--from` 换源、`--to` 换目标（例如 `tools/clone-workspace --from dev-workspace --to ~/Documents/OttoSmasher\ Workspace` 把开发用的工作区整个变成发布版的日常工作区）。
- **`otto`**：仓库里一律用 `tools/otto`（连正在运行的开发版的工作区，没开就是 `dev-workspace`）；`~/.local/bin/otto`（发布版启动时自动安装）指向发布版。两者不交叉。先 `otto status` 看 `workspace`。
- **流程**：日常遇到 bug → 记下日志（`Data/Logs/`、任务的 `Data/Jobs/<id>/log.txt`、agent 的 `otto session`）→ 克隆工作区、开发版复现、修好、测试 → 提交 → `tools/package_mac.py`（版本加一）
  → 替换“应用程序”里的旧版。新版第一次打开日常工作区会升级数据库，升级前自动备份到 `Data/Backups/`；保留上一版 ZIP 以便换回（换回时连同备份一起恢复）。

