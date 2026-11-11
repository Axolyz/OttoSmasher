# OttoSmasher 架构

> 现在的系统是怎么搭的：进程、代码、数据、存储、媒体、任务、分发、命令行。2026-10-05 起草，2026-10-31 按 0.1.x 的现状审过一遍。
> 产品规矩见 [DECISIONS.md](DECISIONS.md)，原始需求见 [spec/](spec/README.md)（文中“规格 xx §y”“R4.4”指它）；章节号保持不变，代码注释里的“ARCHITECTURE §x”指这里。文中“阶段 N”是开发期的阶段编号，只表示出处（[history/](history/README.md)）。

---

## 0. 一页总览

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
| 模型推理 | ONNX Runtime（Windows 用 onnxruntime-directml），统一会话工厂 | 规格 14 §14.7；包入口 `ottosmasher/__init__.py` 在导入 onnxruntime 前设 `ORT_DISABLE_TELEMETRY=1`：1.30 在 macOS 自带遥测上传，退出时与静态析构竞争偶发 SIGABRT（134），也违背“不上传任何东西” |
| 媒体工具 | ffmpeg/ffprobe、Rubber Band CLI（R3） | 规格 14 建议项 |
| 界面国际化 | **只翻译文字**：自写的小型 `t(key, 参数)` + 每种语言一个 JSON 文案文件；伪语言测试；后端只返回“错误码 + 参数” | 所有者 2026-10-06：只要翻译文字，不需要按语言格式化日期数字；不引入国际化框架（§7） |
| 打包 | `tools/package_mac.py` 直接组装 `.app`（复制 Electron、随包 python-build-standalone + 按 uv.lock 装 Core、媒体工具、模型）→ ZIP（§14） | 不用 electron-builder、conda-pack；只发 macOS |
| 测试 | Python：pytest；前端：Vitest + Testing Library；端到端：Playwright 驱动 Electron；发布包冒烟（§12） | 规格 16 第三部分的合成测试做法 |

所有依赖装在项目内：`node_modules/`（含 Electron 二进制）、`.venv/`、`.uv-python/`、`third_party/`。所有者已同意“缺什么依赖都可以装”；
仍优先项目内安装，确实只能全局安装的（目前没有）会先说明。

---

## 1. 技术栈与理由

### 1.1 为什么是 Electron + Web 前端

2026-10-05 与所有者重新权衡后从 PySide6 改为 Electron：Web 生态大、接手门槛低；视频用 libmpv render API 画进页面 `<canvas>`（§10.1），避开旧版“原生视图盖住网页”的整类问题；
前后端经管道通信（不开端口），类型由 Core 的命令定义自动生成。代价是两套运行时（Chromium + Python）和一个小的原生扩展。
不选 Tauri（系统 WebView 在两个平台是不同内核，还要引入 Rust）、不用浏览器 `<video>`/MSE 播 HEVC（做不到样本级截停，旧版失败过）。权衡过程见 [history/QUESTIONS.md](history/QUESTIONS.md)。

### 1.2 主要依赖（版本以 `package-lock.json`、`uv.lock` 为准）

| 依赖 | 版本 | 用途 |
|---|---|---|
| electron | 44.6 | 桌面外壳 |
| react / react-dom | 19.3 | 界面 |
| vite（界面）+ esbuild（主进程与 preload） | 8.3 / 0.28 | 构建 |
| typescript | 7.0 | 类型检查 |
| react-aria-components | 1.21 | 无样式的交互基础件（列表、菜单、弹层、对话框、选择框、组合框、数字输入……），样式全部用自己的设计令牌（§1.3） |
| lucide-react · zustand · @msgpack/msgpack | 1.52 · 5.0 · 3.1 | 图标（ISC）· 界面状态 · 与 Core 的帧编码 |
| node-addon-api + node-gyp | 8.9 / 13.1 | libmpv 渲染桥（原生扩展，§10.1）；`tools/build-native.mjs` 用 Electron 头文件编译 |
| Python 3.12（uv 托管，装在 `.uv-python/`） | — | Core 与任务进程 |
| msgspec、numpy、scipy、regex、onnxruntime 1.30.0（Windows：onnxruntime-directml 1.24.4）、pyopenjtalk-plus[tsqyomi] 0.4.1.post9 | 见 `pyproject.toml` | Core；pydomino 只编译上游 tokenizer + Viterbi 成 `_domino` 扩展（`core/native/domino_ext.cpp` + `tools/build_domino.py`），ONNX 推理走统一会话工厂 |
| pytest、hypothesis；vitest、@testing-library/react、@playwright/test | — | 测试 |

外部可执行文件与库：ffmpeg / ffprobe 与 Rubber Band（开发期用 Homebrew 的，发布包用固定版本的）、libmpv（media-kit 的 macOS 构建，`tools/third_party.json` 固定版本与 SHA-256）。

### 1.3 组件库与设计语言

- **交互基础件用 React Aria Components（无样式），外观全部用自己的设计令牌 + 组件清单**（所有者 2026-10-06；与 Base UI、Ark UI、Radix 的比较见 history/QUESTIONS Q18：同样的组件它并不更重，而且有我们最需要的列表勾选、组合框、标签块、数字输入）。
- 每个 React Aria 组件只在 `app/renderer/components/` 里包一次，页面只用包好的；缺的（右键菜单、提示条、波形与画布类业务组件）自己写进组件库。
- GridList / Table 在多选 + toggle 模式下单击行触发 `onAction`（= 查看），复选框只管勾选，正好对上 DECISIONS §13 的集合规则。
  注意：行会被 React Aria 缓存，render 用到的外部状态要放进 `dependencies`（`CollectionList` 的 `renderDeps`、`ActionList` 的 `renderDeps`）。
- **设计令牌**（颜色、性质四色、字号阶、间距、圆角、阴影、密度、动效时长，深浅两套，CSS 变量，`app/renderer/styles/tokens.css`）+ CSS Modules，不引入 Tailwind，不套用 Material / Fluent / Ant。
- 字体用系统字体；**采样名、台词、读音标 `lang="ja"`**，让日文汉字用日文字形。

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
| 命令行 `otto`（agent / 脚本） | 外部进程，经 Core 的本机端点（§15） | 请求进 Core 主线程同一个队列；只在应用开着时可用 |

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
- 每个写事务产生“变化集”（对象类型 + ID + 操作），Core 推给界面；**界面只显示“资料已更新”类提示，不自动刷新/重排/重选**（P8）。例外：采样库当前页已有的行用 `samples.rows` 就地换成最新状态（合并 400 ms，不插入、不删除、不重排；DECISIONS §13）。
- 界面每个请求带“代次”，过期响应丢弃（规格 17 §17.1 #3）。

### 2.5 安全

- 渲染进程只加载本地打包的页面，CSP 禁止远程脚本与远程资源；`nodeIntegration` 关闭、`contextIsolation` 开启，preload 只暴露白名单 API；禁止打开新窗口与跳到外部地址。
- preload **不放进沙箱**（`sandbox: false`）：它要加载 mpv 渲染桥这个原生扩展并直接在画布上绘制。页面世界仍然没有 Node；播放器只接受主进程/Core 给出的文件（阶段 1 探针的路径来自主进程的对话框或环境变量，页面不能指定路径）。
- mpv 渲染桥只接受 Core 解析过的“播放句柄”（资产 ID + 区间 → 已核对文件快照的路径），渲染进程不能让它打开任意文件或 URL（R22.7）。
- 没有本地 HTTP 服务（R23.2 的 Host/Origin 校验因此不适用）。
- 命令行端点（阶段 A，§15）：本机套接字（macOS AF_UNIX，文件 0600；Windows 命名管道，未实测）+ 每次启动随机的 32 字节密钥（HMAC 质询），
  地址与密钥只写在工作区 `Data/agent-endpoint.json`（0600）；只传 msgpack，不反序列化 pickle；外部连接不能调用 ui / app / dev 类命令，撤销不了的命令要所有者在应用里确认。

---

## 3. 代码结构

