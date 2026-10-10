# 推送到 GitHub 与 Actions 构建说明（给执行推送的 agent）

> 写于 2026-10-10，所有者要求：“写一份推送和构建说明，我让另外一个 agent 去 GitHub 推送并用 Actions 做 Windows 和 Mac 的构建”。
> 执行前先读 [AGENTS.md](../AGENTS.md)（全部规则照样适用），再读本文件。本文件只覆盖“推送 + 持续集成构建”，**不是**阶段 10 的打包发布。

## 0. 授权范围

- **已授权**（所有者 2026-10-10）：把本仓库推送到所有者的 GitHub；新增 GitHub Actions 工作流，在 macOS arm64 与 Windows x64 上安装依赖、编译、跑测试。
- **没有授权**（要做先问所有者）：打 tag、建 GitHub Release、发布安装包；改仓库可见性为公开；改写已有提交历史；强制推送；
  改产品代码让 CI 变绿（CI 暴露的 Windows 问题是阶段 10 的开发工作，只记录和汇报，见 §6）；往仓库或 Actions 里放任何素材、模型权重。
- 推送前 §1 的三件事必须先问所有者拿到答复，不能自己定。

## 1. 推送前要所有者确认的三件事

| # | 问题 | 选项 | 推荐 |
|---|---|---|---|
| 1 | 仓库可见性 | 私有 / 公开 | **私有**。理由：测试代码里写着真实素材的文件名（不含内容，但能看出用的是哪些作品）；仓库还没有 LICENSE 文件和第三方声明（阶段 10 才补，GPL-3.0-or-later）；交接包派生的规格文字在 docs/ 里 |
| 2 | 提交里的邮箱 | 保留 / 改成 GitHub 的 noreply 地址 | 全部 150+ 个提交的作者是 `OttoSmasher Dev <samuj0220@gmail.com>`。私有仓库：**保留**，不改历史。若要公开：改作者邮箱要重写全部历史（`git filter-repo`），属于“改写历史”，要所有者单独同意 |
| 3 | 仓库放在哪 | 所有者的 GitHub 账号与仓库名 | 由所有者给出（例如 `<账号>/OttoSmasher`）；`gh auth status` 看当前登录的是不是所有者的账号，不是就停下来问 |

## 2. 推送前检查（只读，全部要过）

```bash
git status --short                      # 必须为空；有未提交修改 → 停下来问（不要替别人提交，也不要丢掉）
git branch --show-current               # main
git remote -v                           # 现在没有远程；有了别的远程 → 停下来问
# 仓库里不能有素材、模型、数据库、第三方二进制（.gitignore 已排除，这里再核一遍已跟踪的文件）
git ls-files | grep -Ei '\.(mkv|mp4|mov|webm|wav|flac|mp3|m4a|ogg|aac|srt|ass|onnx|npy|npz|sqlite3|so|dylib|dll|node|exe)$'   # 必须没有输出
git ls-files | grep -E '^(dev-workspace|third_party|fixtures|\.venv|node_modules|out|\.cache)/'                              # 必须没有输出
# 历史里最大的对象（现在最大的是 0.5 MB 的 logo.png；出现几 MB 以上的媒体文件 → 停下来问）
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' | awk '$1=="blob"' | sort -k2 -n -r | head
# 凭据
git grep -nIE '(api[_-]?key|secret|token|password)\s*[:=]\s*["'"'"'][^"'"'"']{12,}' -- . ':!package-lock.json' ':!uv.lock'   # 逐条看，确认没有真凭据
```

`STATUS.md`、`dev-workspace/` 已在 .gitignore，不会被推送。

## 3. 推送

```bash
gh repo create <账号>/<仓库名> --private --source . --remote origin --description "OttoSmasher 新版"
git push -u origin main
```

- 不推 tag，不推别的分支。以后由开发会话本地提交、在所有者每次授权后推送（AGENTS §3 不变）。
- 推送后用 `gh repo view --web` 或 `gh api repos/<账号>/<仓库名>` 确认可见性确实是 private。

