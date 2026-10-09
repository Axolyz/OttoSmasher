# OttoSmasher 新版架构（阶段 0 草案）

> 状态：**草案，待所有者过目**（2026-10-05）。依据只有交接包 `OttoSmasher-Rewrite-Handoff/`（下文 “规格 xx §y” 指交接包 docs/xx）。
> 本文件属于“自由设计”层（规格 02 §2.6）：架构、进程模型、数据库、内部格式由开发者决定，但必须满足基线行为与规格 15 的非功能要求。
> 界面布局与交互另见 `docs/UI_PLAN.md`（半基线，须所有者确认）；疑问与矛盾见 `docs/QUESTIONS.md`。

---

## 0. 一页总览

> 2026-10-05 修订：按所有者意见重新权衡后，界面层从 PySide6 改为 **Electron + TypeScript/React + wavesurfer.js**（理由与取舍见 §1.1）。（2026-10-07 起波形不用 wavesurfer，见下表“波形”行与 §13）
> Python 核心、数据模型、存储、任务与检索方案不变。

| 层面 | 选择 | 一句话理由 |
|---|---|---|
| 界面 | **Electron 44 + TypeScript + React 19 + Vite** | Web 生态最大：图表、交互等都有成熟上游可跟进（波形最终自研，见下一行）；所有平台同一个 Chromium，渲染一致 |
| 波形 | **自研画布组件**（所有者 2026-10-07 定：整集时间线、舞台、工作台同一个组件，不用 wavesurfer） | 放大后的细化显示是刚需：按视口向 Core 取峰值（≤32000 点），≤30 秒细节窗精确解码到样本级；wavesurfer / peaks.js / waveform-playlist 都只吃覆盖全程的固定分辨率数据，语音标注工具都在浏览器里整段解码，图表库没有区段编辑与车道（两轮调研，§13）；车道、F0 线、命中框、区段编辑都画在同一组件的图层上 |
| 视频/音频播放 | **libmpv**（播放引擎）+ **render API 把画面画进页面里的 `<canvas>`** | 保留旧版验证过的 libmpv（HEVC Main10 + FLAC、引擎侧样本级截停、外挂声部 + 音频延迟、硬解）；不再用“原生视图叠在网页上”，画面是普通 DOM 元素，遮挡/裁剪/缩放问题整体消失（§10.1） |
| 核心 | **Python 3.12 Core 进程**（领域、SQLite、任务调度、检索协调） | 定型模型与文本前端都在 Python 生态；Core 是唯一写库者 |
| 进程 | Electron 主进程 + 渲染进程 + Python Core + 检索进程池 + 任务进程（§2） | 界面永不被计算阻塞；模型与检索可整树取消 |
| 进程间通信 | 渲染进程 ⇄ 主进程：Electron IPC；主进程 ⇄ Core：stdio 上的长度前缀 **msgpack** 帧 | 无端口、无 HTTP、无跨站风险（规格 15 §15.6）；Core 的命令用 msgspec 定义，自动导出 JSON Schema → 生成 TypeScript 类型 |
| 数据库 | **SQLite（WAL）**，Core 单写多读 | 本地单用户；事务原子；检索 worker 只读并发打开 |
| 数值与特征 | numpy；F0 帧与音高索引用 `.npy`（内存映射） | 逐帧无损、按声音内容共享 |
| 模型推理 | ONNX Runtime（Windows 用 onnxruntime-directml），统一会话工厂 | 规格 14 §14.7 |
| 媒体工具 | ffmpeg/ffprobe、Rubber Band CLI（R3） | 规格 14 建议项 |
| 界面国际化 | **只翻译文字**：自写的小型 `t(key, 参数)` + 每种语言一个 JSON 文案文件；伪语言测试；后端只返回“错误码 + 参数” | 所有者 2026-10-06：只要翻译文字，不需要按语言格式化日期数字；不引入国际化框架（§7） |
| 打包 | electron-builder（目录产物 → ZIP）+ 随包的 Python 运行时（uv 托管的 python-build-standalone + 项目依赖） | 不用 conda-pack |
| 测试 | Python：pytest；前端：Vitest + Testing Library；端到端：Playwright 驱动 Electron | 规格 16 第三部分的合成测试做法 |

所有依赖装在项目内：`node_modules/`（含 Electron 二进制）、`.venv/`、`.uv-python/`、`third_party/`。所有者已同意“缺什么依赖都可以装”；
仍优先项目内安装，确实只能全局安装的（目前没有）会先说明。

---

## 1. 技术栈与理由

### 1.1 重新权衡：PySide6 还是 Electron + Web 前端

| 维度 | PySide6（上一版草案） | **Electron + React（选定）** |
|---|---|---|
| 生态与扩展 | Qt 本身很成熟，但 Python 侧的现成高级控件少，波形、卷帘、条件块都要自写 | 组件、可视化、交互库极多；wavesurfer.js 等上游持续更新；以后加功能（例如更复杂的可视化）选择多 |
| 开发者与后续维护 | Qt/Python 桌面开发者相对少 | Web 前端开发者多，接手门槛低 |
| 视频 | render API 画进 `QOpenGLWidget` | render API 画进页面 `<canvas>`（§10.1）——同样避免了旧版“原生视图盖住网页”的整类 bug |
| 运行时 | 一套 Python | Electron（Chromium + Node）+ Python 两套；包体更大（仍远低于 2 GB 上限） |
| 前后端边界 | 进程内/管道 | 管道（不开端口），类型由 Core 的命令定义自动生成，避免前后端字段名不一致（旧版 A27 那类 bug） |
| 拖出与剪贴板 | `QDrag`、pyobjc/ctypes | `webContents.startDrag`、`clipboard.writeBuffer('REAPERMedia')` |
| 界面测试 | pytest-qt | Vitest（组件）+ Playwright（Electron 端到端） |

结论：所有者的两点（wavesurfer.js 好用且跟上游、Web 生态带来的扩展可能）成立；PySide6 唯一明显的优势是“视频是普通控件”，
而在 Electron 里用 libmpv render API → `<canvas>` 也能做到。所以改为 Electron。代价是两套运行时与一个小的原生扩展（§10.1），都在可控范围。

**仍然不选的**：Tauri（系统 WebView 在 macOS/Windows 是两个不同内核，行为不一致；还要引入 Rust）；
浏览器 `<video>`/MSE 播放 HEVC（Windows 依赖系统 HEVC 扩展，MKV/FLAC 支持不稳定，做不到样本级截停；旧版已失败过）。

### 1.2 主要依赖（阶段 1 用 lockfile 锁定）

| 依赖 | 版本（初定） | 用途 |
|---|---|---|
| electron | 44.x | 桌面外壳 |
| react / react-dom | 19.x | 界面 |
| vite（界面）+ esbuild（主进程与 preload） | 8.3 / 0.28 | 构建（electron-vite 5 不支持 Vite 8，改用两者直接组合） |
| react-aria-components | 1.21.x | 无样式的交互基础件：列表/表格（勾选与键盘）、菜单（含子菜单）、弹层、对话框、提示、选择框、组合框、标签块、数字输入、工具栏；样式全部用自己的设计令牌（§1.3） |
| lucide-react | 1.x | 线条图标（ISC 许可） |
| zustand | 5.x | 前端界面状态 |
| node-addon-api + node-gyp | 8.9 / 13.1 | libmpv 渲染桥（原生扩展，§10.1）；`tools/build-native.mjs` 用 Electron 头文件编译 |
| electron-builder | 26.x | 打包 |
| Python 3.12（uv 托管，装在 `.uv-python/`） | — | Core 与任务进程 |
| msgspec、numpy、onnxruntime(-directml) 1.30.0/1.24.4、pyopenjtalk-plus[tsqyomi]==0.4.1.post9、pydomino @ 4930396（只编译上游 tokenizer + Viterbi 成 `_domino` 扩展：`core/native/domino_ext.cpp` + `tools/build_domino.py`；ONNX 推理走统一会话工厂，不用上游内置的 ONNX Runtime 1.16）、regex | — | Core |
| pytest、hypothesis；vitest、@testing-library/react、playwright | — | 测试 |

外部可执行文件与库：ffmpeg/ffprobe（开发期用 Homebrew 9.0.2，发布随包）、rubberband 4.0.0、libmpv（所有者已同意直接下载，GitHub 等来源均可；阶段 1 记录来源、版本与 SHA-256，见 QUESTIONS Q2）。

### 1.3 组件库与设计语言（2026-10-06 第三次修订：采用 React Aria Components）

**结论：交互基础件用 React Aria Components（无样式），外观全部用自己的设计令牌 + 组件清单。** 所有者第七轮：不想全部自己写，有更轻的同等组件库就用它，否则就用 React Aria。

**实测体积**（2026-10-06，esbuild 压缩打包、不含 React 本身；每个库取我们要用的同一组组件）：