```
app/                     Electron + 前端（TypeScript）
  main/                  主进程：窗口、Core 进程管理（core-client.ts）、IPC 转发、拖出、剪贴板（REAPERMedia）、退出流程；paths.ts = 源码运行 / 发布版的位置
  preload/               白名单 API（core.request / core.onEvent / player.* / files.* / agent.*）；player.ts、picture.ts（详情区画面）、playback.ts
  shared/                主进程与界面共用：protocol.ts（IPC 类型）、i18n.ts、repo.ts（仓库地址）
  native/mpv-bridge/     C++（node-addon-api）：libmpv 播放器、render API、共享帧缓冲
  renderer/              React 界面
    shell/               左侧导航、顶栏、底部播放条、命令面板、任务抽屉、操作历史、agent 确认框、工作台（语音分析、拉平、分离结果）
    library/             采样库：列表、查找栏与范围行、检索浮层与画布、详情区
    sources/             原素材页：列表（含台词搜索）、查看器（画面 + 台本 + 时间线）、准备清单、各种对话框
    workbenches/         设置、字幕规则等全屏工作台
    tools/               工具页（组件样张、开发期 mpv 探针；只在开发版显示）
    components/          组件库（React Aria 包一层）：CollectionList / ActionList（统一选择规则）、Menu、Overlay、Fields、WaveCard（自研波形画布）……
    state/               zustand：store.ts（全局状态）、commands.ts（命令面板来源）、settings.ts
    i18n/                t()、locales/zh-CN.json、en.json、伪语言
    api/                 core.ts（call() 按命令名推断类型）+ generated.ts（由 Core 的命令目录生成，不手改）
core/
  native/domino_ext.cpp  pydomino 的 tokenizer + Viterbi 小扩展
  ottosmasher/
    api/                 命令目录：types.py（参数与返回的 TypedDict）、registry.py（登记、校验、严格模式核对返回值）、catalog.py（导出 docs/api/commands.json 与 generated.ts）、events.py
    core/                Core 进程：server.py（命令登记与分发、事件）、rpc.py、edits.py（统一编辑通道）、scheduler.py（任务）、各领域服务（sources、samples、text_layer、subtitle_import、speech、units、rhythm、search*、flatten、separation、exports、video_export、independence、storage……）、agent_link.py（命令行端点）
    domain/              纯领域逻辑：mapping、naming、subtitle_rules、rules、oped、filename、reaper、tag_expr……
    algo/                基线算法（纯函数 + numpy）：音块、停顿、语段、量化、拉伸映射、语音检索、音高检索、拉平定音、声学指标
    lang/                语言插拔（LanguageProfile；本轮只有 ja：文本前端、用户辞典、pyopenjtalk 适配）
    models/              onnx.py（统一会话工厂）、registry.py（模型位置与 SHA-256、随包模型）、download.py、probe.py、domino.py、fcpe.py、hifigan.py、f0store.py
    media/               ffprobe、区间解码、MP3 V0 编码、WAV、峰值、缩略图、拉伸渲染、视频片段
    studio/              PyMSS Studio 适配（发现、worker 协议）
    jobs/                任务进程入口（worker.py 按任务种类分发）
    store/               db.py（连接、迁移、备份）、migrations/（0001–0017，只增不改）、workspace.py（工作区布局与锁）
    platform/            进程组 / 作业对象
    cli/                 命令行 otto：main.py、client.py、skills.py、guide/（说明书、内置 skill、playbook 模板）
    resources.py         “仓库还是 Resources”的统一判断（源码运行 / 发布版）
  tests/                 unit/、integration/（真实进程与模型；带 OTTO_FIXTURES 时跑真实素材）、perf/（3 万条合成库）
e2e/                     Playwright 驱动 Electron 的端到端测试（含伪语言、发布包冒烟）
tools/                   uv / npm 包装、otto、第三方拉取与编译、发布打包 package_mac.py、clone-workspace、合成数据、i18n 检查
skills/ottosmasher/      托管的 agent 入口 SKILL.md
docs/                    开发文档；spec/（原始规格）、history/（过程记录）、api/commands.json（生成）
```

`domain/`、`algo/`、`media/`、`lang/`、`models/` 不依赖资料库与 Core（引擎边界，见 §15.6），规格里的数值例子直接写成单元测试。

---

## 4. 数据模型

> 业务事实以规格 04 与 DECISIONS 为准；表结构以 `core/ottosmasher/store/migrations/` 为准（0001–0017），下面是要点。ID 一律为不透明的随机 128 位十六进制串（`uuid4().hex`），
> 文件位置是独立字段；**不做媒体内容指纹**，文件是否被替换用“文件快照”判断（§4.1）。所有用户可编辑对象都有 `version`（乐观并发）和 `created_at`/`updated_at`；写入记来源（`actor_kind`、`actor_session`）。
> 显示文字不入库：性质、角色、来源种类等存稳定的内部值（如 `speech`、`vocal`），界面按语言显示。

### 4.1 原片与流

| 表 | 关键字段 | 说明 |
|---|---|---|
| `source` | id, path, path_key, import_root, root_id, rel_path（原素材文件夹里的相对路径）, file_snapshot, duration, work, episode, source_type, subtitle_path, default_audio_stream, media_state(`available`/`released`), visual_binding_id, version | 原片（可以是视频、长音频或很短的纯音频）。`media_state=released` 是删除原片后保留独立化采样的“媒体已释放的原片”（§4.9）。列表按作品分组、默认折叠（§4.10） |
| `source_stream` | source_id, kind(audio/video), ordinal（第几条音频/视频流）, container_index, codec, sample_rate, channels, bit_depth, language, title, start_time, duration, is_attached_pic | 封面图不算视频（规格 05 §5.1）；音轨按“第几条音频流”选择（R22.2） |

**文件快照**（取代内容指纹，所有者 2026-10-06）：大小 + 修改时间 + 流签名（各音频/视频流的编解码、采样率、声道、时长）。不读文件内容、不算哈希。
播放/导出/处理/测量前核对快照，不一致即报“音源已改变”（不替换、不回退；用户可“重新定位”到正确文件）。库内生成文件同样用快照。
仍然保留的哈希只有两类（都不是媒体内容指纹）：字幕文件内容指纹（记在段的来源记录里；字幕版本已取消，所有者 2026-10-09）；模型文件 SHA-256（规格 14 的定型校验与 Studio 模型指纹）。

### 4.2 声音资产、角色、默认轨

| 表 | 关键字段 | 说明 |
|---|---|---|
| `sound_asset` | id, source_id, origin(`stream`/`separation`/`flatten`/`reimport`), media_file_id, stream_ordinal, duration, mapping（控制点数组）, input_asset_id, input_start, input_end, stem_name（原样大小写）, production（操作、参数、模型身份/指纹、算法版本）, language, reimport_id, from_separation | 不可变。声音的测量（F0、单音指标）按“资产 + 音频流”共享（同一资产内覆盖所需区间即可复用；不同资产不共享）；**音素不按资产，属于原素材时间线**（§4.5）。`input_asset_id` 等构成**加工链**（`core/lineage.py`：详情区「加工链」、「返回原素材」换到的整轨 = 沿链往上第一条整轨）。建资产时由触发器从输入资产抄下两件事（迁移 0015）：`reimport_id` = 从哪个回导成品来的（回导成品 = 自己），`from_separation` = 是不是从分离声部来的 |
| `asset_storage` | asset_id, range_start, range_end, media_file_id, kind(`primary`/`materialized_slice`) | 资产的**物理存储**。正常只有一条 primary；独立化时增加覆盖采样区间的无损切片（§4.9）。这是规格 04 §4.2.4 允许的“显式存储迁移”：只改位置/编码，不改时间关系 |
| `media_file` | id, path（工作区相对或绝对）, location(`external`/`library`), file_snapshot, format, sample_rate, frames, encode_manifest | 原片文件、库内音轨、回导文件、物化切片 |
| `asset_role` | asset_id, role(`vocal`/`sfx`), state(`on`/`removed_by_user`) | 角色集合；“用户显式移除”单独记，系统不再加回（R2.5） |
| `default_track` | source_id, role, asset_id | 每原片每角色最多一条；写入时校验“完整覆盖且未变速（容差 20 ms）” |

映射（`domain.mapping.Mapping`）：控制点 `[(local, source)]` 两列严格递增，首点 local=0、末点 local=资产时长；分段线性；越界报错，不外推不夹取；
提供 `crop(a,b)`、`compose(child)`、`to_source(t)`、`to_local(t)`；帧/样本舍入允许一帧。**所有时钟换算只走这里**（规格 17 §17.1 #1）。

### 4.3 原片上的时间对象：文本层的段、音效提示、区段标签、OP/ED（所有者 2026-10-09【基线变更】，迁移 0012 / 0013）