## 4. 现状：能“构建”到哪一步

**还不能出安装包。** 打包是阶段 10 的工作，现在缺的东西：

- `app/main/paths.ts` 对打包后的应用直接报错（发布版的目录布局未定，L8）；没有 electron-builder 配置。
- Python 运行时现在用的是仓库里的 `.venv/`；发布版要用 python-build-standalone 随包带（ARCHITECTURE §14），还没做。
- **Windows 的 libmpv 还没有来源**：`tools/third_party.json` 只有 `libmpv-macos-arm64`。所以 Windows 上 mpv 渲染桥（`app/native/mpv-bridge`）现在编不了，应用也起不来。
- ffmpeg / rubberband 开发期用的是本机 Homebrew 版，没有随包版本。
- 模型权重不随包（规格如此），CI 里也没有，需要模型的测试会自动跳过。

所以这一轮 Actions 做的是**持续集成构建**：

| 步骤 | macOS arm64 | Windows x64 |
|---|---|---|
| 安装 Python 依赖（uv，锁文件）| 要 | 要（第一次在 Windows 上解析，包括 onnxruntime-directml）|
| 安装 Node 依赖与 Electron | 要 | 要 |
| 拉第三方文件（校验 SHA-256） | 要 | 要（自动只拉本平台的条目，没有 libmpv）|
| 编译 pydomino 解码扩展（`tools/build_domino.py`） | 要 | **要**（L9：MSVC 构建从没实测过，这是这轮最重要的检查之一）|
| 编译 mpv 渲染桥（`tools/build-native.mjs`） | 要 | 跳过（没有 libmpv，阶段 10）|
| 类型检查、i18n 检查、前端单元测试（vitest） | 要 | 要 |
| Core 测试（pytest，`OTTO_STRICT_API=1`） | 要 | 要（第一次在 Windows 上跑，预计会暴露问题，照实记录）|
| 构建前端与主进程（`npm run build`） | 要 | 要 |
| e2e（Playwright 驱动真实 Electron） | 要 | 跳过（应用依赖 mpv 渲染桥）|
| 上传产物 | 测试报告、编译出的扩展（`third_party/native/darwin-arm64/`、`app/native/mpv-bridge/build/Release/*.node`）、`out/` | 测试报告、`third_party/native/win32-x64/` 里的扩展、`out/` |

产物只给开发看“能不能编出来”，**不是给用户用的程序**，不要叫它“安装包”或“发布版”。

## 5. 工作流怎么写

文件：`.github/workflows/ci.yml`（新增，进 Git，作为本地提交推送；提交信息末尾带当前会话要求的署名行）。下面是参考草稿：它没跑过，按实际跑通再调整；**能改的只有工作流本身**。

要点：