| 库 | 覆盖的组件 | 压缩后 | gzip 后 |
|---|---|---|---|
| React Aria Components 1.21 | 对话框、菜单（含子菜单）、弹层、提示、选择框、组合框、数字输入、标签页、复选框、滑块、工具栏、标签块、**列表（GridList/ListBox，带勾选与键盘）** | 312 KB | 93 KB |
| Base UI 1.8（Radix 与 Floating UI 原班人马） | 同上，但**没有列表/表格**、没有标签块；多了右键菜单、提示条 | 339 KB | 113 KB |
| Ark UI 5.39（Zag 状态机） | 同上，有列表框、标签输入、分栏拖动条；**没有表格、没有工具栏** | 369 KB | 101 KB |
| Radix（radix-ui 1.7） | 对话框、菜单、右键菜单、弹层、提示、选择框、标签页、复选框、滑块、工具栏、提示条；**没有列表、组合框、数字输入、标签块** | 170 KB | 53 KB |

结论：
- **同样的组件，React Aria 并不比其他无样式库重**；只有 Radix 更小，但缺的正是我们最需要的列表勾选、组合框（分面搜索）、标签块（条件块）、数字输入（精确时间）。
  另外这是桌面应用，代码从本地磁盘加载，几百 KB 对启动没有可感知的影响（Electron 本身约 200 MB，模型以 GB 计）。
- “注重无障碍”：所有无样式库（Radix、Base UI、Ark、React Aria）的核心工作都是键盘与焦点管理，这正是规格 03 §3.8 要求的；读屏属性是顺带的，不额外花我们的功夫。
- “有点重”的真实代价是 API 啰嗦（子组件多、靠渲染函数和 data 属性写样式）。对策：每个 React Aria 组件只在 `components/` 里包一次成我们自己的组件，页面只用包好的。
- 交互规则对得上：GridList/Table 在 `selectionMode="multiple"`、`selectionBehavior="toggle"` 时，**单击行触发 `onAction`（= 查看），复选框只管勾选**；Shift 连选、↑↓、⌘A 内置——正是 UI_PLAN §6.1。
- 它没有的，自己补：**右键菜单**（React Aria 没有专门的组件，用它的菜单 + 一个落在指针位置的锚点实现）、提示条（它的 Toast 仍标 UNSTABLE，自己写）、波形与画布类全部业务组件。
- 列表本来就分页（规格 07 / 03 §3.2，一页最多 100 行），采样列表不需要虚拟滚动；原片列表规格要求不分页，若一组展开后上千行，用 React Aria 自带的 Virtualizer。
- 设计语言：**设计令牌**（颜色、性质四色、字号阶、间距、圆角、阴影、密度、动效时长，深浅两套，CSS 变量）+ **组件清单**（按钮、分段、条件块、列表行、缩略图播放钮、
  菜单、锚定小面板、确认框、全屏工作台、抽屉、提示条、时间输入、波形卡……），每个组件只实现一次。样式用 CSS 变量 + CSS Modules，不引入 Tailwind。
  原型的颜色和间距是令牌初稿；阶段 1 先做一页“组件样张”给所有者看。不套用 Material、Fluent、Ant 这类现成视觉语言（网页后台风，压不到工作室观感）。
- 国际化不受影响：React Aria 只负责交互，界面文字仍走我们自己的 `t()`（§7）。
- 字体：界面用系统字体；**采样名、台词、读音标 `lang="ja"`**（中文采样标 `zh`），让日文汉字用日文字形显示。

---

## 2. 进程模型

```
┌──────────── Electron 渲染进程（React 界面）─────────────┐   ┌──────── Electron 主进程 ────────┐
│ 三页常驻（隐藏不卸载）· 视图状态（zustand）              │   │ 窗口、菜单、全局快捷键            │
│ 自研波形 · 分页列表 · 检索画布                          │◀─▶│ 拖出（startDrag）· REAPER 剪贴板   │
│ 视频 <canvas>：从 mpv 渲染桥拿帧（共享内存）            │IPC│ 启动/看护 Core；转发请求与事件     │
│ PlaybackCoordinator：全应用同一时刻只有一个声音          │   │ 工作区锁、退出时取消全部任务       │
└───────────────────────▲─────────────────────────────┘   └──────────────┬──────────────────┘
                        │ preload 暴露的受限 API                            │ stdio（msgpack 帧）
             ┌──────────┴───────────┐                       ┌───────────────▼──────────────────────┐
             │ mpv 渲染桥（原生扩展） │                       │ Python Core（唯一写库者）              │
             │ libmpv：解码、音频输出、│                       │ 命令 = 公开业务接口（msgspec 定义）     │
             │ 范围截停、外挂声部       │                       │ 领域服务 · 统一编辑通道 · 有效标签索引   │
             └──────────────────────┘                       │ 任务调度（模型 1 / 轻量 2）· 检索协调    │
                                                             │ 缓存服务（峰值/缩略图/频谱）· 清理器     │
                                                             └──────┬────────────────────┬───────────┘
                                                     spawn（进程组/作业对象）    常驻进程池（只读）
                                                   ┌────────▼─────────┐     ┌───────▼──────────┐
                                                   │ 任务进程           │     │ 检索进程池          │
                                                   │ 分析/测量/拉平/分离 │     │ 语音、音高、单音指标 │
                                                   │ → Studio、ffmpeg…  │     └──────────────────┘
                                                   └──────────────────┘
```

### 2.1 各部分在哪里跑

| 工作 | 进程 | 说明 |
|---|---|---|
| 界面、波形绘制、检索画布 | 渲染进程 | 只做显示与交互；不做 O(采样数) 的计算 |
| 视频解码、音频输出、范围截停 | mpv 渲染桥（libmpv 原生线程） | 不受界面卡顿影响（规格 15 §15.2：界面阻塞 700 ms 时截停仍准确） |
| 拖出、剪贴板、窗口 | 主进程 | |
| 浏览、标签、编辑、设置、字幕预览 | Core | 毫秒级；写操作串行化到一个写连接 |
| 字幕导入、字幕采样创建、删除原片（含独立化物化） | Core（大批量作为轻量任务） | 原子事务 |
| 语音分析、音高测量与索引、拉平、分离 | 任务进程（模型通道） | 一个批量任务 = 一个进程处理全部条目（避免逐句起进程） |
| 单音指标、派生重建、视频片段导出 | 任务进程（轻量通道） | |
| 三大搜索 + 单音指标筛选 | 检索进程池 | 交互式；可取消；写成固定结果 |
| 波形峰值、缩略图、频谱 | Core 的低优先级线程池调用 ffmpeg | 可清理缓存 |

### 2.2 取消

- **任务**：POSIX 上 `start_new_session=True`（独立进程组），Windows 上加入 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 作业对象；
  取消 = `killpg` / `TerminateJobObject`，连带结束 Studio worker、ffmpeg、rubberband；只影响本任务；不用 `kill(pid, 0)` 在 Windows 探活。
- **排队任务**：直接改为已取消，从不启动进程。
- **检索**：每次检索一个取消令牌（共享内存标志），worker 每个采样检查一次；超过 2 秒不退出就强制结束并重建进程池；被取消的检索不写固定结果。
- **拖出准备**：Esc/松手/失焦 → 取消；已生成的持久文件保留。
- **结果采纳**：任务进程只写 `Data/Jobs/<id>/` 并返回结果描述；登记与否由 Core 按规格的采纳规则决定，取消永远不会留下半成品登记。

### 2.3 生命周期与崩溃

- 主进程启动 Core（随包的 Python），Core 持有工作区锁；主进程退出或崩溃 → Core 读到 stdin EOF → 取消全部任务（整树）→ 退出。
- 退出应用时若有任务：提示“退出将取消 N 个任务”；确认后取消再退出；下次启动显示为“已中断”，可重试（两平台一致）。
- Core 崩溃：界面显示“核心服务已退出 · 重新启动”；渲染进程崩溃：主进程重建窗口并恢复状态（规格 13 §13.5 记录桌面端事件）。
- “另开窗口”是主进程开的第二个 BrowserWindow，共享同一个 Core；PlaybackCoordinator 经主进程协调，跨窗口也只有一个声音。

### 2.4 并发与一致性

- Core 单写连接 + 多个只读连接（WAL）；检索 worker 只读打开。
- 可编辑对象带 `version`（乐观并发）；编辑预览携带版本，应用时不一致就拒绝。
- 每个写事务产生“变化集”（对象类型 + ID + 操作），Core 推给界面；**界面只显示“资料已更新”类提示，不自动刷新/重排/重选**（P8）。
- 界面每个请求带“代次”，过期响应丢弃（规格 17 §17.1 #3）。

### 2.5 安全