原片上的四类对象各做一件事（DECISIONS §1、§3；原始记录 history/QUESTIONS「原片上的四类对象」）：段 = 说了什么（给分析）；音效提示 = 给人工拣选；区段标签 = 时间上的属性；采样 = 切好、能用的单位。
字幕导入是一次显式操作、四类一起进（`core/subtitle_import.py`）；**没有字幕版本**：重新导入就是一次批量编辑（新增 / 无变化 / 替换 / 跳过，碰到受保护的段跳过，可逐行强制替换），整次导入一个编辑批次、可撤销。

| 表 | 关键字段 | 说明 |
|---|---|---|
| `text_segment` | id, source_id, start, end（原片秒）, text（= 对齐文本，保留换行）, speakers（JSON 有序名单，按规则确定读出的那部分）, speakers_withheld（原文有标注但没记，0017）, origin(`subtitle`/`typed`), provenance（字幕文件名、指纹、行号、原文 `raw`、导入时间；合并产物带各段原文）, edited, speaker_edited, deleted, version, actor | 每个原片一层，不设作用域；字幕来源与手输同级。**受保护** = edited（改过文本或边界、拆分合并产物、切开后缩短的旧段、手输段）或任一条轨上有人工音素版本；只改说话人记 speaker_edited（只让「按当前规则重新生成说话人」跳过）。段长度上限 120 秒（查询下界）。复合操作在 `core/text_layer.py`：加段（重叠时替换 / 切开 / 取消）、拆分、合并（删旧建新） |
| `sfx_hint` | id, source_id, start, end, text（括号内容）, origin(`subtitle`/`manual`), provenance, edited, deleted, version | 作用于整个原片、所有轨可见；不对齐、不带标签。手动新增或改过的受保护 |
| `range_tag` | id, source_id, scope(`source`/`role`/`asset`), scope_role, scope_asset_id, start, end（`asset` 作用域用资产局部秒）, label, tags[], deleted, version | 用户显式画的区段标签（原 `annotation.kind=tag`）；本地标签「提升为区段标签」也建在这里 |
| `oped` | id, source_id, kind(OP/ED), start, end, origin(`subtitle_rule`/`manual`), evidence, edited, deleted | 规则无错时随字幕导入登记；有错时在导入页逐对确认。人工标记 / 确认、改过边界的受保护 |

说话人是段的属性，经段参与标签继承：只对带人声角色的资产生效（一人 `character:`、多人 `participants:` + `speaker-status:多人未分段`，来源记为“区段”）。
旧的 `annotation`、`annotation_revision`、`subtitle_version`、`subtitle_line` 与 `sample.align_text_manual`、`source.current_subtitle_version_id` 在 0012 迁成上面几张表后由 0013 删除；
0012 在编辑历史里插一道“屏障”，撤销不越过它。

### 4.4 采样

| 表 | 关键字段 | 说明 |
|---|---|---|
| `sample` | id, asset_id, start, end（资产局部秒，创建后不变）, src_start, src_end（原素材秒，建采样时由触发器按映射算好、不变；迁移 0015）, name, nature(`speech`/`pitched`/`unpitched`/`unclassified`), starred, rating, note, language, created_via(`manual`/`segment`/`hint`/`hit`/`processed`/`import`/`reimport`), origin（来源：段 / 提示 / 命中 / 任务等）, text_snapshot（建立时的文本，用于命名与显示，之后不追改）, tag_judge_start/end（**判定区间**，原片秒）, independent(bool), visual_binding_id, version | **采样之间没有父子关系**（所有者 2026-10-12，0015 删掉 parent_sample_id / parent_label）：同一原素材上原素材时间正长度交叠的采样是“相关采样”（`samples.related`，跨所有音轨）；声音怎么做出来的看资产的加工链。排序“按原素材”、原素材页“采样”车道、「返回原素材」都用 src_start / src_end。采样不拥有分析，只读取。判定区间可见、可编辑，必须在采样范围内（编辑通道的 `judge` 字段用资产局部秒），同时决定标签继承与读哪些段；从段或提示建的 = 段或提示的区间，其余 = 选区（插入时没给就由触发器按映射补成选区）。所有建采样入口是一个动作（`core/sample_plan.py`：`samples.plan` / `samples.createPlanned`，来源 = 选区 / 段 / 提示 / 分离声部 / 整段原片，单条与批量产物相同）。显式保存一律新建；删除是硬删除（带确认），固定结果里的成员保留位置并标“已删除” |
| `sample_tag` | sample_id, tag | 本地标签（≤512 个/采样） |
| `sample_effective_tag` | sample_id, tag, facet, provenance(`local`/`source`/`segment`/`auto`), provenance_ref | **派生索引**，不是冻结：由 Core 在同一个写事务里按规则增量维护（段的说话人与边界、区段标签、判定区间、角色、原片属性、本地标签、绑定变化都会触发）；语义仍是“实时求值”，测试要求它恒等于完整重算（R8.8） |

### 4.5 测量（不是缓存）

| 表 / 文件 | 关键字段 | 说明 |
|---|---|---|
| `measure_run` | id, kind(`alignment`/`f0`/`acoustic`), owner_type(`asset_text`/`asset`), owner_id, asset_id, range（目标）, span_start/span_end（首个到末个非停顿音素，迁移 0011）, inputs（语言、文本与来源、句名、辞典版本、前端版本、模型身份与指纹、目标区间、窗口、容差、音频身份、设备）, status(`ok`/`failed`/`cancelled`/`stale`), manual(bool), result（对齐结果；F0 指向文件）, created_at | 不可变版本 |
| `measure_head` | owner_type, owner_id, kind, run_id, version | 当前采用的版本（version 供人工修正与切换版本的乐观并发）；采纳规则见规格 08 §8.4。**音素属于原素材时间线**（所有者 2026-10-12【基线变更】，`core/units.py`；取代 2026-10-09 的“段 + 具体那条资产”）：一句台词只有一份当前音素，owner_type = `asset_text`，owner_id = `seg:<段>@<原素材>`；回导成品和从它再加工出来的资产读 `seg:<段>@<回导成品>` 那一份（`reimport_id`）。在哪条轨上测的只记在 `measure_run.asset_id`（界面写“在某某轨上测得”）。**时间存原素材秒**（采纳时把测量资产的局部秒换算过来）；任何资产读取时按自己的映射换成局部秒，越出这条资产覆盖范围的音素去掉、被裁掉一部分的非停顿音素标 `clipped`。**只在盖住整句的含人声资产上测**（对齐要整句；容差 20 ms），所以没有半句分析；原素材页 = 正在看的那条轨，采样入口 = 默认人声轨，没有就是采样所在的轨（盖不住整句时沿加工链往上第一条盖得住的人声轨），再没有用原混音；明确选的轨不含人声或盖不住整句 → 写原因不分析。**含人声** = 开着 `vocal` 角色，或者一个角色都没开、又不是从分离声部来的（`from_separation = 0`：原混音以及从它截取 / 拉平 / 回导的）；不含人声的资产不读音素（列表状态 `novoice`）。目标 = 段区间映射到测量资产，窗口 = 目标 ± 对齐容差（默认 0.2 秒；2026-10-30 前是 0.65 秒），只送这段的文本。`measure_run` 另记 seg_start / seg_end / seg_text（分析时段的内容）：**可用** = 成功、内容与段现在一致（不再核对读取方的文件指纹，R11.10 对音素作废）；当前头内容不一致时退回到内容一致的最新成功版本（人工优先），所以撤销一次段修改不用重跑就恢复。改段的文本或边界后旧音素立即停用；设置「改段后自动在后台重跑」（默认关，在当前版本测量用的轨上重跑）。人工版本保护只在头的内容与段一致时生效；人工修时间可以从任何读这句的轨上改（只改这条轨盖得住的音素，被边界裁过、没改的端点保持原值）。不属于任何采样：删采样，音素和人工修正都在。**采样读取规则只有一条**：读与判定区间正长度交叠的所有段的音素（采样所在资产不含人声时不读）；任何一段不可用 → 节奏不可用并写明哪段（`rhythm-segments-missing` / `rhythm-segment-stale`）；两段的非停顿音素在采样范围内交叠 → 不可用（`rhythm-units-conflict`，“第 X 段与第 Y 段在 a–b 秒重叠”，X、Y 是读取时按存活段排出的序号）。合成时去掉各段首尾停顿、段间补停顿、mora/词序号依次平移，音素裁到采样范围，被裁掉一部分的非停顿音素标 `clipped`（音素上的 ◐）。列表与详情区标题的 ◐（状态 `partial`）= 采样的原素材起止没有盖住读到的某一段 |
| `Data/Measurements/f0/<asset_id>/<身份>/` | 每 60 秒一段 `<段号>.npy`（6000×3：F0、置信度、能量，float32 逐帧无损，两侧各 1 秒上下文推理）+ `manifest.json` | 按资产共享；身份 = 文件快照 + 音频流 + 存储窗口 + 映射 + 模型与算法版本（`models/f0store.py`）；只测用到且没测过的段；测量记录 kind=f0、归属 asset（阶段 4.5b） |
| （音高检索索引） | 阶段 7：完整检索直接读 F0 测量（上一行），不另建 50 ms 摘要；“已索引” = 范围所在的 F0 段都已测 | F0 就是音高检索索引，**不当缓存删**（规格 10 §10.2.5） |