- **项目内缓存的规则在 CI 里同样做到**：`tools/uv`、`tools/npm` 是 sh 脚本，作用只是把缓存与安装目录设到仓库内。Windows 上的 Git Bash 会把路径写成 `/d/a/...`，原生的 uv / npm 不认。所以工作流不调用这两个脚本，而是在 job 的 `env` 里用 `${{ github.workspace }}` 设同样的变量，再直接调用 `uv` / `npm`：效果与这两个脚本相同，两个平台通用。
- 版本与开发机一致：Node 26.9.0、npm 11.19.1（npm 11 才认 `package.json` 的 `allowScripts`，只允许 electron 和 esbuild 的安装脚本）、uv 0.12.19、Python 3.12（uv 托管）。
- `uv sync --frozen`：严格按 `uv.lock`，不重新解析；锁文件在 Windows 上缺包 → 失败并记录，不要在 CI 里改锁文件。
- **不设 `OTTO_FIXTURES`**，不准备 `dev-workspace/Models`：真实素材与模型相关的测试会自己跳过。不要从任何地方下载素材或模型权重。
- macOS runner 上可以用 Homebrew 装 ffmpeg 和 rubberband（这是 CI 虚拟机，不是所有者的电脑；开发机上不许 `brew install` 的规则不受影响）。Windows 先只装 ffmpeg（choco）；rubberband 没有就让相关测试跳过。
- 权限只给 `contents: read`；同一分支新推送时取消旧的运行。

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: macos-15        # arm64
            plat: darwin-arm64
          - os: windows-2025    # x64
            plat: win32-x64
    runs-on: ${{ matrix.os }}
    timeout-minutes: 60
    env:
      # 与 tools/uv、tools/npm 相同：全部缓存与安装目录放在仓库内
      UV_PYTHON_INSTALL_DIR: ${{ github.workspace }}/.uv-python
      UV_CACHE_DIR: ${{ github.workspace }}/.uv-cache
      UV_PROJECT_ENVIRONMENT: ${{ github.workspace }}/.venv
      UV_PYTHON_INSTALL_BIN: "0"
      UV_PYTHON_PREFERENCE: only-managed
      npm_config_cache: ${{ github.workspace }}/.cache/npm
      npm_config_update_notifier: "false"
      npm_config_fund: "false"
      npm_config_audit: "false"
      electron_config_cache: ${{ github.workspace }}/.cache/electron
      ELECTRON_BUILDER_CACHE: ${{ github.workspace }}/.cache/electron-builder
      PLAYWRIGHT_BROWSERS_PATH: ${{ github.workspace }}/.cache/ms-playwright
      OTTO_STRICT_API: "1"
      PYTHONUTF8: "1"           # Windows 控制台与文件默认编码按 UTF-8（中文路径、中文日志）
    defaults:
      run:
        shell: bash
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6
        with:
          version: "0.12.19"
          enable-cache: false   # 缓存自己管（下面的 actions/cache），目录在仓库内

      - uses: actions/setup-node@v4
        with:
          node-version: "26.9.0"
      - run: npm install -g npm@11.19.1   # CI 虚拟机上的全局安装，不涉及开发机

      - uses: actions/cache@v4
        with:
          path: |
            .uv-cache
            .uv-python
            .cache/npm
            .cache/electron
            .cache/node-gyp
          key: deps-${{ matrix.plat }}-${{ hashFiles('uv.lock', 'package-lock.json', 'tools/third_party.json') }}

      - name: 媒体工具（只给测试用）
        run: |
          if [ "$RUNNER_OS" = "macOS" ]; then brew install ffmpeg rubberband; else choco install ffmpeg -y --no-progress; fi
          ffmpeg -version | head -1

      - name: Python 依赖
        run: uv sync --frozen
      - name: Node 依赖与 Electron
        run: npm ci

      - name: 第三方文件（固定版本，校验 SHA-256）
        run: uv run --no-sync python tools/fetch_third_party.py
      - name: pydomino 解码扩展
        run: uv run --no-sync --with setuptools python tools/build_domino.py
      - name: mpv 渲染桥（Windows 还没有 libmpv，阶段 10）
        if: runner.os == 'macOS'
        run: node tools/build-native.mjs

      - name: 类型检查 / i18n / 前端单元测试
        run: |
          npm run typecheck
          npm run i18n:check
          npm test
      - name: Core 测试
        run: uv run --no-sync python -m pytest core/tests -rs --junitxml=.cache/reports/pytest.xml
      - name: 构建前端与主进程
        run: npm run build
      - name: e2e（真实 Electron）
        if: runner.os == 'macOS'
        env:
          OTTO_MPV_AO: "null"
        run: npx playwright test --reporter=list,junit
        # junit 报告路径：PLAYWRIGHT_JUNIT_OUTPUT_FILE，按需要设

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: ci-${{ matrix.plat }}
          retention-days: 14
          if-no-files-found: ignore
          path: |
            .cache/reports/
            .cache/playwright-results/
            third_party/native/
            app/native/mpv-bridge/build/Release/*.node
            out/
```

可能要按实际调整的地方（这些都只改工作流）：

- **macOS 的 SDK**：`build-native.mjs` 和 `build_domino.py` 会在 `/Library/Developer/CommandLineTools/SDKs` 里挑一个正式版 SDK；runner 上这个目录不存在时会退回 Xcode 默认 SDK，一般没问题。编不过就在步骤里显式设 `SDKROOT=$(xcrun --show-sdk-path)`。
- **Windows 上 setuptools 找 MSVC**：runner 自带 Visual Studio；找不到时在这一步前加 `ilammy/msvc-dev-cmd@v1`。
- **e2e 的窗口**：macOS runner 有图形会话，Electron 可以直接开窗。全量 e2e 在开发机上约 6 分钟，其中 `sources-many`（1500 个短音频）约 2 分钟；超时就把这一条单独放宽，不要删测试。
- **上传产物**里不能出现媒体或模型：e2e 的临时工作区在系统临时目录，不在上传路径里；`.cache/playwright-results/` 只有失败截图与追踪。上传前在步骤里 `find` 一下扩展名，发现 `.wav/.mp4/.onnx` 等就不传并报告。

## 6. 跑完以后

1. 两个平台各跑一次（推送触发；之后可以用 `gh workflow run ci` 手动触发）。用 `gh run watch`、`gh run view --log-failed` 看结果。
2. **CI 本身的问题**（缓存路径、工具版本、MSVC 环境、超时）：改工作流、本地提交、推送，直到配置本身没问题。
3. **产品代码在 Windows 上的失败**（测试失败、扩展编不过、路径或编码问题）：**不要改产品代码**。逐条记下失败的步骤 / 测试名、错误摘要、日志链接，交给开发会话在阶段 10 处理（对应 ROADMAP L9）。macOS 上的失败同样只记录，开发机上全部测试是通过的，CI 失败多半是环境差异，也要写明。
4. 写进本地 `STATUS.md` 的“未知项 / 等待所有者”下面（新起一小节“CI 首次运行 2026-10-xx”），再用中文给所有者汇报：
   - 仓库地址与可见性；推送了哪些提交（`git log --oneline origin/main -5`）；
   - 每个平台每一步：通过 / 失败 / 跳过，pytest 与 vitest、e2e 的通过 / 跳过 / 失败数；
   - Windows 上第一次暴露的问题清单（就是阶段 10 的待办）；
   - 产物在哪里下载（Actions 运行页面的 Artifacts），并说明那**不是可以直接用的程序**。
5. **Windows 上没有实测的功能一律算“未验收”**：CI 通过只说明能编译、单元测试能过，不等于应用在 Windows 上能用。

## 7. 不要做的事

- 不打开旧仓库 `/Users/a/Documents/OttoSmasher` 和 `~/Documents/OttoSmasher-Handoff-Archive-2026-10-03`。
- 不把交接包的 `fixtures/`、`dev-workspace/` 里的任何东西（素材、模型、数据库）放进仓库、Actions 缓存、产物或 Release；不在 Actions 里设 `OTTO_FIXTURES`。
- 不在 Actions 里调用任何在线 ASR / LLM 服务。
- 不用 `git push --force`，不改写历史，不删远程分支；不开自动合并。
- 不在开发机上做全局安装（系统 npm / uv / brew）；本地一律用 `tools/npm`、`tools/uv`。
- 不操作所有者正在使用的应用。

## 8. 之后（阶段 10）才做的事，这一轮不做

- 发布版目录布局与 `paths.ts`（L8）、electron-builder 目录产物、macOS ad-hoc 签名与去绝对 rpath、ZIP 严格 < 2,000,000,000 字节；
- python-build-standalone 随包的 Python、ffmpeg / ffprobe（要带 libx264 / aac / prores_ks，与许可证一起选）、rubberband、Windows 的 libmpv 来源与许可证复核；
- 冒烟检查（ARCHITECTURE §14：中文与空格路径、清空 Python 环境变量、空工作区、运行库探测、播放截停、媒体工具）；LICENSE 与第三方声明；发布版数据目录（L3）；
- 那时再给工作流加打包与上传 ZIP 的 job，并由所有者在 Windows 实机验收。