- 渲染进程只加载本地打包的页面，CSP 禁止远程脚本与远程资源；`nodeIntegration` 关闭、`contextIsolation` 开启，preload 只暴露白名单 API；禁止打开新窗口与跳到外部地址。
- preload **不放进沙箱**（`sandbox: false`）：它要加载 mpv 渲染桥这个原生扩展并直接在画布上绘制。页面世界仍然没有 Node；播放器只接受主进程/Core 给出的文件（阶段 1 探针的路径来自主进程的对话框或环境变量，页面不能指定路径）。
- mpv 渲染桥只接受 Core 解析过的“播放句柄”（资产 ID + 区间 → 已核对文件快照的路径），渲染进程不能让它打开任意文件或 URL（R22.7）。
- 没有本地 HTTP 服务（R23.2 的 Host/Origin 校验因此不适用）。

---

## 3. 代码结构

```
app/                     Electron + 前端（TypeScript）
  main/                  主进程：窗口、Core 进程管理、IPC 转发、拖出、剪贴板（REAPERMedia）、退出流程
  preload/               白名单 API（core.request / core.onEvent / player.* / drag.*）
  renderer/              React 界面
    shell/               左侧导航、顶栏、底部播放条与交接通知、命令面板、任务抽屉
    library/             用途视图（统一列表）、查找栏与范围行、检索编辑器、舞台（采样详情）
    sources/             原片列表（按作品分组折叠）、查看器（画面 + 台本 + 时间线；只按内容调整）、准备清单
    workbenches/         拉平台、字幕导入、设置（全屏工作台面板）
    components/          自有组件清单（§1.3，交互基础用 React Aria 包装）：Wave（自研画布：峰值按视口取、细节窗样本级、选区、区段、车道、叠加曲线）、BlockCanvas、Collection（统一选择规则）、Menu、Popover、Modal、Sheet…
    i18n/                t()、locales/zh-CN.json、伪语言生成
    api/                 core.ts（call() 按命令名推断类型）+ generated.ts（由 Core 的命令目录生成，不手改）
  native/mpv-bridge/     C++（node-addon-api）：libmpv 播放器、render API（软件或 GL）、共享帧缓冲
core/                    Python
  ottosmasher/
    api/                 命令目录（ROADMAP L2）：types.py（参数与返回的 TypedDict）、registry.py（登记、参数校验、严格模式核对返回值）、catalog.py（导出 docs/api/commands.json 与前端 generated.ts）
    core/                Core 进程：rpc、services/、edits（统一编辑通道）、scheduler、search_coordinator、cleaner
    domain/              纯领域逻辑：mapping、overlap、naming、tag_expr、facets、subtitle_rules、nature_rules、oped、filename
    algo/                基线算法（纯函数 + numpy）：有效范围、强度、音块、停顿、语段、量化、拉伸映射、语音检索、音高检索、拉平定音与掩码、声学指标
    lang/                语言插拔（base + ja）
    models/              onnx.py（统一会话工厂：SHA-256 校验、CPU/CoreML/DirectML、请求的 EP 没进会话就报错、首次推理的节点分布）、probe.py（实测）、domino.py（pydomino 对齐）、FCPE、PC-NSF-HiFiGAN
    media/               ffprobe、区间解码、MP3 V0 编码与无缝校验、WAV/FLAC、峰值、缩略图、频谱、视频片段
    studio/              PyMSS Studio 适配
    jobs/                任务进程入口
    store/               schema 与迁移、仓储、文件发布（原子、租约、清单）、工作区布局
    platform/            进程组 / 作业对象
  tests/                 unit/ synthetic/ integration/（需 OTTO_FIXTURES）perf/
tools/                   拉取第三方二进制、校验模型、合成数据生成器、伪语言、Core 命令 → TS 类型生成
```

`domain/` 与 `algo/` 不依赖 IO，规格里的数值例子直接写成单元测试。

---

## 4. 数据模型草案

> 业务事实以规格 04 为准；下面是表结构草案（阶段 1 定稿）。ID 一律为不透明的随机 128 位十六进制串（`uuid4().hex`），
> 文件位置是独立字段（规格 04 §4.6）；**不做媒体内容指纹**（所有者 2026-10-06：废弃），文件是否被替换用“文件快照”判断（见 §4.1）。所有用户可编辑对象都有 `version`（乐观并发）和 `created_at`/`updated_at`。
> 显示文字不入库：性质、角色、来源种类等存稳定的内部值（如 `speech`、`vocal`），界面按语言显示（规格 15 §15.7）。

### 4.1 原片与流

| 表 | 关键字段 | 说明 |
|---|---|---|
| `source` | id, path, import_root, file_snapshot, duration, work, episode, source_type, subtitle_path, default_audio_stream, media_state(`available`/`released`), visual_binding_id, current_subtitle_version_id, version | 原片（可以是视频、长音频或很短的纯音频）。`media_state=released` 是删除原片后保留独立化采样的“媒体已释放的原片”（§4.9）。列表按作品分组、默认折叠（§4.10） |
| `source_stream` | source_id, kind(audio/video), ordinal（第几条音频/视频流）, container_index, codec, sample_rate, channels, bit_depth, language, title, start_time, duration, is_attached_pic | 封面图不算视频（规格 05 §5.1）；音轨按“第几条音频流”选择（R22.2） |

**文件快照**（取代内容指纹，所有者 2026-10-06）：大小 + 修改时间 + 流签名（各音频/视频流的编解码、采样率、声道、时长）。不读文件内容、不算哈希。
播放/导出/处理/测量前核对快照，不一致即报“音源已改变”（不替换、不回退；用户可“重新定位”到正确文件）。库内生成文件同样用快照。
仍然保留的哈希只有两类（都不是媒体内容指纹）：字幕文件内容哈希（规格 06 §6.1 按内容区分字幕版本，文件很小）；模型文件 SHA-256（规格 14 的定型校验与 Studio 模型指纹）。

### 4.2 声音资产、角色、默认轨

| 表 | 关键字段 | 说明 |
|---|---|---|
| `sound_asset` | id, source_id, origin(`stream`/`separation`/`flatten`/`reimport`), media_file_id, stream_ordinal, duration, mapping（控制点数组）, input_asset_id, input_start, input_end, stem_name（原样大小写）, production（操作、参数、模型身份/指纹、算法版本）, language | 不可变。测量按“资产 + 音频流”共享（同一资产内覆盖所需区间即可复用；不同资产不共享） |
| `asset_storage` | asset_id, range_start, range_end, media_file_id, kind(`primary`/`materialized_slice`) | 资产的**物理存储**。正常只有一条 primary；独立化时增加覆盖采样区间的无损切片（§4.9）。这是规格 04 §4.2.4 允许的“显式存储迁移”：只改位置/编码，不改时间关系 |
| `media_file` | id, path（工作区相对或绝对）, location(`external`/`library`), file_snapshot, format, sample_rate, frames, encode_manifest | 原片文件、库内音轨、回导文件、物化切片 |
| `asset_role` | asset_id, role(`vocal`/`sfx`), state(`on`/`removed_by_user`) | 角色集合；“用户显式移除”单独记，系统不再加回（R2.5） |
| `default_track` | source_id, role, asset_id | 每原片每角色最多一条；写入时校验“完整覆盖且未变速（容差 20 ms）” |

映射（`domain.mapping.Mapping`）：控制点 `[(local, source)]` 两列严格递增，首点 local=0、末点 local=资产时长；分段线性；越界报错，不外推不夹取；
提供 `crop(a,b)`、`compose(child)`、`to_source(t)`、`to_local(t)`；帧/样本舍入允许一帧。**所有时钟换算只走这里**（规格 17 §17.1 #1）。

### 4.3 字幕、标注、OP/ED

| 表 | 关键字段 | 说明 |
|---|---|---|
| `subtitle_version` | id, source_id, content_fingerprint, file_name, language, rules_snapshot, imported_at | 按文件内容区分；同内容再导入只补登 |
| `subtitle_line` | id, version_id, line_no, start, end, raw_text | 该版本的原始行（内容快照） |
| `annotation` | id, source_id, kind(`line`/`sfx`/`song`/`tag`), scope(`source`/`role`/`asset`), scope_role, scope_asset_id, start, end（原片秒或资产局部秒，由 scope 决定）, raw_text, clean_text, align_text_auto, align_text_manual, tags[], subtitle_version_id, subtitle_line_id, user_edited, deleted, version | 字幕导入只插入不覆盖（`user_edited` 的不改写）；非当前版本的标注各处不参与 |
| `annotation_revision` | annotation_id, version, snapshot, edit_id | 每次编辑留版本 |
| `oped` | id, source_id, kind(OP/ED), start, end, origin(`subtitle_rule`/`manual`), evidence, deleted | 绑定原片 ID（不含路径），重新定位后仍有效 |

### 4.4 采样