拉平成品的 `pitch:` 标签来自资产 `production.target`（登记时记录的目标音），不来自重测（规格 11 §11.4）。
拉平（阶段 5，`core/flatten.py` + 任务进程 `jobs/flatten.py`，算法 `algo/flatten.py`、声码器前端 `models/hifigan.py`）：拉平台打开时冻结“资产 + 外选区 + 文件快照指纹”，提交时核对；
任务对冻结的输入重新测 F0、定音、重合成、掩码拼接、编码 MP3 V0，再对成品测 F0；登记一个 origin=flatten 的资产（`production` 记目标音〔名称、MIDI、Hz、原始 MIDI、偏移〕、范围与实际处理区间、定音方式与参考区间、内区与过渡、所用对齐、算法与模型版本、输入指纹）
+ 成品的 F0 测量（kind=f0）+ 一个调谐单音采样；输入指纹相同的成品音频复用、采样新建。

### 4.6 派生数据（可重建）

| 表 | 内容 | 失效条件 |
|---|---|---|
| （节奏视图） | 不落库：详情区的节奏视图在 Core 内存里按身份缓存（`core/rhythm.py`），检索用的逐块属性在 `speech_index` | — |
| `speech_index`（迁移 0008，阶段 7 实现） | 每采样一行：失效键 + msgpack（逐块属性按列：起音、结束、前导辅音开始、首元音、前导辅音、MIDI 中位数、波动、覆盖率、走势、相对音高、相对响度、强度、持续终点、角色（产生该块的那一段的说话人）、停顿段号、语段号；整句与各语段的占格、停顿、切口、窗口）。由「准备检索索引」任务构建（`jobs/search.py`，只读、进程池并行），采纳时核对失效键 | 失效键全部来自数据库（`core/search_index.py::speech_keys`：采样范围、判定区间与节奏参数、读到的段〔区间、文本、说话人〕与各段用的分析版本〔`units.reads_sql`〕、区段标签、F0 测量头、存储签名与文件快照、惩罚度、算法版本）；改名、星标、普通标签不失效（R14.14）；采样删除级联 |
| `scheme_cache` | 没有落库：检索进程内存里按（采样 + 失效键, 范围, BPM）缓存（3 万条冷启动 S3 2.8 s，不需要） | — |
| `acoustic_metric`（迁移 0009） | 每采样一行单音指标（JSON）；有效 = 资产、范围、存储签名、算法版本都等于现在的（SQL 里核对，筛选直接分页） | 内容变了失效 |
| `Data/Cache/` 文件 | 波形峰值金字塔、缩略图、帧索引、卡拍试听渲染、Studio 模型列表（临时解码 PCM 走管道、不落盘） | 可清理 |

### 4.7 检索结果与筛选

| 表 | 关键字段 | 说明 |
|---|---|---|
| `result_set` | id, kind(`speech`/`pitch`), created_at, title, query, scope_snapshot（范围栏标签条件 + 查找栏文字/表达式/临时条件 + 当时的筛选器内容）, params（含 BPM）, stats（后端耗时、缺少有效分析计数、是否截断）, ui_state（激活、页码、选中、滚动）, closed | 固定结果；重启后恢复不重搜（规格 04 §4.2.10） |
| `result_member` | result_id, rank, sample_id 或 (asset_id, 原片模式), binding_snapshot（asset_id/start/end/分析版本/索引版本）, hits（每处命中：区间、证据、方案、分数） | 读取时只核对失效（已删除/绑定变化/索引变化），不重算不重排 |
| `segment_search`（迁移 0014，阶段 8） | segment_id, text, dict_version, norm, reading | 文字搜索：段的规范化原文与平假名读音（pyopenjtalk-plus + 用户辞典，不经 tsqyomi）；可重建，检索前补齐过期行、资料变化后在后台补 |
| `saved_filter` | id, name, conditions（**只有标签条件**：分面〔作品、类型、人物、音高、其他标签〕+ 可选的标签表达式；所有者 2026-10-06：文字不能进筛选器，筛选器只放标签）, sort_order, version | 范围栏上的命名预设【基线变更：规格 07 §7.3 原含文字、性质、原片、星标、属性条件】 |

### 4.8 编辑记录、任务、导出、其他

| 表 | 关键字段 | 说明 |
|---|---|---|
| `edit` | id, created_at, label_code + args（可本地化的“这次修改”描述）, changes[(entity, id, field, before, after, version_before, version_after)], undo_of, undone_by | 统一编辑通道（§5）；没有重做 |
| `job` | id, kind, channel(`model`/`light`), status(`queued`/`running`/`succeeded`/`failed`/`cancelled`/`interrupted`), params（提交时冻结的业务输入）, device（冻结）, progress（阶段、done/total、消息码）, error（码 + 参数 + 日志路径）, affects（原片/采样 ID）, result, retry_of, items_total/ok/failed, background, promote_seq（§11） | 先持久化再执行（R19.1）；批量任务的逐条结果在 `job_item` |
| `job_item` | job_id, idx, target, status, error, result_ref | 批量语音分析/批量拉平的结果表，可只重跑失败项 |
| `export_file` | stable_key, path, kind(wav/video/reaper_wav/manifest), size, mtime, sha256, created_at | 按稳定键复用；被外部改过就报错不覆盖；从不自动删除 |
| `visual_binding` | id, owner_type(source/sample), mode(`sync`/`image`/`loop`/`materialized_clip`), media_file_id, clip_offset, version | 采样 > 原片 > 原片自带视频流 |
| `user_dictionary` | version, source_text, compiled_path, created_at | 全局一份；编译成功才原子启用 |
| `setting` | key, value, version | 走编辑通道（可撤销）；只作用于之后的操作 |
| `ui_state` | window, page, key, value | 重启恢复（勾选集合不恢复） |
| `model_probe` | model, file_sha, device_setting, status, ep_node_counts, error, tested_at | “文件就位 / 运行库可加载 / 实测通过”分开记（规格 14 §14.7） |

### 4.9 采样独立化（刚需，数据模型从阶段 1 起支持）

按所有者选定的形态 (b)（规格 04 §4.8、18 D32/D48）：

0. **语音分析**（所有者 2026-10-12：音素属于原素材时间线，采样只读取）：音素和文本层一起留下；测它们用的资产即使没有独立化的采样也只留一条记录（去掉原存储、界面不列出），独立化采样继续读得到（`sources._release`）。
1. **声音**：对每个要独立化的采样，把它绑定资产的 `[start, end)`（两端各留 1 帧余量）解码为**无损 WAV 切片**（源是无损时用与源相同位深的整数 PCM；源是 MP3 正式音轨时用 32-bit float，与解码结果逐样本相同）写入
   `Library/Independent/<source-key>/`，作为该资产的 `asset_storage(kind=materialized_slice)`。采样的绑定（资产 + 区间）**不变**，
   所以测量（按资产共享）、固定结果、来源记录都继续有效——测的就是同一段声音（PCM 相同，切片无损正是为此）。
2. **画面**：按该采样的画面绑定生成视频片段（同步视频取原片对应区间），存入同一目录，作为采样的 `visual_binding(mode=materialized_clip)`。
3. **原片元数据**：删除原片时，若仍有已独立化的采样，原片记录保留为 `media_state=released`：作品、集数、来源类型、文本层的段、音效提示、区段标签、OP/ED、
   资产角色等都在，标签继承与来源追溯照常工作；原片文件引用置空，未被切片覆盖的资产区间不可播放（明确报错）。
4. 删除原片时**不删**已独立化的采样及其切片/片段；其他采样、库内整轨、测量按规格 04 §4.5 级联删除（只删库内生成文件，不删磁盘原片与导出）。
5. 界面区分“已独立化”（采样徽标）与“媒体已释放”（原片徽标）；独立化采样不能再“返回原片”看前后文，界面说明原因。

> 物化切片用无损 WAV（所有者 2026-10-05：不用 FLAC，很多软件不支持），而不是 MP3 V0，是为了让“测量随资产保留”严格成立。