| 表 | 关键字段 | 说明 |
|---|---|---|
| `sample` | id, asset_id, start, end（资产局部秒，创建后不变）, name, nature(`speech`/`pitched`/`unpitched`/`unclassified`), starred, rating, note, language, created_via, parent_sample_id, parent_label（父被删后保留的来源说明）, origin（预览行、字幕版本、命中、任务等）, text_snapshot（原文、自动对齐文本、原字幕时间）, tag_judge_start/end, align_text_manual, independent(bool), visual_binding_id, version | 显式保存一律新建；删除是硬删除（带确认），固定结果里的成员保留位置并标“已删除” |
| `sample_tag` | sample_id, tag | 本地标签（≤512 个/采样） |
| `sample_effective_tag` | sample_id, tag, facet, provenance(`local`/`source`/`segment`/`auto`), provenance_ref | **派生索引**，不是冻结：由 Core 在同一个写事务里按规则增量维护（标注、角色、原片属性、本地标签、绑定变化都会触发）；语义仍是“实时求值”，测试要求它恒等于完整重算（R8.8） |

### 4.5 测量（不是缓存）

| 表 / 文件 | 关键字段 | 说明 |
|---|---|---|
| `measure_run` | id, kind(`alignment`/`f0`/`acoustic`), owner_type(`sample`/`asset_text`), owner_id, asset_id, range, inputs（语言、文本版本、辞典版本、前端版本、模型身份与指纹、目标区间、窗口、容差、设备）, status(`ok`/`failed`/`cancelled`/`stale`), manual(bool), result（对齐结果 msgpack；F0 指向文件）, created_at | 不可变版本 |
| `measure_head` | owner_type, owner_id, kind, run_id, version | 当前采用的版本（version 供人工修正与切换版本的乐观并发）；采纳规则见规格 08 §8.4。语音测量的归属：`sample`，或 `asset_text`（资产选区 + 文字区段，owner_id = 资产与区间的指纹，不需要采样）；子采样没有自己的测量时读覆盖它的同一物理声音测量的投影 |
| `Data/Measurements/f0/<asset_id>/<身份>/` | 每 60 秒一段 `<段号>.npy`（6000×3：F0、置信度、能量，float32 逐帧无损，两侧各 1 秒上下文推理）+ `manifest.json` | 按资产共享；身份 = 文件快照 + 音频流 + 存储窗口 + 映射 + 模型与算法版本（`models/f0store.py`）；只测用到且没测过的段；测量记录 kind=f0、归属 asset（阶段 4.5b） |
| （音高检索索引） | 阶段 7：完整检索直接读 F0 测量（上一行），不另建 50 ms 摘要；“已索引” = 范围所在的 F0 段都已测 | F0 就是音高检索索引，**不当缓存删**（规格 10 §10.2.5） |

拉平成品的 `pitch:` 标签来自资产 `production.target`（登记时记录的目标音），不来自重测（规格 11 §11.4）。
拉平（阶段 5，`core/flatten.py` + 任务进程 `jobs/flatten.py`，算法 `algo/flatten.py`、声码器前端 `models/hifigan.py`）：拉平台打开时冻结“资产 + 外选区 + 文件快照指纹”，提交时核对；
任务对冻结的输入重新测 F0、定音、重合成、掩码拼接、编码 MP3 V0，再对成品测 F0；登记一个 origin=flatten 的资产（`production` 记目标音〔名称、MIDI、Hz、原始 MIDI、偏移〕、范围与实际处理区间、定音方式与参考区间、内区与过渡、所用对齐、算法与模型版本、输入指纹）
+ 成品的 F0 测量（kind=f0）+ 一个调谐单音采样；输入指纹相同的成品音频复用、采样新建。

### 4.6 派生数据（可重建）

| 表 | 内容 | 失效条件 |
|---|---|---|
| `rhythm_cache` | （阶段 7 起合并进 `speech_index`）| 舞台的节奏视图仍在 Core 内存里按身份缓存（`core/rhythm.py`） |
| `speech_index`（迁移 0008，阶段 7 实现） | 每采样一行：失效键 + msgpack（逐块属性按列：起音、结束、前导辅音开始、首元音、前导辅音、MIDI 中位数、波动、覆盖率、走势、相对音高、相对响度、强度、持续终点、角色、停顿段号、语段号；整句与各语段的占格、停顿、切口、窗口）。由「准备检索索引」任务构建（`jobs/search.py`，只读、进程池并行），采纳时核对失效键 | 失效键全部来自数据库（`core/search_index.py::speech_keys`：采样范围与节奏参数、语音测量头或投影来源、F0 测量头、存储签名与文件快照、台词标注、惩罚度、算法版本）；改名、星标、普通标签不失效（R14.14）；采样删除级联 |
| `scheme_cache` | 没有落库：检索进程内存里按（采样 + 失效键, 范围, BPM）缓存（3 万条冷启动 S3 2.8 s，不需要） | — |
| `acoustic_metric`（迁移 0009） | 每采样一行单音指标（JSON）；有效 = 资产、范围、存储签名、算法版本都等于现在的（SQL 里核对，筛选直接分页） | 内容变了失效 |
| `Data/Cache/` 文件 | 波形峰值金字塔、缩略图、频谱、临时解码 PCM（带租约） | 可清理 |

### 4.7 检索结果与筛选

| 表 | 关键字段 | 说明 |
|---|---|---|
| `result_set` | id, kind(`speech`/`pitch`), created_at, title, query, scope_snapshot（范围栏标签条件 + 查找栏文字/表达式/临时条件 + 当时的筛选器内容）, params（含 BPM）, stats（后端耗时、缺少有效分析计数、是否截断）, ui_state（激活、页码、选中、滚动）, closed | 固定结果；重启后恢复不重搜（规格 04 §4.2.10） |
| `result_member` | result_id, rank, sample_id 或 (asset_id, 原片模式), binding_snapshot（asset_id/start/end/分析版本/索引版本）, hits（每处命中：区间、证据、方案、分数） | 读取时只核对失效（已删除/绑定变化/索引变化），不重算不重排 |
| `saved_filter` | id, name, conditions（**只有标签条件**：分面〔作品、类型、人物、音高、其他标签〕+ 可选的标签表达式；所有者 2026-10-06：文字不能进筛选器，筛选器只放标签）, sort_order, version | 范围栏上的命名预设【基线变更：规格 07 §7.3 原含文字、性质、原片、星标、属性条件】 |

### 4.8 编辑记录、任务、导出、其他

| 表 | 关键字段 | 说明 |
|---|---|---|
| `edit` | id, created_at, label_code + args（可本地化的“这次修改”描述）, changes[(entity, id, field, before, after, version_before, version_after)], undo_of, undone_by | 统一编辑通道（§5）；没有重做 |
| `job` | id, kind, channel(`model`/`light`), status(`queued`/`running`/`succeeded`/`failed`/`cancelled`/`interrupted`), params（提交时冻结的业务输入）, device（冻结）, progress（阶段、done/total、消息码）, error（码 + 参数 + 日志路径）, affects（原片/采样 ID）, result, retry_of, items_total/ok/failed | 先持久化再执行（R19.1）；批量任务的逐条结果在 `job_item` |
| `job_item` | job_id, idx, target, status, error, result_ref | 批量语音分析/批量拉平的结果表，可只重跑失败项 |
| `export_file` | stable_key, path, kind(wav/video/reaper_wav/manifest), size, mtime, sha256, created_at | 按稳定键复用；被外部改过就报错不覆盖；从不自动删除 |
| `visual_binding` | id, owner_type(source/sample), mode(`sync`/`image`/`loop`/`materialized_clip`), media_file_id, clip_offset, version | 采样 > 原片 > 原片自带视频流 |
| `user_dictionary` | version, source_text, compiled_path, created_at | 全局一份；编译成功才原子启用 |
| `setting` | key, value, version | 走编辑通道（可撤销）；只作用于之后的操作 |
| `ui_state` | window, page, key, value | 重启恢复（勾选集合不恢复） |
| `model_probe` | model, file_sha, device_setting, status, ep_node_counts, error, tested_at | “文件就位 / 运行库可加载 / 实测通过”分开记（规格 14 §14.7） |

### 4.9 采样独立化（刚需，数据模型从阶段 1 起支持）

按所有者选定的形态 (b)（规格 04 §4.8、18 D32/D48）：

1. **声音**：对每个要独立化的采样，把它绑定资产的 `[start, end)`（两端各留 1 帧余量）解码为**无损 WAV 切片**（源是无损时用与源相同位深的整数 PCM；源是 MP3 正式音轨时用 32-bit float，与解码结果逐样本相同）写入
   `Library/Independent/<source-key>/`，作为该资产的 `asset_storage(kind=materialized_slice)`。采样的绑定（资产 + 区间）**不变**，
   所以测量（按资产共享）、固定结果、来源记录都继续有效——测的就是同一段声音（PCM 相同，切片无损正是为此）。