**实现（阶段 9，`core/independence.py`）**：切片的媒体快照里记着 `from`（原存储的媒体 ID、快照、音频流、窗口）；`assets.measured_as` 让分析的文件快照核对与 F0 身份按原存储认，
所以独立化之前的语音分析、F0 在切片上照常可读（L32）。`assets.locate` 找不到覆盖区间的存储、而原片已释放 → `media-released`；波形只画切片覆盖的那段。
独立化是轻量任务「采样独立化」；删除原片时可以接着删除（`SourceService.delete(release=True)`：留下独立化采样、它们的资产〔只留切片〕、文本层、标签、OP/ED、测量，其余删除）。

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
- 命令行与脚本（`otto call`、`otto run`，§15）只能调用同一组公开命令，写入同样走编辑通道，并记来源，可按会话撤回。

---

## 6. 用户可见存储布局（目录名一律英文）

```
<Workspace>/                         工作区：用户数据。源码运行 = 仓库内 dev-workspace/；发布版默认 ~/Documents/OttoSmasher Workspace/；OTTO_WORKSPACE 可改
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
├── Models/                          可选：用户放置或下载的模型权重（pydomino/ tsqyomi/ features/ flatten/）；有同名文件时优先于随包的模型
├── Agent/playbook.md                 可选：所有者给 agent 的约定（§15.5）
└── Data/                            应用数据（不给用户直接改）
    ├── library.sqlite3              数据库（WAL）
    ├── Measurements/                F0 帧、音高索引（永不当缓存删）
    ├── Cache/                       峰值、缩略图、帧索引、试听渲染（可清理；15 分钟内生成的跳过）
    ├── Jobs/<job-id>/               任务输入、输出、日志（成功后清理私有中间文件；失败保留证据）
    ├── Manifests/                   导出清单（规格 12 §12.1：放数据目录，不放导出目录）
    ├── Dictionary/                  用户辞典源与编译产物
    ├── Logs/                        核心日志、界面事件日志（滚动，有上限）
    ├── Backups/                     结构迁移前的一致性备份
    └── Staging/                     原子发布用的临时文件（与 Library 同卷）
```

- 原片目录名按 `<作品 集数> [<原片 ID 前 8 位>]` 在第一次生成文件时取（`core/libdirs.py`），之后按末尾的 `[id8]` 找回、不随改名移动（L23，阶段 9 统一了分离 / 拉平 / 回导 / 独立化）。
- **长期固定的目录名一律英文**（`Library/`、`Tracks/`、`Separation/`、`Flatten/`、`Reimport/`、`Independent/`、`Exports/`、`REAPER/`、`Models/`、`Data/` 及其下各目录）；按原片、按日期生成的子目录不受限制，可以用中日文（所有者 2026-10-06）。子目录与文件名都经过可移植处理（规格 12 §12.1）。界面里每个原片/采样都有“打开所在目录”。
- Core 生成导出文件名时用 NFC 合成可合成的假名和浊点（`domain/filename.py`），登记外部素材时保留原路径。REAPER 可在导出目录的 `peaks/` 里自行生成 `.reapeaks` 波形缓存，缓存名可能使用分解写法，即使对应 WAV 的文件名是 NFC。
- **原子发布**：先写 `Data/Staging/`，校验后 `os.replace` 到目标；导出到其他卷（自定义导出目录）时先复制为同目录下的隐藏临时名再改名，
  未完成的发布记录在数据库里，启动时清理残留——用户可见目录里不会长期留下 `.part`/`.lock`（规格 12 §12.6）。
- **清理保护**：临时解码 PCM 走管道不落盘，没有需要保护的租约文件；清理器跳过 15 分钟内生成的文件、不跟随符号链接，有任务在跑时拒绝清理。
- **清理口径**：引用关系来自数据库外键（`media_file` 被谁引用），不是在来源记录里搜路径字符串（规格 17 §17.3 #20）。
- 空闲判定用 UI 上报的“最后一次用户输入时间”，界面轮询不刷新空闲计时；策略与规格 13 §13.3.3 一致（空闲 5 分钟、每小时至多一次、1 天、512/384 MiB）。

---

## 7. 界面国际化（只翻译文字）

所有者 2026-10-06：国际化只要翻译文字，不需要按语言格式化日期、数字这些。【基线变更：规格 15 §15.7“数字、时间、文件大小按界面语言格式化”】

- **文案资源**：`app/renderer/i18n/locales/<lang>.json`（简体中文、英语），按键查找；代码里只出现键：`t("library.count", {n})`。语言：环境变量 `OTTO_LOCALE`（测试）> 工作区设置 `general.ui_language`（auto = 跟随系统，变了重新载入窗口）；主进程把上次用的语言存在界面数据目录，启动时不闪一下。英文的单复数在格式化后统一改（`englishPlurals`）；Windows 的键名与文件管理器名同样替换（`windowsKeys`）。
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

`core/ottosmasher/lang/__init__.py`：

```python
@dataclass(frozen=True)
class LanguageProfile:
    code: str                                    # "ja"
    normalize: Callable[[str], str]              # 逐码位替换，保持字符位置（日语：规格 08 §8.2.2）
    analyze: Callable[..., Any]                  # 文本 → 音素、音素↔文字↔读音、版本（日语：pyopenjtalk-plus + tsqyomi + 用户辞典）
    split_syllables: Callable[[str], list[str]]  # mora/音节切分（日语：小写假名并入、ー 单独成拍）
    core_phonemes: frozenset[str]                # 音块核心（日语：a i u e o A I U E O N；cl 另计）
    aligner: str                                 # 对齐模型（日语：pydomino；模型身份/版本写入测量）
```

读音搜索的规范化、辞典格式、默认字幕规则目前仍在日语模块和 `domain/` 里直接实现；加第二种语言时再挪进这个接口。

- 语言是**数据属性**：音频流、文本层的段、采样、测量输入都记录语言；默认取来源的语言标记或“首选语言”（默认 `ja`）。
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
- **自动准备**（所有者 2026-10-08，`core/search_auto.py`）：资料变化后合并 1.5 秒，补语音检索索引（有分析的采样）与 F0（新采样的范围、每个原片的默认人声轨或原混音整轨）；都是后台任务（`job.background`，同一通道里排在用户任务后面），按采样 / F0 段记账不重复提交；启动时补齐一次；设置 `analysis.auto_prepare` 可关。建索引时同一资产上相邻的一批采样一次解码再切片（`RhythmService.preload`）。

### 9.2 语音检索（`algo/speech_search.py`）

- 列数据一次拼成数组：逐块条件、邻接（同一采样、同一停顿段、最大间隔）、首尾全部向量化；只对通过的窗口算节奏证据（整句与语段 × 近快/近慢，方案在进程内存缓存）。
- 同一次求解里记住建好的方案、检索不建倍快（`stretch.candidates(..., which)`，结果不变）。

### 9.3 音高检索（`algo/pitch_search.py`）

- 所有者 2026-10-08：**完整检索**——每个允许的 10 ms 起点都严格判定（不再 50 ms 粗筛 + 2000 候选），相邻合格起点成组取最好；忽略八度、时长弹性、滑音块。
- 实现：同一资产上候选区间合并读 F0（`Data/Measurements/f0`，不另建摘要索引），全部声音拼成一条数组；带内可靠帧、距离、能量、缺口用前缀和 O(1) 判每个起点；
  便宜的必要条件（缺口、每块可靠帧数）先筛；忽略八度先用“折叠到一个八度”的下界预筛再逐个八度精判；滑音块逐帧累计；稳定度只对剩下的起点算分位数。
- 原片音轨模式：整轨测完 F0 的音轨才检索；句首/句尾用文本层的段（按映射换成资产秒）。

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
- **舞台画面**（阶段 9，`app/preload/picture.ts`）：第三个 libmpv 实例（只有画面、静音），画到舞台的 `canvas[data-otto-stage-video]`；页面只给采样 ID，preload 向 Core 要有效画面（`visuals.forSample`）。
  只在舞台这个采样的原声试听时跟着走：试听时钟 → 资产秒 → 原片秒（映射）→ 画面时间（同步 = 原片秒 + 偏移；循环 = 本地秒 mod 时长）；偏差 > 0.08 秒才重定位，暂停时暂停（规格 12 §12.4）。