2. **画面**：按该采样的画面绑定生成视频片段（同步视频取原片对应区间），存入同一目录，作为采样的 `visual_binding(mode=materialized_clip)`。
3. **原片元数据**：删除原片时，若仍有已独立化的采样，原片记录保留为 `media_state=released`：作品、集数、来源类型、字幕版本与标注、OP/ED、
   资产角色等都在，标签继承与来源追溯照常工作；原片文件引用置空，未被切片覆盖的资产区间不可播放（明确报错）。
4. 删除原片时**不删**已独立化的采样及其切片/片段；其他采样、库内整轨、测量按规格 04 §4.5 级联删除（只删库内生成文件，不删磁盘原片与导出）。
5. 界面区分“已独立化”（采样徽标）与“媒体已释放”（原片徽标）；独立化采样不能再“返回原片”看前后文，界面说明原因。

> 物化切片用无损 WAV（所有者 2026-10-05：不用 FLAC，很多软件不支持），而不是 MP3 V0，是为了让“测量随资产保留”严格成立。

---

### 4.10 原片列表的组织（2026-10-06 所有者定稿：方案 A）

过程：Q9 独立素材区 → 层级顾虑 → 素材包提议 → 所有者第七、八轮决定：**沿用原片逻辑（规格 06 §6.6 原样），原片列表按作品分组、默认折叠**；层级不再特别处理。

- 每个导入的文件都是一个原片（`source`，可以是很短的纯音频）。**原片只有一种**（所有者 2026-10-07）：原片页「＋」与采样库「导入」是同一个导入框，区别只在「直接建立全长采样」默认勾不勾（采样库勾、原片页不勾）；任何原片之后也能「建立全长采样」。
- 媒体已释放的原片（`media_state=released`）留在所属作品组里。
- **分组**：一组一个作品（没有作品的在“未指定作品”）。组头写数量（“游戏 A · 1 个原片 · 1,240 个短音频”）；默认折叠，当前查看的原片所在组展开；折叠状态记住（`ui_state`）；组内按登记时间倒序（规格 03 §3.4），可搜索。
  组展开后可能上千行：原片列表规格要求不分页，用 React Aria 的 Virtualizer。
- **在既有入口内补齐**（所有者同意）：
  - 导入接受整个文件夹（含子文件夹；音频和视频都导入，与音频同名的视频/图片是它的画面），弹窗里一次设好作品（统一设为 / 按文件名推断，预览给出分组）、类型（与性质，勾了全长采样时）；
    已登记原片的重新归组用原片列表批量「作品与类型…」；导入前预览数量、能匹配到画面的数量、读不了的文件（列出，不导入）。再次导入已登记的文件不重复登记原片。
  - **同名画面自动绑定**（所有者 2026-10-06 同意）：同一文件夹里与音频同名（不含扩展名）的视频/图片，自动绑定为该原片的画面（规格 12 的画面绑定）；默认勾选，可在弹窗里取消。
    同名多个时按 视频 > 动图 > 静态图 取第一个，并在预览里列出冲突。之后也可对勾选的原片批量“匹配同名文件”。
  - 批量“重新定位”：对勾选的原片选一个新文件夹，按文件名与相对路径一次找回。
  - **原片文件夹**（阶段 3.13，所有者 2026-10-07）：设置里指定一个或多个原片文件夹（`source_root`），第一层子文件夹 = 作品（`work_folder`：来源类型、同名画面开关），原片记 `root_id` + 相对路径 `rel_path`。
    启动时与「重新扫描」时用轻量任务登记新文件，按文件快照认出移动/改名；文件删掉只标“文件找不到”。原片文件夹里的原片作品只跟文件夹走；「作品设置…」改名 = 改磁盘上的文件夹名并在一个事务里更新路径（失败回滚，不进撤销）。
    整个文件夹搬家用「更换位置…」按相对路径找回。不在原片文件夹里的文件仍用导入框登记。
  - 查看器只有一种，只按内容调整：没有视频时画面区显示绑定的画面或“纯音频”占位；没有视频又没有字幕时上面一行缩矮（2026-10-07 取消“短音频简化查看器”）。
- 数据上不需要新表；`source` 增加 `import_root`（导入时选的根文件夹，供批量重新定位用相对路径）。

## 5. 统一编辑通道

- 所有用户资料修改（规格 07 §7.6 列出的全部对象，含快捷编辑、默认轨、资产角色、保存筛选器、设置）都表示为一个 `EditBatch`：
  对象列表 + 字段级前后值 + 对象版本。
- **预览**：Core 计算变化集与逐字段对比，不写库；未知字段报错。
- **应用**：单事务；任一对象版本不一致或校验失败 → 整批拒绝，错误码指出第几个对象（R9.2）。
- **撤销**：从最近一次开始，找第一个“所有对象当前状态仍等于该次修改后状态”的修改，以一次新的编辑恢复 before 值；
  找不到 → “没有仍可安全撤销的资料修改；后续编辑不会被覆盖”。没有重做。
- 快捷编辑（星标、性质一键归类、改名、本地标签）同样产生 `edit`，只是不弹预览；界面在提示条上给“撤销”按钮。
- 脚本入口（阶段 11，P2）只能调用同一组公开命令，写入同样走预览 → 应用 → 可撤销。

---

## 6. 用户可见存储布局（目录名一律英文）

```
<Workspace>/                         工作区：用户数据（数据库、素材库、模型）。开发期 = 仓库内 dev-workspace/；发布版默认 ~/Documents/OttoSmasher Workspace/，设置里可换
├── Library/                         素材库：用户可见，不是缓存，不自动清理
│   ├── Tracks/
│   │   └── <作品 集数> [<id8>]/      每个原片一个目录，名字可读（建立时按作品与集数取名，之后不随改名移动）
│   │       ├── Separation/          分离声部（LAME VBR V0 MP3）
│   │       ├── Flatten/             拉平成品（MP3 V0）
│   │       └── Reimport/            回导成品（复制进来，保持原格式）
│   ├── Independent/
│   │   └── <作品 集数> [<id8>]/      独立化物化：WAV 声音切片、视频片段
│   ├── Exports/
│   │   └── 2026-10-05/              默认导出（WAV、视频片段），按导出日期分目录
│   └── REAPER/
│       └── 2026-10-05/              REAPER 原声 WAV、交接清单、.RTrackTemplate（试验）
├── Models/                          用户放置的模型权重：pydomino/ tsqyomi/ features/ flatten/
└── Data/                            应用数据（不给用户直接改）
    ├── library.sqlite3              数据库（WAL）
    ├── Measurements/                F0 帧、音高索引（永不当缓存删）
    ├── Cache/                       峰值、缩略图、频谱、临时解码 PCM（可清理；租约保护）
    ├── Jobs/<job-id>/               任务输入、输出、日志（成功后清理私有中间文件；失败保留证据）
    ├── Manifests/                   导出清单（规格 12 §12.1：放数据目录，不放导出目录）
    ├── Dictionary/                  用户辞典源与编译产物
    ├── Logs/                        核心日志、界面事件日志（滚动，有上限）
    ├── Backups/                     结构迁移前的一致性备份
    └── Staging/                     原子发布用的临时文件（与 Library 同卷）
```

- **长期固定的目录名一律英文**（`Library/`、`Tracks/`、`Separation/`、`Flatten/`、`Reimport/`、`Independent/`、`Exports/`、`REAPER/`、`Models/`、`Data/` 及其下各目录）；按原片、按日期生成的子目录不受限制，可以用中日文（所有者 2026-10-06）。子目录与文件名都经过可移植处理（规格 12 §12.1）。界面里每个原片/采样都有“打开所在目录”。
- **原子发布**：先写 `Data/Staging/`，校验后 `os.replace` 到目标；导出到其他卷（自定义导出目录）时先复制为同目录下的隐藏临时名再改名，
  未完成的发布记录在数据库里，启动时清理残留——用户可见目录里不会长期留下 `.part`/`.lock`（规格 12 §12.6）。
- **租约**：临时 PCM 等文件被任务使用时登记租约（数据库行，含进程 ID 与过期时间）；清理器跳过有租约或 15 分钟内生成的文件。
- **清理口径**：引用关系来自数据库外键（`media_file` 被谁引用），不是在来源记录里搜路径字符串（规格 17 §17.3 #20）。
- 空闲判定用 UI 上报的“最后一次用户输入时间”，界面轮询不刷新空闲计时；策略与规格 13 §13.3.3 一致（空闲 5 分钟、每小时至多一次、1 天、512/384 MiB）。

---

## 7. 界面国际化（只翻译文字）

所有者 2026-10-06：国际化只要翻译文字，不需要按语言格式化日期、数字这些。【基线变更：规格 15 §15.7“数字、时间、文件大小按界面语言格式化”】

- **文案资源**：`app/renderer/i18n/locales/<lang>.json`，按键查找；代码里只出现键：`t("library.count", {n})`。
  `t()` 自己写（几十行）：取当前语言的文案，替换 `{名字}` 参数；缺键在开发期直接报错。术语以规格 01 §1.6 为准；本轮只有 `zh-CN`。