- 范围播放：mpv 的 `ab-loop-a/b`（循环）与 `end`（单次）让**引擎**截停；任何普通跳转或播放/暂停先清除范围（规格 05 §5.3.1）。
- 同一原片切音轨：容器内音轨用 `aid`；外挂声部用 `audio-add select` / `audio-remove` 更换，保留视频、播放位置、暂停状态和范围播放。时间线以原片 ID 决定视口重置，切轨只重取波形和对应图层。
- 外挂声部：首次加载用 `audio-files` + `aid` + `audio-delay`（= 原片范围起点 − 资产选区起点），加载期间原音轨静音；不转码不代理（R22.1）。
- 字幕：mpv 自带字幕关闭（`sid=no`）；文本层的段（段文本，与台本、字幕层一致）用 HTML 叠加在画面 `<canvas>` 上（纯文本、白字黑边、按画面高度缩放；右键 = 这段的菜单）。
- 时钟：状态（播放/暂停/结束/代次）约每 50 ms 推送；**播放头每帧取 `player.position()`**：preload 里保存引擎逐帧推来的最新 time-pos（不节流）加流逝时间，正常播放中不小幅后退（实测 YY2-07-A 4 秒：每帧偏差 P95 7.2 ms、最大 15.7 ms、后退 0 次；旧的 50 ms 外推为 10.9 / 34.5 ms、后退 45 次）。不在每帧同步读 mpv 属性——会等 mpv 内部锁，打开/跳转时卡住页面（实测）。换源时用代次号丢弃旧事件。
- **波形组件与 mpv 的关系**：波形只做显示与交互（峰值与细节窗样本由 Core 按视口给出，不在浏览器解码音频）；播放全部交给 mpv。
  选区只能拖两端、不能整体拖；刻度、总览条、播放头、音素/字幕/区段车道、F0 金线、命中框都是同一组件的图层。
  Shift 吸附、⌥ 拖出（越过 4 px 才生成）等规格要求的手势直接在组件里实现。
- **libmpv 来源**（DECISIONS §14）：两端是同一个 mpv 提交（8ca245f2）。macOS arm64 由 `tools/build_libmpv_macos.sh` 在云端从官方源码编译（FFmpeg n9.0.2，含 VideoToolbox，只开 LGPL，静态并进一个 `libmpv.2.dylib`，见 `.github/workflows/build-libmpv.yml`）；Windows x64 用 zhongfly/mpv-winbuild 的 LGPL 包（未实测）。压缩包都存在本仓库的预发布版本 `third-party-1`，SHA-256 固定在 `tools/third_party.json`；头文件取同一提交。原生播放不可用 → 明确报错，不换其他播放方式（P6）。
- **实现要点**（开发初期的探针确认）：软件渲染在桥内独立线程里进行；`mpv_render_context_render` 默认按帧的显示时间阻塞，正好用来给画面定时，界面线程每个动画帧只取最新一帧（拷贝 + 纹理上传）。默认选项 `hwdec=auto-copy`（macOS 上实测选到 videotoolbox-copy）、`sws-fast=yes`。

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
  实现（阶段 9，`media/video.py`、`core/video_export.py`）：Core 算好每个输出帧要的画面时间，任务进程按区间解码源视频（`-copyts` + `-to`，`showinfo` 报每帧真实时间）流式选最近帧、写进编码器；
  帧数 ⌈时长 × 帧率⌉、按音频时长截断、帧率写成分数；可选 ProRes 422 HQ。

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
- 同一通道里的顺序：用户“提前”的任务（`promote_seq`，越晚提前越靠前）→ 用户提交的 → 后台任务（`background`，如自动准备）；同类按提交时间。
- 提交时冻结业务输入与设备设置；重试 = 相同业务参数的新任务 + **当前**设备设置。
- 进度结构化：`{stage, done, total, percent, message_code, args}`；Studio 的 `task_progress`/`task_stage` 映射到同一结构（规格 14 §14.6.2）。
- 任务摘要很轻（不含大结果），声明影响的原片/采样；UI 只在状态或进度变化时更新。
- 任务进程启动时加载需要的 ONNX 会话（统一会话工厂：CPU 默认；开启加速时 [CoreML/DirectML, CPU]，请求的 EP 没进入会话就报错；
  首次推理后用 profiling 统计各 EP 节点数，写 `model_probe`）。
- 有逐条工作但一条都没做成的任务记为失败（`job-all-items-failed`），不显示成“完成”；部分失败记成完成 + 提醒（P6）。
- 日志：每任务一个日志文件 + 外部工具的命令/版本/设备/输入输出路径；保留上限（按数量与天数滚动）。

### 11.1 PyMSS Studio 适配（规格 14 §14.6）

- 发现安装与活动推理环境、列模型（`downloaded` 且 `supported`）、按名称/别名匹配、声部按 `/ | ,` 拆分且保留原样大小写。
- 每次调用独立子进程：`<Studio python> <resources>/python/worker.py <cmd> --payload <json>`；环境变量按契约设置，删除 `PYTHONPATH`/`PYTHONHOME`；
  stdin 关闭、stdout 按 UTF-8 逐行解析事件、stderr 写日志；退出码非 0 **或任何 `error` 事件** → 失败；`download` 强制 false。
- 推理前后各算一次模型指纹，不一致拒绝；输出只信任 `task_done.outputs`，核对路径、样本数（差 ≤ 1）、声部齐全；任何不完整都不登记。
- 测试用“伪 Studio worker”脚本（逐行输出事件）覆盖成功、部分失败退 0、缺输出、时长不符、超时、取消。

---

## 12. 测试

怎么跑见 [DEVELOPMENT.md](DEVELOPMENT.md)「测试」。

| 层 | 在哪 | 内容 |
|---|---|---|
| Core 单元 | `core/tests/unit/` | `domain/`、`algo/` 的纯函数，直接用规格 16 第二部分的数值例子（R3 映射、R5 说话人、R6 OP/ED、R10 前端、R12–R15 算法、R17 拉平……）；合成信号（斜坡、混音、置零段、内联 SRT）；伪 Studio（`fake_studio`）；“一调用就失败”的重操作替身（证明检索不解码不推理）；命令目录与说明书核对；引擎边界 |
| Core 集成 | `core/tests/integration/` | 真实子进程、真实模型；设 `OTTO_FIXTURES` 时小批跑真实素材（不全库跑模型，输出只写临时工作区）。`OTTO_STRICT_API=1` 核对每个命令的返回值与目录一致 |
| 性能 | `core/tests/perf/` | 1 万条分页（R8.9）、3 万条合成库三大搜索（R14.15，`tools/synth_library.py`） |
| 界面组件 | `app/**/*.test.tsx`（Vitest + Testing Library） | 统一选择规则、范围栏、检索画布、快捷键焦点 |
| 端到端 | `e2e/*.spec.ts`（Playwright 驱动 Electron） | 各页面流程；`pseudo` 伪语言；`real-*` 用真实素材（要 `OTTO_FIXTURES`）；`probe` mpv 性能探针；`packaged` 发布包冒烟（`OTTO_PACKAGED_E2E=1`） |
| 文案与目录 | `tools/npm run i18n:check`、`tools/uv run python -m ottosmasher.api.catalog --check` | 文案键齐全、Core 里没有界面语言的字面量；命令目录与 `generated.ts` 是最新的 |
| 人工 | — | 只验自动化证明不了的：原生播放的手感、拖到 REAPER、听感（拉平、分离） |

Windows 云端（合成素材）测试通过，还没有实机验证；真实素材、显卡、声音、REAPER 相关的一律标“未验证”。

---

## 13. 技术风险与验证情况

开发初期逐项验证过的技术点，和还没验证的。