- **单复数**：中文不需要。以后加英文时，需要单复数的文案拆成两个键（`…_one` / `…_other`），由 `t()` 按数量选——不引入 ICU 语法。
- **数字、时长、日期、文件大小**：全应用一种固定格式，不随界面语言变（秒数 3 位小数、`2026-10-06 12:01`、`1.2 GB`），规则集中在一个格式化模块里。
- **后端错误**：Core 返回 `{code, args}`（例如 `track-out-of-range {start} {end}`）；界面按当前语言渲染。日志只用英文错误码 + 参数。
- **稳定内部值**：性质、角色、分面、任务类型、来源种类等在数据里存内部值，显示名走资源（`nature.speech = 语音`）。
- **导出文件名固定词**（原混音、人声、拉平-、卡拍-、片段、局部-、试听片段）由 Core 生成：Core 随包带同一份文案里的“文件名词表”子集，
  按当前界面语言取值；切换语言只影响之后的导出。
- **两个独立设置**：界面语言（设置 → 通用）与首选采样语言（设置 → 原片，默认日语）。
- **测试**：脚本生成伪语言（每条文案加方括号并拉长），Playwright 跑主要页面，断言界面文字都带方括号（规格 16 R22.13）；
  静态检查：`app/renderer`、`core/ottosmasher` 源码里除注释、测试与文案资源外不得出现 CJK 字面量。

---

## 8. 采样语言的插拔点（为中文、英文预留）

```python
class LanguageProfile(Protocol):
    code: str                                    # "ja"
    def normalize(text) -> NormalizedText        # 逐码位替换，保持字符位置（日语：规格 08 §8.2.2）
    def g2p(text, dictionary) -> FrontendResult  # 音素、音素↔文字↔读音、版本（日语：pyopenjtalk-plus + tsqyomi）
    def split_syllables(reading) -> list         # mora/音节切分（日语：小写假名并入、ー 单独成拍）
    aligner: Aligner                             # 日语：pydomino（模型身份/版本写入测量）
    core_phonemes: frozenset                     # 音块核心（日语：a i u e o A I U E O N；cl 另计）
    leading_consonant_stops: frozenset           # 前导辅音停止标签（日语：pau AP spn N cl + 元音）
    def reading_key(text) -> str                 # 读音搜索的规范化（日语：平假名）
    dictionary_format: DictionaryFormat          # 用户辞典格式与编译器（日语：表记\t片假名 → MeCab）
    default_subtitle_rules: SubtitleRules        # 默认字幕规则（日语：规格 06 §6.2.1）
```

- 语言是**数据属性**：音频流、字幕版本、采样（及对齐文本）、测量输入都记录语言；默认取来源的语言标记或“首选语言”（默认 `ja`）。
- 与语言无关、直接复用：FCPE、停顿检测、音块合组的时间规则（以 `core_phonemes` 为参数）、占格推断、卡拍与映射、音高检索、拉平、导出、REAPER。
- 采样库按语言筛选是交集条件；在只有一种语言时不显示入口（规格 04 §4.9）。
- 本轮只注册 `ja`；新语言的前端与对齐模型由所有者另行定型。

---

## 9. 三大搜索的索引与性能方案（阶段 7 实现，2026-10-08）

目标（规格 15 §15.2、09 §9.6.5、10 §10.2.7）：约 **3 万条 × 3 秒**的语音采样上，常见查询 **30 秒内**完成；检索并行、可取消、不阻塞界面。开发机：M1 Pro（10 核）、16 GB。

### 9.1 进程与流程

- 命令（`search.speech` / `search.pitch`）在 Core 主线程先校验查询、快照范围（浏览条件 → 采样 ID）、算覆盖，立即返回检索 ID；
  分片交给**常驻只读进程池**（`core/search_worker.py`，spawn，N = min(6, 核数 − 2)），后台线程等结果，再回到主线程写固定结果（全部写入），发 `search.finished`。
- 取消：共享内存里每次检索一个标志；分片在循环里检查；2 秒内不退出就强制结束并重建进程池；被取消的检索不写固定结果。
- 检索不解码、不推理、不读波形（测试用“一调用就失败”的替身证明）。语音检索索引要解码算停顿，所以由「准备检索索引」任务预先构建（`speech_index`）。

### 9.2 语音检索（`algo/speech_search.py`）

- 列数据一次拼成数组：逐块条件、邻接（同一采样、同一停顿段、最大间隔）、首尾全部向量化；只对通过的窗口算节奏证据（整句与语段 × 近快/近慢，方案在进程内存缓存）。
- 同一次求解里记住建好的方案、检索不建倍快（`stretch.candidates(..., which)`，结果不变）。

### 9.3 音高检索（`algo/pitch_search.py`）

- 所有者 2026-10-08：**完整检索**——每个允许的 10 ms 起点都严格判定（不再 50 ms 粗筛 + 2000 候选），相邻合格起点成组取最好；忽略八度、时长弹性、滑音块。
- 实现：同一资产上候选区间合并读 F0（`Data/Measurements/f0`，不另建摘要索引），全部声音拼成一条数组；带内可靠帧、距离、能量、缺口用前缀和 O(1) 判每个起点；
  便宜的必要条件（缺口、每块可靠帧数）先筛；忽略八度先用“折叠到一个八度”的下界预筛再逐个八度精判；滑音块逐帧累计；稳定度只对剩下的起点算分位数。
- 原片音轨模式：整轨测完 F0 的音轨才检索；句首/句尾用台词标注（按映射换成资产秒）。

### 9.4 单音指标

指标存在 `acoustic_metric`（准备是显式任务：先补测 F0 再解码算指标）；筛选是即时浏览，条件进采样列表的 SQL（缺少所选指标不命中）。

### 9.5 性能实测（`tools/synth_library.py` + `core/tests/perf/`，2026-10-08）

3 万条 × 3 秒合成库，真进程池端到端（含写固定结果），冷启动：S3 必须满足节奏 2.8 s、按相似度 4.4 s、无 BPM 2.5 s、C-E-G 1.4 s、S5 人力 1.4 s、最坏（1 块无条件，30 万处命中）2.6 s；
音高两块 0.9 s、C-E 忽略八度 1.2 s、C-E-G 0.8 s、时长弹性 1.1 s、滑音 0.7 s。准备检索索引（真实 MP3）：300 条串行 14 s、6 进程 3.7 s。

---

## 10. 播放与媒体

### 10.1 libmpv 与“画面进页面”

- **mpv 渲染桥**（`app/native/mpv-bridge`，C++/node-addon-api）：在 preload 中加载，管理每个窗口的两个 libmpv 实例——
  **原片播放器**（视频 + 音频）与**试听播放器**（`vid=no`，列表/命中/详情/工作台试听共用）。
- **画面**：用 libmpv render API 渲染到离屏缓冲（先用软件渲染 `MPV_RENDER_API_TYPE_SW`，按画布实际像素尺寸输出 RGBA，例如 1280×720），
  写入与渲染进程共享的帧缓冲，页面用 WebGL 把它贴到 `<canvas>`。画面因此是普通 DOM 元素：弹窗、菜单、抽屉、缩放、切页都不需要任何特殊处理。
  解码仍用硬件（`hwdec=videotoolbox-copy` / `d3d11va-copy`）。性能不够时改为 GL 渲染到共享纹理（同一接口）。
- 范围播放：mpv 的 `ab-loop-a/b`（循环）与 `end`（单次）让**引擎**截停；任何普通跳转或播放/暂停先清除范围（规格 05 §5.3.1）。
- 外挂声部：`audio-files` + `aid` + `audio-delay`（= 原片范围起点 − 资产选区起点），加载期间原音轨静音；不转码不代理（R22.1）。
- 字幕：mpv 自带字幕关闭（`sid=no`）；当前字幕版本的原文用 HTML 叠加在画面 `<canvas>` 上（纯文本、白字黑边、按画面高度缩放）。
- 时钟：状态（播放/暂停/结束/代次）约每 50 ms 推送；**播放头每帧取 `player.position()`**：preload 里保存引擎逐帧推来的最新 time-pos（不节流）加流逝时间，正常播放中不小幅后退（实测 YY2-07-A 4 秒：每帧偏差 P95 7.2 ms、最大 15.7 ms、后退 0 次；旧的 50 ms 外推为 10.9 / 34.5 ms、后退 45 次）。不在每帧同步读 mpv 属性——会等 mpv 内部锁，打开/跳转时卡住页面（实测）。换源时用代次号丢弃旧事件。
- **波形组件与 mpv 的关系**：波形只做显示与交互（峰值与细节窗样本由 Core 按视口给出，不在浏览器解码音频）；播放全部交给 mpv。
  选区只能拖两端、不能整体拖；刻度、总览条、播放头、音素/字幕/区段车道、F0 金线、命中框都是同一组件的图层。
  Shift 吸附、⌥ 拖出（越过 4 px 才生成）等规格要求的手势直接在组件里实现。