| 风险 | 验证情况 | 不行时的备选 |
|---|---|---|
| mpv 渲染桥：软件渲染 + 画布在 1080p HEVC10、24 fps 下是否流畅，拖动/逐帧是否及时 | **已验证**（2026-10-06，M 系列 Mac，YY1-01，画布 1920×1080）：硬解 videotoolbox-copy；显示 24.1 fps、丢帧 0；渲染线程 13.2 ms/帧（默认缩放 20.2 ms）；界面线程 0.5 ms/帧（最大 2 ms）；跳转 14–61 ms；逐帧 11–103 ms；渲染进程约 36% 单核。复测：`OTTO_PROBE_FILE=<整集> npx playwright test e2e/probe.spec.ts` | GL 渲染到共享纹理（暂不需要）；再不行才考虑原生子视图（会带回遮挡问题，先问所有者） |
| 原生扩展在 Windows x64 上构建与加载 | 云端通过（2026-11-03）；实机未验证 | 改为独立 utility 进程 + 共享内存 |
| `startDrag` 在“越过阈值后才异步生成文件”的时序下能否发起系统拖拽 | 已验证（macOS，拖到 Finder、REAPER；`e2e/dragout.spec.ts`） | 先生成到暂存再在下一次移动事件发起；仍不满足规格时先问所有者 |
| mpv 对 LAME 无缝 MP3 的样本级对齐 | 合成斜坡 MP3 的偏移测试 | 正式音轨改存 FLAC（要所有者同意，涉及存储预算） |
| pydomino C++ 扩展在 Windows 上构建 | 云端通过（2026-11-03）；实机未验证 | 已改为自写最小 CPython 绑定（不依赖 pybind11/Eigen/上游 ORT），setuptools 调 MSVC 编译；Windows 未实测 |
| pyopenjtalk-plus 导入时加载旧读音模型 | 测试“导入不加载任何模型”（test_openjtalk） | 已做：导入前给 `yomi_model.nani_predict` 放空模块占位（`lang/ja/openjtalk.py`），tsqyomi 会话由工厂创建后交给库 |
| 检索 3 万条 30 秒 | 已验证（合成库基准，§9.5） | numba 热点编译 |
| wavesurfer 在 24 分钟整集 + 深度缩放下的流畅度 | **已定（2026-10-07）**：wavesurfer 只能一次喂整段峰值，放大到几十毫秒要几千万点、元素宽度超浏览器上限；调研 peaks.js、waveform-playlist 等也都只接受覆盖全程的固定分辨率数据，没有“按可见范围向后端取数”的接口（所有者提议后调研，见 history/QUESTIONS 第五节） | **已采用**：整集时间线、舞台、工作台都用同一个自研画布组件，按视口向 Core 取峰值（≤32000 点；≤30 秒细节窗精确解码到样本级）；不引入 wavesurfer（所有者 2026-10-07，第二轮调研无现成组件满足） |
| 发布版在别的 Mac 上第一次打开（ad-hoc 签名、没有公证，Gatekeeper 会拦） | 不做公证：README 安装步骤让用户第一次打开前运行 `xattr -dr com.apple.quarantine`（所有者 2026-10-31） | 要更顺就得 Developer ID 签名与公证（要所有者定） |

---

## 14. 分发（2026-10-30【基线变更】：本地构建 macOS、模型随包；DECISIONS §14）

Windows（2026-11-03，还没发布）：`tools/package_win.py` 由云端构建，免安装文件夹 + ZIP，不签名；布局见脚本开头。下面写的是 macOS。

- `tools/package_mac.py` 直接组装 `.app`（不用 electron-builder）：复制 Electron 的 `Electron.app`，改名（主程序与四个 Helper）、改 Info.plist（`io.github.axolyz.ottosmasher`、macOS 14+）、
  由 `assets/brand/logo.png` 生成图标；逐个 ad-hoc 签名所有 Mach-O，再签整个 .app；`ditto` 打 ZIP（< 2 GB）并写 SHA-256。
- `Contents/Resources/` 布局（`app/main/paths.ts` 与 `core/ottosmasher/resources.py` 按它找；源码运行时同样的相对路径在仓库里）：
  `app/`（`out/` 与界面文案、mpv 渲染桥 + `libmpv/`）、`python/`（与开发环境同一个 python-build-standalone 3.12 + 按 uv.lock 装的 Core 与依赖）、
  `third_party/`（模型支持文件、pydomino 扩展）、`models/`（四个模型权重；工作区 `Models/` 里有同名文件时优先用工作区的）、
  `bin/` + `lib/`（ffmpeg、ffprobe、rubberband 来自固定版本的压缩包（`tools/build_media_tools_macos.py` 在 macOS 14 上生成），依赖的动态库一起复制、改成 `@loader_path`；`otto` 启动器）、`licenses/`。
- 发布版运行时：主进程设 `OTTO_RESOURCES`、`OTTO_FFMPEG` / `OTTO_FFPROBE` / `OTTO_RUBBERBAND`，清掉 `PYTHONHOME` / `PYTHONPATH` / Conda 等变量；
  默认工作区 `~/Documents/OttoSmasher Workspace`（L3，`OTTO_WORKSPACE` 可改）；随包的模型文件直接算已核对（构建时按 SHA-256 核对、.app 有签名）。
- 程序目录只读；工作区与程序分离；不需要首次启动“释放运行库”。冒烟检查：`e2e/packaged.spec.ts`（清空环境变量、中文与空格路径、空工作区、随包模型就绪、登记、试听截停、otto 路径）。
- 许可：GPL-3.0-or-later（Rubber Band、带 libx264 的 ffmpeg 为 GPL）；模型各按自己的许可作为单独组件随包，PC-NSF-HiFiGAN 是 CC BY-NC-SA 4.0（非商业），
  见 [THIRD_PARTY.md](THIRD_PARTY.md) 与包内 `licenses/`。
- **PyMSS Studio 不随包**：设置 → PyMSS Studio 没找到时说明要另外安装，并给发布页（主进程 `links:open` 只开固定列表里的网址）。
- 构建时预编译 Python 字节码，运行时设 `PYTHONDONTWRITEBYTECODE`：.app 里不会生成 `__pycache__`（否则签名失效）。
- 版本号：每次构建自动加一位补丁号，`tools/release_notes.md` 模板生成这一版的 `RELEASE_NOTES.md`（流程见 DEVELOPMENT「发布」）。
- 开发版与发布版并存：源码运行的应用叫 OttoSmasher Dev（独立的应用身份与 userData，顶栏标“Dev”和工作区名），默认用仓库里的 `dev-workspace/`，不碰日常工作区；
  要用真实资料复现 bug 时 `tools/clone-workspace` 克隆一份（APFS 克隆 + SQLite 在线备份，删掉端点与锁文件）。
- 体积：Electron 约 290 MB、Python 与 Core 依赖约 590 MB、模型 187 MB、媒体工具与动态库约 40 MB；.app 约 1.2 GB。

---

## 15. 命令行与 agent 接入（2026-10-24 所有者【基线变更】；DECISIONS §12）

所有者 2026-10-24：让 LLM agent 把应用的能力与数据库、自己的推理和别的工具组合起来完成复杂任务（history/QUESTIONS「命令行与 agent 接入」）。
定：**只在应用开着时**可用；撤销不了的操作要所有者在应用里确认；只做命令行、不做 MCP；说明书中英双语。

### 15.1 通道

- Core 在 `serve`（即应用里真正运行）时开本机端点（`core/agent_link.py`，标准库 `multiprocessing.connection`）：macOS 套接字放系统临时目录
  `otto-<工作区哈希>.sock`（避开 104 字节路径上限），Windows 命名管道 `\\.\pipe\ottosmasher-<哈希>`；地址、pid、随机密钥写 `Data/agent-endpoint.json`（0600），关闭时删除。
  `--no-agent-link` 不开端点。一个工作区仍然只有一个 Core（工作区锁不变）；应用没开时命令行报 `app-not-running`，不另起无界面 Core。
- 消息与 stdio 相同（msgpack 的 req / res / evt），握手先发 `hello` 声明 `{kind: agent|script, session}`；**这个连接上的所有请求按握手的来源记**（`core/actor.py`），消息里的 `actor` 不理。
- 请求进 Core 主线程的同一个队列串行处理，响应回到该连接；**事件广播给 stdio 与所有连接**。外部连接的请求不带请求标记，界面把它们的改动当作“别处的改动”（P8，底部“资料已更新”）。
- 外部连接调用 ui / app / dev 类命令 → `agent-command-forbidden`；参数里有没声明的键 → `bad-request`（严格模式下界面也一样，原来会被静默丢掉）。

### 15.2 权限：撤销不了的命令

- 登记命令时标 `danger`（总是，或按参数）：`sources.delete`、`samples.delete`、`works.rename`、`storage.clean`、`samples.independ`（带删原素材时）。目录里写 `"danger": "always" | "conditional"`。
- 外部连接调用它们 → Core 发 `agent.confirm`（命令、参数、影响预览、会话、秒数）→ 外壳弹确认框 → `agent.confirmReply`（ui 类，只有应用能调）。
  同意才执行；拒绝 → `agent-confirm-declined`；缺省 120 秒没人回答 → `agent-confirm-timeout`（`OTTO_AGENT_CONFIRM_SECONDS` 可改，0 = 不限时）；提问的连接断了 → 作废；这两种都记进“错过的请求”（`agent.missed`，本次运行内，最多 50 条）。
  提问时记下资料指纹（影响预览 + 涉及对象的版本），放行时重算，不同就不执行、带新预览重新问（`{"reasked": true}`）。设置 `agent.skip_confirm`（默认关）打开后不问、直接执行；这一项在 `settings.HUMAN_ONLY` 里，只有用户来源能改或撤销（否则 `setting-human-only`）。等待期间不占主线程；`agent.confirmClosed` 让其他窗口撤下框。