- **libmpv 来源**（所有者同意直接下载，Q2）：macOS arm64 用 GitHub media-kit/libmpv-darwin-build v0.7.3 的 `video-full` 包（mpv 0.36.0 + FFmpeg 6.0，含 VideoToolbox；SHA-256 固定在 `tools/third_party.json`）；头文件取 mpv 官方 v0.36.0。Windows 的来源到阶段 10 定。原生播放不可用 → 明确报错，不换其他播放方式（P6）。
- **实现要点**（阶段 1 探针确认）：软件渲染在桥内独立线程里进行；`mpv_render_context_render` 默认按帧的显示时间阻塞，正好用来给画面定时，界面线程每个动画帧只取最新一帧（拷贝 + 纹理上传）。默认选项 `hwdec=videotoolbox-copy`、`sws-fast=yes`、`zimg-fast=yes`。

### 10.2 波形、频谱、缩略图

- 峰值金字塔（min/max，多级分辨率，长音频点数上限）由 Core 后台用 ffmpeg 解码生成，懒加载，不阻塞打开与跳转；挂波形不重置播放头。
- 频谱：取所选音频窗口（≤30 秒）实算 STFT，固定 −90–0 dB，对数/线性/Mel（规格 05 §5.3.2）。
- 缩略图：采样本地中点经映射后的原片时间取帧；限制并发、缓存；画面绑定变化后失效。

### 10.3 解码、编码、导出

- 按区间解码：ffmpeg `-ss` 精确定位 + `-t`，输出 float32 PCM 管道；MP3 正式音轨依赖 LAME/Xing 头去编码延迟，随机读预滚 2 秒再丢弃（规格 14 §14.9）。
  用 24 kHz 斜坡信号的合成测试保证首样本不错位（R21.5）。
- MP3 V0 编码：ffmpeg + libmp3lame，写 Xing/LAME 头；编码后解码校验长度（只允许尾部 0–1152 帧填充），否则失败并保留原 PCM（规格 13 §13.3.2）。
- 导出 WAV：PCM 24-bit，采样率/声道跟随源；文件名按模板（§7、规格 12 §12.1）；稳定键复用；被外部改动报错不覆盖。
- 视频片段：ffmpeg 生成 H.264 MP4 + AAC；卡拍版“同映射变速”逐帧按逆映射取最近源帧（不插帧）；超出视频流的部分补黑帧并提示（规格 12 §12.5）。

### 10.4 拖出与 REAPER

- 拖出：Option/Alt 按下时冻结请求 → 移动 > 4 px 才请求 Core 生成 → 生成期间提示，Esc/松手/失焦放弃 → 完成且仍按住时主进程 `webContents.startDrag`；
  进入系统拖拽后 Esc 交给系统。生成失败用消息提示（不吞错误）。（Electron 的 startDrag 必须在拖动手势中调用，阶段 2 探针验证“生成后再发起”的时序。）
- REAPER：Core 生成未烘焙原声 WAV（`Library/REAPER/<日期>/`）与 `<ITEM …>` 文本（规格 12 §12.3，12 位小数、引号选择、单调性校验；`domain/reaper.py`、`core/handoff.py`）；
  主进程（`reaper:copy`）向 Core 要文本，用 Electron 44 的 `clipboard.write([new ClipboardItem({'electron application/osclipboard;format="REAPERMedia"': …})])`
  写入（NUL 分隔、双 NUL 结尾），写后 `clipboard.read()` 回读校验；页面不能往剪贴板写任意内容。Windows 实测前标“未验收”。

### 10.5 节奏与卡拍（阶段 6）

- 算法：`algo/rhythm.py`（音块、停顿、语段、时值、原节奏束搜索、纯 mora、目标拍、逐音属性）、`algo/stretch.py`（控制点、帧域时间映射、语音速度、候选密度、原速二分）；纯函数。
- 渲染：`media/stretch.py`，桥与弹性停顿片分别用 Rubber Band CLI `-3 -D <秒>` 伸缩到精确帧数（实测精确；time map 偏 20 ms 以上所以不用），核心逐样本复制，桥两端 3 ms 交叉淡化。
- Core：`core/rhythm.py`（逐采样参数 `sample.rhythm`、节奏视图、方案按需计算、试听渲染缓存 `Data/Cache/rhythm/<键>.wav`、全局 BPM 设置 `rhythm.bpm`），
  试听播放器按键解析渲染结果（`playback.resolveRender`），不接受路径。导出与交接在 `core/handoff.py`（卡拍 WAV 的清单写 `Data/Manifests/`，组合两层映射）。

---

## 11. 任务系统

- 两条通道：模型（默认并发 1）、轻量（默认 2；设置 1–4）。排队任务不占进程。
- 提交时冻结业务输入与设备设置；重试 = 相同业务参数的新任务 + **当前**设备设置。
- 进度结构化：`{stage, done, total, percent, message_code, args}`；Studio 的 `task_progress`/`task_stage` 映射到同一结构（规格 14 §14.6.2）。
- 任务摘要很轻（不含大结果），声明影响的原片/采样；UI 只在状态或进度变化时更新。
- 任务进程启动时加载需要的 ONNX 会话（统一会话工厂：CPU 默认；开启加速时 [CoreML/DirectML, CPU]，请求的 EP 没进入会话就报错；
  首次推理后用 profiling 统计各 EP 节点数，写 `model_probe`）。
- 日志：每任务一个日志文件 + 外部工具的命令/版本/设备/输入输出路径；保留上限（按数量与天数滚动）。

### 11.1 PyMSS Studio 适配（规格 14 §14.6）

- 发现安装与活动推理环境、列模型（`downloaded` 且 `supported`）、按名称/别名匹配、声部按 `/ | ,` 拆分且保留原样大小写。
- 每次调用独立子进程：`<Studio python> <resources>/python/worker.py <cmd> --payload <json>`；环境变量按契约设置，删除 `PYTHONPATH`/`PYTHONHOME`；
  stdin 关闭、stdout 按 UTF-8 逐行解析事件、stderr 写日志；退出码非 0 **或任何 `error` 事件** → 失败；`download` 强制 false。
- 推理前后各算一次模型指纹，不一致拒绝；输出只信任 `task_done.outputs`，核对路径、样本数（差 ≤ 1）、声部齐全；任何不完整都不登记。
- 测试用“伪 Studio worker”脚本（逐行输出事件）覆盖成功、部分失败退 0、缺输出、时长不符、超时、取消。

---

## 12. 分阶段的测试策略

| 层 | 内容 | 何时跑 |
|---|---|---|
| 单元 | `domain/`、`algo/` 的纯函数，直接用规格 16 第二部分的数值例子（R3 映射、R5 说话人、R6 OP/ED、R10 前端、R12–R15 算法、R17 拉平……） | 每次提交前 |
| 合成 | 斜坡信号、220+880 Hz 混音、置零段、合成 F0 帧、内联 SRT、合成节奏骨架（规格 16 第三部分）；伪 Studio、伪 ONNX Runtime；“一调用就失败”的重操作替身（证明检索不解码不推理） | 每次提交前 |
| 集成（真实素材） | 通过 `OTTO_FIXTURES` 指向交接包，**小批**跑 clips/ 与指定整集片段；不全库跑模型；输出只写临时工作区 | 阶段验收前 |
| 界面 | Vitest + Testing Library（组件：统一选择规则、范围栏、检索画布、快捷键焦点）；Playwright 驱动 Electron（端到端、伪语言）；人工只验原生播放、拖放到 REAPER 这类自动化证明不了的 | 阶段验收前 |
| 性能 | 1 万条分页（R8.9）、3 万条三大搜索（R14.15） | 阶段 7、8 |
| 平台 | Windows x64：最后用 GitHub Actions 的 Windows 机器构建（需要所有者届时授权推送）；所有者手动实机验收，验收前一律标“未验收” | 阶段 10 |

各阶段的验收重点（对应规格 16）：

| 阶段 | 自动化重点 | 真实素材 / 人工补充 |
|---|---|---|
| 1 骨架 | 编辑通道（R9）、任务（R19：持久化、进程树取消、只杀本任务、重试、中断）、迁移与备份、模型 SHA 检测、伪语言 | 应用启动、三页常驻、设置读写 |
| 2 播放闭环 | R1、R3、R21.1–3/8、R22（解码区间、逐样本导出、文件名可移植、拖出状态机） | YY2-07 整集播放跳转、范围截停、拖出 WAV 到 Finder/REAPER |
| 3 准备链路 | R2、R4–R7（字幕规则表、版本、OP/ED、性质预填、标签判定区间）；伪 Studio | YY1-01 字幕导入与 OP/ED 数值（S1.5）、S10、S11；Studio 实跑一个短片段 |
| 4 语音分析 | R10、R11（前端例子、采纳规则、人工版本）、FCPE 前端数值 | S1.8 与参考输出对比 9 句 |
| 5 拉平 | R17、11 §11.7 全部数值例子 | S4 听感对比 |
| 6 节奏与卡拍 | R12、R13（占格、映射、核心逐样本）、R21.4–7（REAPER 文本） | REAPER 粘贴人工验收（macOS） |
| 7 三大搜索 | R14、R15、R16；3 万条性能 | S3、S5 |
| 8 采样库完善 | R8、R9 | — |
| 9 画面与周边 | R20、R21.9、独立化与删除（S12） | S7、S8 |
| 10 Windows | 打包、冒烟（规格 15 §15.8） | Windows 实机 |