### 15.3 来源与撤回

- 编辑、任务、新建的原素材 / 资产 / 采样 / 测量都记来源（agent / script + 会话，迁移 0004）。`edits.history` 按来源列编辑；`edits.undoSession` 从新到旧撤回一个会话的编辑，
  遇到之后又被改过的那条就停下报告（不跳过，免得撤出半套）。`edits.undoOne` 撤指定的一条（它改过的东西之后没被再改过才行；`edits.history` 的 `undoable`）。
  新建的采样、资产不走编辑通道，不在撤回范围内（删除要确认）。
- 任务摘要带 `actor`，任务抽屉给命令行提交的任务一个“agent”小标记；顶栏「操作历史」面板列出所有人的修改、错过的确认请求（history/UI_PLAN §11）。

### 15.4 命令目录与命令行

- `docs/api/commands.json`（目录版本 3：每条带 `layer`）：命令（作用类别、danger、参数与返回 Schema）、**事件**（`api/events.py`：名称 + 负载 Schema；测试扫描源码里的 `emit` 检查登记齐全）、错误码表。
- 命令行 `otto`（`core/ottosmasher/cli/`；开发期 `tools/otto` / `tools/otto.cmd`；发布包里是 `Contents/Resources/bin/otto`）：`status`、`commands`、`describe`、`errors`、`call`（`--wait` 跟到任务 / 检索 / 视频导出结束）、
  `wait`、`events`、`run`（用应用的 Python 跑 agent 自己的脚本，`LinkClient.from_env()` 取工作区与会话）、`guide`、`session`、`setup`（`playbook` / `skills` / `audio`）。stdout 只写 JSON；退出码 0 成功 / 1 业务错误 / 2 用法、连接、参数 / 3 所有者拒绝或超时。导出文件名的固定词取界面同一组文案。
- agent 通过 `otto`／`LinkClient` 经本地端点调用 Otto Core；外部音频工具通过 agent 宿主的 MCP 功能接入。Otto 提供音频导出及时间映射，宿主管理音频工具的连接和依赖。
- `LinkClient.from_env()` 优先用 OTTO_WORKSPACE，未设置时复用 CLI 的同种运行实例发现规则；工作区名称和路径由运行实例提供。
- 返回形状沿用命令目录：speech.align 直接返回 JobSummary，separation.submit 的摘要位于 job 字段，sources.prep 是七个各含 ok 的顶层项。CLI JSON 中的二进制为 base64，Python 客户端为 bytes。
- 轻量读取：`jobs.summaries` 分页返回无大结果的任务与同通道排队数，`jobs.get` 取完整单项；`samples.metrics` 只读带有效性状态的声学缓存；创建物按已有 actor_session 查询。拉平沿用原 open / estimate / submit / submitBatch，任务脚本可组合这些命令。
- 为外部调用挪进 Core 的业务（原来在界面里拼）：`tracks.setDefault`、`tracks.setRole`、`visuals.bind`。语音检索查询的默认值 Core 本来就有（`parse_query`），没有挪。

### 15.5 agent 的说明（三处，所有者 2026-11-04）

- **说明书** `core/ottosmasher/cli/guide/reference/`（`otto guide --lang en|zh-CN`，中英双语；中文在 `zh-CN/`）：只讲怎么正确操作应用——对象、命令、应用会怎样、硬规定。随版本走，测试核对提到的命令存在、示例参数合法。
- **skill** `guide/skills/{en,zh-CN}/<名字>/` 加 `guide/skills/common/<名字>/`（语言无关的文件，如 `scripts/speaker_embed.py`）：不确定的流程，格式是 Agent Skills。`cli/skills.py` 把它们同步到 `<工作区>/Agent/skills/`，清单是其中的 `.otto-skills.json`（语言、每个文件装入时和提示过的哈希）。更新规则见 DECISIONS §12。
  `otto status`、`otto guide`、设置 › 命令行与 agent（`agent.skills`）都会同步。`otto guide` 末尾列出每个 skill 的名字、用途和路径，agent 用到时才读全文。`otto setup skills` 同步并列出 skill 里提到、应用已没有的命令。`otto guide notes` 是旧名字的别名。
  带外部模型依赖的脚本由 agent 用自己的环境跑（PEP 723 内联依赖，`uv run`）；依赖应用包的机械助手用 `otto run` 的 Python 客户端连接 Core，不在 Core 或界面主进程中执行。字幕统计和核验方法由 agent 根据当前来源选择。测试核对两种语言逐节对应、符合规范、提到的命令存在，以及不需要模型的那部分脚本。
- **用户的约定** `<工作区>/Agent/playbook.md`（`otto guide playbook`；`otto setup playbook` 从 `guide/playbook/<lang>.md` 模板生成）：优先于 skill，改不了说明书的硬规定。
- 交付（所有者 2026-10-30）：仓库托管 `skills/ottosmasher/SKILL.md`——只是入口（怎么找到 otto、先看 `otto guide`），不抄说明书正文，所以不会过期；
  可选，想装时 agent 按自己工具的方式装到**项目级**（不装全局，避免污染别的项目的 skill 列表）。设置 › 命令行与 agent 显示 otto 的位置、手动重装 otto 和「复制给 agent 的开场白」（让 agent 先跑 `otto status`、`otto guide`，不用下载）。
  发布版启动时自动安装 otto（`app/main/otto-link.ts`；macOS 是 `~/.local/bin/otto` 链接，Windows 是 `WindowsApps/otto.cmd` 转发脚本），运行中的应用登记到 `Application Support/OttoSmasher/instances/<pid>.json`（`cli/instances.py` 读；`otto open` 打开应用）。
  `otto status` 的 `environment` 报 otto 的位置、模型、PyMSS Studio、有没有 playbook、skill 与待合并的新版本，并给出 `hints`；`otto setup audio` 只打印接 audio-mcp 的命令 / 配置。
- `otto session`：分页收齐本会话摘要任务，另列修改摘要及新建采样／资产数量与最近 ID，长任务之后接着干用；`--details` 才取完整任务。`wait` 默认静默，`--progress` 输出进度，最终结果保持完整格式。

### 15.6 两层命令与引擎边界（所有者 2026-10-30）

- 命令目录每条带 `layer`：`library` 业务命令（资料库里的对象、编辑、撤销、任务登记）；`primitive` 原始能力（只算、不改资料库，像 git 的 plumbing）。
  `otto commands --layer primitive` 列出。原始能力：`speech.align`（日语对齐）、`text.analyze`（读音）、`f0.track`（FCPE 音高）——任务，逐条结果写在任务目录，
  用 `speech.alignResults` / `text.analyzeResults` / `f0.trackResults` 读（命令行 `--wait` 自动读出）；`subtitles.parse`（按当前规则读字幕文件）、`subtitles.ruleTest`、`dictionary.check`、`spectrum.get`。
- 声音输入 `AudioRef`：库里的音轨（资产秒，结果另给原片秒）或任意文件（文件秒，`stream` 选音频流），不用先登记（`core/primitives.py`、`jobs/primitives.py`）。
- 判断“要不要开放成原始能力”：没有 agent 时应用自己需要它、已经在维护它；应用不需要的（ASR、OCR、抠图）交给外部工具（如 audio-mcp）。
- 引擎边界：`media`、`lang`、`models`、`domain`、`algo`、`jobs/speech.py`、`jobs/primitives.py` 不引用 `store` / `core`（`core.errors` 除外）/ `api` / `cli`（测试 `test_engine_boundary`），以后要拆成独立包基本只是挪目录。
- 对齐不能定位：窗口要紧贴说话（试验见 history/QUESTIONS 阶段 A 决定 15）；结果给 `edges`、`longestPhone` 这类事实，不给“可疑”判定（试过的判定把三到四成好结果也标成可疑）。

### 15.7 还没做的

- **编排层**（自动做音MAD 的时间线编排）：仍按原来的边界——agent 用检索、卡拍、导出，成片在 REAPER 里完成；不在应用里做多轨编辑器。
- **数据外发**：agent 若用云端大模型，它读到的台词会离开本机；应用没法控制 agent，由用户自己决定（所有者 2026-10-24：说明书里不写禁止外发的规定）。
- Windows 命名管道与 `otto.cmd` 未实测（ROADMAP L47）。