---

## 13. 风险与需要尽早验证的技术点（阶段 1 的探针）

| 风险 | 验证方式 | 不行时的备选 |
|---|---|---|
| mpv 渲染桥：软件渲染 + 画布在 1080p HEVC10、24 fps 下是否流畅，拖动/逐帧是否及时 | **阶段 1 已验证**（2026-10-06，M 系列 Mac，YY1-01，画布 1920×1080）：硬解 videotoolbox-copy；显示 24.1 fps、丢帧 0；渲染线程 13.2 ms/帧（默认缩放 20.2 ms）；界面线程 0.5 ms/帧（最大 2 ms）；跳转 14–61 ms；逐帧 11–103 ms；渲染进程约 36% 单核。复测：`OTTO_PROBE_FILE=<整集> npx playwright test e2e/probe.spec.ts` | GL 渲染到共享纹理（暂不需要）；再不行才考虑原生子视图（会带回遮挡问题，先问所有者） |
| 原生扩展在 Electron 44 / Windows x64 上构建与加载 | 阶段 10 用 GitHub Actions 构建；之前保证构建脚本两平台通用 | 改为独立 utility 进程 + 共享内存 |
| `startDrag` 在“越过阈值后才异步生成文件”的时序下能否发起系统拖拽 | 阶段 2 探针（拖到 Finder、REAPER） | 先生成到暂存再在下一次移动事件发起；仍不满足规格时先问所有者 |
| mpv 对 LAME 无缝 MP3 的样本级对齐 | 合成斜坡 MP3 的偏移测试 | 正式音轨改存 FLAC（要所有者同意，涉及存储预算） |
| pydomino C++ 扩展在 Windows 上构建 | 同上（GitHub Actions） | 已改为自写最小 CPython 绑定（不依赖 pybind11/Eigen/上游 ORT），setuptools 调 MSVC 编译；Windows 未实测 |
| pyopenjtalk-plus 导入时加载旧读音模型 | 测试“导入不加载任何模型”（test_openjtalk） | 已做：导入前给 `yomi_model.nani_predict` 放空模块占位（`lang/ja/openjtalk.py`），tsqyomi 会话由工厂创建后交给库 |
| 检索 3 万条 30 秒 | 合成库基准 | numba 热点编译 |
| wavesurfer 在 24 分钟整集 + 深度缩放下的流畅度 | **阶段 2 已定（2026-10-07）**：wavesurfer 只能一次喂整段峰值，放大到几十毫秒要几千万点、元素宽度超浏览器上限；调研 peaks.js、waveform-playlist 等也都只接受覆盖全程的固定分辨率数据，没有“按可见范围向后端取数”的接口（所有者提议后调研，见 QUESTIONS 第五节） | **已采用**：整集时间线、舞台、工作台都用同一个自研画布组件，按视口向 Core 取峰值（≤32000 点；≤30 秒细节窗精确解码到样本级）；不引入 wavesurfer（所有者 2026-10-07，第二轮调研无现成组件满足） |

---

## 14. 分发（阶段 10 细化）

- electron-builder 生成目录产物：macOS `.app`（ad-hoc 签名；原生扩展与 libmpv 去绝对 rpath）、Windows 便携目录；各打成 ZIP，严格 < 2,000,000,000 字节。
- 包含：Electron 运行时、前端、mpv 渲染桥与 libmpv、Python 运行时（python-build-standalone）与 Core 依赖、ONNX Runtime、ffmpeg/ffprobe、rubberband、
  G2P 辞典与 tokenizer、模型配置等非权重支持文件。不包含：模型权重、PyTorch、PyMSS Studio、用户素材。
- 程序目录只读；工作区与程序分离；不需要首次启动“释放运行库”。
- 冒烟检查：含中文与空格的隔离路径、清空 Python/Conda 环境变量、空工作区、运行库探测、原生播放截停一段短区间、媒体工具可用。
- 许可证：GPL-3.0-or-later（Rubber Band 为 GPL）；随包附第三方声明。

---

## 15. 为 agent 预留（2026-10-07，所有者问；长期方向，不在当前阶段实现）

所有者的问题：将来能否把一部分工作交给 agent，甚至自动制作音MAD。
规格 03 §3.6 / 07 §7.7 只规定了阶段 11 的“脚本批量入口”（由“非 agent 的大模型”帮用户写脚本）。让 agent 直接操作属于基线之外的扩展，
真做时按 02 §2.7 写提议。本节只记录：现有架构哪些地方已经能承接，哪些还缺，以及现在就该顺手做的便宜事。

### 15.1 已经具备的地基

| 地基 | 在哪里 | 对 agent 的意义 |
|---|---|---|
| 业务全部在 Core，界面只是客户端；Core 可脱离界面运行 | §2、§3；`python -m ottosmasher` | agent 与界面调用同一组命令，没有“只有界面能做”的业务 |
| 命令 = 公开业务接口，错误只返回“错误码 + 参数” | §2、§7 | 机器能直接判断失败原因，不用解析界面文字 |
| 统一编辑通道：预览 → 原子应用 → 可撤销，对象带版本 | §5 | 自动写入可先给人看影响；出错能撤回；不会覆盖人后来的修改 |
| 任务：先持久化、参数冻结、结构化进度、可取消可重试、取消不留半成品 | §11 | agent 能提交长任务并跟踪，不会留下半截登记 |
| 固定结果、导出文件、REAPER 交接都是持久对象 | §4.7、§10.3、§10.4 | agent 的“检索 → 挑选 → 交接”每一步都有可引用的产物 |

### 15.2 还缺的

1. **接入通道**：Core 只经 Electron 主进程的管道访问，且一个工作区只允许一个 Core（工作区锁）。agent 必须连到正在运行的同一个 Core，
   否则会与界面争用。可行做法：由主进程额外提供一个仅本机可用的 MCP 端点（stdio 或本机套接字），转发给 Core；界面与 agent 共享同一套命令与事件。
   若采用本机网络端点，要补上规格 16 R23.2 的本机来源校验（外部 Host → 403、外站 Origin 写请求 → 403）。
2. **权限分级**：检索、试听、读取可放开；写入默认“先预览、人确认再应用”；删除原片/采样、独立化、覆盖类操作永远要人确认；模型任务有额度与并发上限。
3. **来源标记（actor）**：编辑记录、任务、新建的采样与资产记录“谁做的”（用户 / 脚本 / agent + 会话 ID），能按来源筛选、整批撤回。→ QUESTIONS Q23
4. ~~**机器可读的命令目录**~~（已做，阶段 4.0）：`docs/api/commands.json` = 每条命令的作用类别（read / write / job / ui / app / dev）、一句说明、参数与返回的 JSON Schema，加错误码表（码、参数名、说明）；前端 `app/renderer/api/generated.ts` 由同一份产物生成。→ QUESTIONS Q24
5. **编排层**：“自动制作音MAD”需要把采样排到时间线上（按旋律、歌词、节拍），规格里没有这一层。自然的边界是：agent 用我们的检索、卡拍、导出，
   产出 REAPER 工程或条目，成片仍在 REAPER 里完成；我们不在应用里做多轨编辑器。
6. **数据外发**：若 agent 使用云端大模型，台词文本、甚至音频会离开本机。测试素材（fixtures）按规则不得上传；用户自己的素材是否允许外发，需要一个明确的设置，默认不允许。

### 15.3 现在就保持的做法（成本低，越早越省）

- 业务逻辑只写在 Core 命令里，界面不做业务判断（已是规则，见 AGENTS §9）。
- Q23、Q24 所有者 2026-10-07 已同意：actor 字段已加（迁移 0004，`core/actor.py`：Core 连接上的临时触发器按请求来源填写，RPC 可带 `actor`）；命令目录已做（阶段 4.0，`core/ottosmasher/api/`）。
- 新命令一律在 `Core._register` 登记（名称、作用类别、参数与返回类型、一句英文说明），类型写在 `api/types.py`，然后运行 `.venv/bin/python -m ottosmasher.api.catalog`；测试与 e2e 打开 `OTTO_STRICT_API=1`，返回值与目录不符直接报 `result-mismatch`。
