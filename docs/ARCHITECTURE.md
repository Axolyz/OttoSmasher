# OttoSmasher 新版架构（阶段 0 草案）

> 状态：**草案，待所有者过目**（2026-10-05）。依据只有交接包 `OttoSmasher-Rewrite-Handoff/`（下文 “规格 xx §y” 指交接包 docs/xx）。
> 本文件属于“自由设计”层（规格 02 §2.6）：架构、进程模型、数据库、内部格式由开发者决定，但必须满足基线行为与规格 15 的非功能要求。
> 界面布局与交互另见 `docs/UI_PLAN.md`（半基线，须所有者确认）；疑问与矛盾见 `docs/QUESTIONS.md`。

---

## 0. 一页总览

| 层面 | 选择 | 一句话理由 |
|---|---|---|
| 语言 | **Python 3.12**（全栈一种语言） | 定型模型与文本前端本来就在 Python 生态（pyopenjtalk-plus、ONNX Runtime、numpy）；界面也用 Python 后，只剩一个运行时、一套打包、一套测试 |
| 桌面框架 | **Qt 6（PySide6 6.11，Widgets）** | 真正的原生桌面应用；视频可以在 Qt 的绘制体系内渲染（不再有“原生视图盖住弹窗”的问题）；原生拖出文件、剪贴板、高 DPI、键盘焦点体系成熟；pytest-qt 可做无头界面测试 |
| 视频/音频播放 | **libmpv**（render API → `QOpenGLWidget`），python-mpv 绑定 | 旧版已验证 libmpv 能稳播 HEVC Main10 + FLAC、引擎侧范围截停、外挂声部 + 音频延迟、VideoToolbox 硬解；改用 render API 后画面是 Qt 控件的一部分，弹窗、抽屉、下拉都能正常盖在上面 |
| 进程 | **界面进程 + 核心进程 + 检索进程池 + 任务进程**（见 §2） | 界面线程永不被计算/数据库阻塞；核心进程是唯一写库者；模型与检索在独立进程里跑、可整树取消 |
| 进程间通信 | 本机管道上的长度前缀 **msgpack** 帧（msgspec 编解码与校验） | 无端口、无 HTTP、无跨站风险；请求/响应 + 事件推送；类型化的命令即“公开业务接口”，脚本入口也用它 |
| 数据库 | **SQLite（WAL）**，核心进程单写多读 | 本地单用户；事务原子；检索 worker 只读并发打开 |
| 数值与特征 | numpy；F0 帧与音高索引用 `.npy` 文件（内存映射） | 逐帧无损、按声音内容共享；检索时零拷贝读取 |
| 模型推理 | ONNX Runtime（Windows 用 onnxruntime-directml），统一会话工厂 | 规格 14 §14.7 的设备策略与实测证据 |
| 媒体工具 | ffmpeg/ffprobe（解码、编码、视频导出）、Rubber Band CLI（R3） | 规格 14 建议项，旧版验证过 |
| 界面国际化 | **Project Fluent**（`.ftl`，按键查找）+ Babel 格式化；后端只返回“错误码 + 参数” | 支持参数、复数/选择、本地化数字与时间；伪语言测试可自动生成 |
| 打包 | PyInstaller onedir → macOS `.app` ZIP / Windows 便携 ZIP（阶段 10 细化） | 不用 conda-pack；PySide6 + PyInstaller 是成熟路线 |
| 测试 | pytest（单元 / 合成 / 集成 / pytest-qt 界面 / 性能） | 规格 16 第三部分的合成测试做法 |

不需要 Node：所选技术栈里没有 Web 前端。本机的 Node 不会被用到（界面原型是纯静态 HTML，直接用浏览器打开）。

---

## 1. 技术栈与理由

### 1.1 为什么是 PySide6 而不是 Electron + Web 前端

| 维度 | Electron + React + Python 服务（旧版路线） | **PySide6 + Python 核心（选定）** |
|---|---|---|
| 运行时 | Node/Chromium + Python 两套，打包两套 | 一套 Python |
| 视频 | libmpv 原生子视图叠在网页之上：要每 ~80 ms 同步几何、被弹窗遮挡时隐藏、Windows 不支持裁剪（规格 14 §14.9、17 §17.1 #14 一整类 bug） | libmpv render API 画进 `QOpenGLWidget`：就是普通控件，遮挡/裁剪/缩放/切页都由 Qt 处理 |
| 前后端边界 | HTTP 服务 + 端口 + Host/Origin 校验 + 版本错配（17 §17.1 #16） | 子进程管道，核心由界面启动、随界面退出，不存在“连到旧服务” |
| 拖出到 DAW | `webContents.startDrag` | `QDrag` + 文件 URL（两平台原生） |
| REAPER 剪贴板 | `clipboard.writeBuffer` | macOS 用 NSPasteboard（pyobjc）、Windows 用 `RegisterClipboardFormatW`（ctypes）直接写 `REAPERMedia` 类型 |
| 界面开发效率 | Web 组件生态更丰富 | 复杂自绘控件（波形、卷帘、音高画布）用 QPainter；范围栏条件块、命令面板等需要自写控件，工作量可控 |
| 界面自动化测试 | 需要 Playwright/Electron 驱动 | pytest-qt 在无头（offscreen）模式下驱动真实控件 |

**放弃的其他方案**：Tauri（要引入 Rust 第三种语言，且本机没有 Rust 工具链，装它需要全局安装）；Qt Multimedia 代替 libmpv
（做不到引擎侧样本级范围截停与外挂声部延迟，规格 05 §5.3.1）；自建 Python 音频引擎（PortAudio 回调受 GIL 影响，在界面进程里有爆音风险）。

### 1.2 主要依赖（阶段 1 起用 uv 锁定版本）

| 依赖 | 版本（初定） | 用途 | 备注 |
|---|---|---|---|
| Python | 3.12（uv 托管，装在项目内 `.uv-python/`） | 全部 | pyopenjtalk-plus、onnxruntime 都有 cp312 的 macOS arm64 / Windows x64 轮子（已查 PyPI） |
| PySide6 | 6.11.x | 界面 | LGPL |
| python-mpv | 1.0.x | libmpv 绑定（ctypes） | libmpv 动态库另行提供（§10.1） |
| msgspec | 0.22.x | IPC 编解码、命令参数校验、JSON | |
| numpy | 2.x | 数值 | |
| onnxruntime / onnxruntime-directml | 1.30.0 / 1.24.4 | 推理 | 规格 14 §14.1 建议版本 |
| pyopenjtalk-plus[tsqyomi] | ==0.4.1.post9 | 日语文本前端（定型） | 需处理“导入时加载旧读音模型”的坑（规格 14 §14.2） |
| pydomino | 上游 @ `4930396…` 源码构建的 C++ 扩展 | Viterbi 解码（定型） | 只用 C++ 解码部分；ONNX 由我们的会话工厂加载 |
| regex | 最新 | 字幕规则（递归括号、超时） | 规格 06 §6.2.2 |
| fluent.runtime + babel | 最新 | 国际化 | |
| soundfile / 直接调 ffmpeg | — | 读写 WAV/FLAC | 解码统一走 ffmpeg 管道（§10.3） |
| pyobjc-framework-Cocoa（仅 macOS） | 最新 | REAPER 剪贴板、拖放细节 | |
| pytest、pytest-qt、hypothesis | 最新 | 测试 | |

外部可执行文件：ffmpeg/ffprobe（开发期用 Homebrew 9.0.2，发布时随包）、rubberband 4.0.0（同上）、libmpv（§10.1）。

---

## 2. 进程模型

```
┌──────────────────────────── UI 进程（PySide6，Qt 事件循环）──────────────────────────────┐
│ 窗口与三页（常驻）· 视图模型 · libmpv 播放器（原片视频 1 个 / 试听 1 个，per 窗口）           │
│ PlaybackCoordinator（全应用同一时刻只有一个声音）· 拖出控制器 · 剪贴板                       │
│ CoreClient：后台读线程把核心的响应/事件转成 Qt 信号；每个视图请求带“代次”，过期响应丢弃      │
└───────────────▲──────────────────────────────────────────────────────────────────────────┘
                │ 管道（msgpack 帧：request / response / event）
┌───────────────┴──────────────────── Core 进程（唯一写库者）─────────────────────────────────┐
│ RPC 分发（命令 = 公开业务接口，带类型与文档）                                                  │
│ 领域服务：原片/资产/采样/标注/标签/OP-ED/字幕/导出/画面/设置/固定结果/保存筛选器              │
│ 统一编辑通道（预览→原子应用→撤销）· 有效标签索引维护 · 失效通知                               │
│ 任务调度器（模型通道 1、轻量通道 2；持久化队列；进程树取消；重试；中断恢复）                   │
│ 检索协调器（快照范围 → 分片 → 进程池 → 合并排序 → 写固定结果）                                │
│ 缓存服务（波形峰值/缩略图/频谱，低优先级线程池）· 清理器（空闲判定、租约、水位）              │
└──────┬───────────────────────────┬──────────────────────────────┬──────────────────────────┘
       │ spawn（独立进程组/作业对象）  │ 常驻进程池（只读打开 SQLite、内存映射索引）  │ 子进程
┌──────▼───────────┐       ┌───────▼──────────────────┐        ┌───────▼──────────────────┐
│ 任务进程（每任务一个） │       │ 检索进程池（N = 物理核数 − 2） │        │ 外部工具                     │
│ 语音分析 / 音高测量 /  │       │ 语音检索、音高检索、         │        │ PyMSS Studio worker.py     │
│ 拉平 / 分离 / 指标 /   │       │ 单音指标筛选                 │        │ ffmpeg / ffprobe / rubberband│
│ 视频导出 / 派生重建     │       └──────────────────────────┘        └──────────────────────────┘
│ 只产出结果文件+结果描述，│
│ 不写库；核心负责登记     │
└──────────────────┘
```

### 2.1 各部分在哪里跑

| 工作 | 进程 | 说明 |
|---|---|---|
| 界面、播放、拖出手势、剪贴板 | UI | libmpv 的解码与音频输出是原生线程，不受 GIL 影响；UI 进程里不做任何 O(采样数) 的计算 |
| 浏览列表、标签、编辑、设置、字幕导入预览 | Core | 毫秒级；Core 内部用线程池处理并发请求，写操作串行化到一个写连接 |
| 字幕标记导入、字幕采样创建、删除原片（含独立化物化） | Core（大批量时作为轻量任务） | 原子事务 |
| 语音分析（前端 + pydomino + 派生 + 必要时 FCPE）、音高测量与索引、拉平、分离 | 任务进程（模型通道） | 一个**批量任务 = 一个进程**处理全部条目（避免旧版“逐句起进程”，规格 17 §17.1 #17），逐条产出结果 |
| 单音指标、派生重建（如改惩罚度）、视频片段导出 | 任务进程（轻量通道） | |
| 三大搜索 + 单音指标筛选 | 检索进程池 | 交互式操作，不进任务抽屉；可取消；结果写成固定结果 |
| 拖出生成 WAV | Core（同步短操作，可取消） | 规格 13 §13.1.1：不进任务列表 |
| 波形峰值、缩略图、频谱 | Core 的低优先级线程池调用 ffmpeg 子进程 | 可清理缓存 |

### 2.2 取消

- **任务**：每个任务进程在 POSIX 上 `start_new_session=True`（独立进程组），Windows 上加入一个 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 作业对象；
  取消 = `killpg` / `TerminateJobObject`，连带结束 Studio worker、ffmpeg、rubberband 等子孙进程；只影响本任务。
  Windows 上不用 `kill(pid, 0)` 探活，改用进程句柄等待（规格 14 §14.9）。
- **排队任务**：直接改状态为已取消，从不启动进程。
- **检索**：协调器给每次检索一个取消令牌（共享内存标志），worker 每处理一个采样检查一次；用户再次点“查找”或关闭结果即取消旧检索。
  超过 2 秒仍未退出的 worker 被强制结束并重建进程池。被取消的检索不写固定结果。
- **拖出准备**：Esc/松手/失焦 → UI 通知 Core 取消；已生成的持久文件保留（规格 12 §12.2）。
- **结果采纳**：任务进程只写自己的 `Data/Jobs/<id>/` 目录并返回结果描述；**是否登记由 Core 按规格的采纳规则决定**
  （已取消 → 不写；输入在任务期间变化 → 只进历史；人工头/更新的头 → 只进历史；规格 08 §8.4）。所以取消永远不会留下半成品登记。

### 2.3 生命周期与崩溃

- UI 启动 Core（同一可执行文件的另一入口），Core 持有工作区锁（`Data/workspace.lock`，用户不可见目录）；同一工作区只能有一个 Core。
- Core 检测到管道断开（UI 崩溃或退出）→ 取消全部任务（整树）→ 退出。不留孤儿进程（两平台一致，规格 13 §13.1.2）。
- 退出应用时若有排队/运行任务：提示“退出将取消 N 个任务”；确认后取消再退出。下次启动把“运行中”的任务标为**已中断**，可重试。
- Core 崩溃：UI 显示“核心服务已退出”，提供“重新启动核心”；数据库事务保证不留半成品。任务进程崩溃 → 该任务“已中断”。
- “另开窗口”是同一 UI 进程里的第二个顶层窗口，共享 CoreClient 与 PlaybackCoordinator（所以“只有一个声音”跨窗口成立）。

### 2.4 并发与一致性

- Core 单写连接 + 多个只读连接（WAL）；检索 worker 只读打开。
- 每个可编辑对象有 `version` 整数（乐观并发）；编辑预览携带版本，应用时不一致就拒绝（规格 07 §7.6）。
- 失效通知：每个写事务产生“变化集”（对象类型 + ID + 操作类型），Core 推送给 UI；**UI 只显示“资料已更新”类提示，不自动刷新/重排/重选**（P8）。
  例外按规格：用户主动截取/回导后打开新子采样。

---

## 3. 代码结构

```
src/ottosmasher/
  app/        UI：shell（顶栏、导航、任务抽屉、命令面板、设置）、pages/（library, sources, tools）、
              widgets/（waveform, block_canvas, range_bar, collection_view, video_view …）、viewmodels/
  core/       Core 进程：rpc、services/（每个领域一个服务）、edits（统一编辑通道）、scheduler、search_coordinator、cleaner
  domain/     纯领域逻辑（无 IO）：mapping、overlap、naming、tag_expr、facets、subtitle_rules、nature_rules、opedrules、filename
  algo/       基线算法（纯函数 + numpy）：effective_range、strength、rhythm_units、pauses、segments、quantize、
              stretch_map、speech_search、pitch_search、flatten_target、flatten_mask、acoustic_metrics
  lang/       语言插拔：base（LanguageProfile 协议）、ja/（前端、mora、辞典、默认规则）
  models/     ONNX 会话工厂与实测证据、pydomino 适配、FCPE、PC-NSF-HiFiGAN
  media/      ffprobe 探测、按区间解码、MP3 V0 编码与无缝校验、WAV/FLAC 写出、峰值、缩略图、频谱、视频片段导出
  studio/     PyMSS Studio 发现、列模型、推理、模型指纹
  jobs/       任务进程入口与各任务实现
  store/      SQLite schema 与迁移、仓储、文件发布（原子、租约、清单）、工作区布局
  i18n/       Fluent 加载、格式化、错误码表；locales/zh-CN/*.ftl
  platform/   进程树（进程组 / 作业对象）、剪贴板（REAPERMedia）、路径（长路径、可移植文件名）
tests/        unit/ synthetic/ integration/（需 OTTO_FIXTURES）ui/（pytest-qt）perf/
tools/        拉取第三方二进制、校验模型、合成数据生成器、伪语言生成
```

`domain/` 与 `algo/` 不依赖 IO 和 Qt，规格里的数值例子直接写成单元测试。

---

## 4. 数据模型草案

> 业务事实以规格 04 为准；下面是表结构草案（阶段 1 定稿）。ID 一律为不透明的随机 128 位十六进制串（`uuid4().hex`），
> 内容指纹与文件位置是独立字段（规格 04 §4.6）。所有用户可编辑对象都有 `version`（乐观并发）和 `created_at`/`updated_at`。
> 显示文字不入库：性质、角色、来源种类等存稳定的内部值（如 `speech`、`vocal`），界面按语言显示（规格 15 §15.7）。

### 4.1 原片与流

| 表 | 关键字段 | 说明 |
|---|---|---|
| `source` | id, kind(`media`/`standalone_audio`), path, fingerprint, size, mtime, duration, work, episode, source_type, subtitle_path, default_audio_stream, media_state(`available`/`released`), visual_binding_id, current_subtitle_version_id, version | 原片。`kind=standalone_audio` 是“独立导入的外部音频”（规格 06 §6.6）；`media_state=released` 是独立化后“媒体已释放的原片”（§4.9） |
| `source_stream` | source_id, kind(audio/video), ordinal（第几条音频/视频流）, container_index, codec, sample_rate, channels, bit_depth, language, title, start_time, duration, is_attached_pic | 封面图不算视频（规格 05 §5.1）；音轨按“第几条音频流”选择（R22.2） |

内容指纹：`size` + 文件头/中/尾各 1 MiB 的 SHA-256 + 流签名（快、足以判断“被替换”）；库内生成文件用全量 SHA-256。
播放/导出/处理前用 size+mtime 快速核对，变化时重算指纹，不一致即报“音源已改变”（不替换、不回退）。

### 4.2 声音资产、角色、默认轨

| 表 | 关键字段 | 说明 |
|---|---|---|
| `sound_asset` | id, source_id, origin(`stream`/`separation`/`flatten`/`reimport`), media_file_id, stream_ordinal, duration, mapping（控制点数组）, input_asset_id, input_start, input_end, stem_name（原样大小写）, production（操作、参数、模型身份/指纹、算法版本）, language, content_key | 不可变。`content_key` = hash(文件内容指纹, 音频流, 解码规范) ——测量按它共享 |
| `asset_storage` | asset_id, range_start, range_end, media_file_id, kind(`primary`/`materialized_slice`) | 资产的**物理存储**。正常只有一条 primary；独立化时增加覆盖采样区间的无损切片（§4.9）。这是规格 04 §4.2.4 允许的“显式存储迁移”：只改位置/编码，不改时间关系 |
| `media_file` | id, path（工作区相对或绝对）, location(`external`/`library`), fingerprint, size, mtime, format, sample_rate, frames, encode_manifest | 原片文件、库内音轨、回导文件、物化切片 |
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
| `measure_run` | id, kind(`alignment`/`f0`/`acoustic`), owner_type(`sample`/`asset_text`), owner_id, content_key, range, inputs（语言、文本版本、辞典版本、前端版本、模型身份与指纹、目标区间、窗口、容差、设备）, status(`ok`/`failed`/`cancelled`/`stale`), manual(bool), result（对齐结果 msgpack；F0 指向文件）, created_at | 不可变版本 |
| `measure_head` | owner_type, owner_id, kind, run_id | 当前采用的版本；采纳规则见规格 08 §8.4 |
| `Data/Measurements/f0/<content_key>/` | 分段的 `f0.npy`（N×3：F0、置信度、能量，float32 逐帧无损）+ 覆盖清单 | 按声音内容共享；“同一内容 + 同一流 + 同一映射 + 完整覆盖”才复用（R11.10、规格 10 §10.1） |
| `Data/Measurements/pitch_index/<content_key>.npz` | 50 ms 摘要（可靠帧 MIDI 均值、可靠覆盖率、平均能量）+ 版本信息 | 由 F0 组成，**不当缓存删**（规格 10 §10.2.5） |

拉平成品的 `pitch:` 标签来自资产 `production.target`（登记时记录的目标音），不来自重测（规格 11 §11.4）。

### 4.6 派生数据（可重建）

| 表 | 内容 | 失效条件 |
|---|---|---|
| `rhythm_cache` | 每个“采样 + 分析版本 + 路线 + 拆点/占格 + 停顿参数 + 惩罚度”的音块、停顿、停顿段、语段、占格骨架 | 任一上游变化 |
| `speech_index_row` | 每采样（含语段）一行：音块列数组（起音、结束、首元音、前导辅音、可靠帧 MIDI 中位数、P10/P90、覆盖率、走势、停顿段内相对音高、相对响度、强度、有效起止、持续终点、停顿段号、语段号）+ 占格骨架 | 同上；采样绑定变化、删除 |
| `scheme_cache` | (采样, 方案身份, BPM, 密度) → 速度、目标拍、映射控制点 | 方案身份任一项变化（规格 09 §9.5.3） |
| `Data/Cache/` 文件 | 波形峰值金字塔、缩略图、频谱、临时解码 PCM（带租约） | 可清理 |

### 4.7 检索结果与筛选

| 表 | 关键字段 | 说明 |
|---|---|---|
| `result_set` | id, kind(`speech`/`pitch`), created_at, title, query, scope_snapshot（范围栏条件 + 主表达式 + 当时的筛选器内容）, params（含 BPM）, stats（后端耗时、缺少有效分析计数、是否截断）, ui_state（激活、页码、选中、滚动）, closed | 固定结果；重启后恢复不重搜（规格 04 §4.2.10） |
| `result_member` | result_id, rank, sample_id 或 (asset_id, 原片模式), binding_snapshot（asset_id/start/end/分析版本/索引版本）, hits（每处命中：区间、证据、方案、分数） | 读取时只核对失效（已删除/绑定变化/索引变化），不重算不重排 |
| `saved_filter` | id, name, conditions（文字、范围表达式、分面、性质、原片、星标、属性条件）, sort_order, version | 范围栏上的命名预设 |

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

1. **声音**：对每个要独立化的采样，把它绑定资产的 `[start, end)`（两端各留 1 帧余量）解码为**无损 FLAC 切片**写入
   `Library/Independent/<source-key>/`，作为该资产的 `asset_storage(kind=materialized_slice)`。采样的绑定（资产 + 区间）**不变**，
   所以测量（按 `content_key` 共享）、固定结果、来源记录都继续有效——测的就是同一段声音（PCM 相同，切片用无损编码正是为此）。
2. **画面**：按该采样的画面绑定生成视频片段（同步视频取原片对应区间），存入同一目录，作为采样的 `visual_binding(mode=materialized_clip)`。
3. **原片元数据**：删除原片时，若仍有已独立化的采样，原片记录保留为 `media_state=released`：作品、集数、来源类型、字幕版本与标注、OP/ED、
   资产角色等都在，标签继承与来源追溯照常工作；原片文件引用置空，未被切片覆盖的资产区间不可播放（明确报错）。
4. 删除原片时**不删**已独立化的采样及其切片/片段；其他采样、库内整轨、测量按规格 04 §4.5 级联删除（只删库内生成文件，不删磁盘原片与导出）。
5. 界面区分“已独立化”（采样徽标）与“媒体已释放”（原片徽标）；独立化采样不能再“返回原片”看前后文，界面说明原因。

> 物化切片用 FLAC（无损）而不是 MP3 V0，是为了让“测量随资产保留”严格成立。这一点规格没写，列在 `docs/QUESTIONS.md` 请确认。

---

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
<Workspace>/                         工作区（发布版默认 ~/Documents/OttoSmasher Workspace/，可在设置里换；开发期 = 仓库内 dev-workspace/）
├── Library/                         素材库：用户可见，不是缓存，不自动清理
│   ├── Tracks/
│   │   └── src-<id8>/               每个原片一个目录（src- + 原片 ID 前 8 位；目录名只用 ASCII）
│   │       ├── Separation/          分离声部（LAME VBR V0 MP3）
│   │       ├── Flatten/             拉平成品（MP3 V0）
│   │       └── Reimport/            回导成品（复制进来，保持原格式）
│   ├── Independent/
│   │   └── src-<id8>/               独立化物化：FLAC 声音切片、视频片段
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

- 文件名里的内容段（采样名、原片名）照常保留中日文；目录名只用 ASCII 英文。界面里每个原片/采样都有“打开所在目录”。
- **原子发布**：先写 `Data/Staging/`，校验后 `os.replace` 到目标；导出到其他卷（自定义导出目录）时先复制为同目录下的隐藏临时名再改名，
  未完成的发布记录在数据库里，启动时清理残留——用户可见目录里不会长期留下 `.part`/`.lock`（规格 12 §12.6）。
- **租约**：临时 PCM 等文件被任务使用时登记租约（数据库行，含进程 ID 与过期时间）；清理器跳过有租约或 15 分钟内生成的文件。
- **清理口径**：引用关系来自数据库外键（`media_file` 被谁引用），不是在来源记录里搜路径字符串（规格 17 §17.3 #20）。
- 空闲判定用 UI 上报的“最后一次用户输入时间”，界面轮询不刷新空闲计时；策略与规格 13 §13.3.3 一致（空闲 5 分钟、每小时至多一次、1 天、512/384 MiB）。

---

## 7. 界面国际化

- **文案资源**：`src/ottosmasher/i18n/locales/<lang>/*.ftl`（Fluent）。代码里只出现消息键：`t("library-count-samples", count=n)`。
  术语以规格 01 §1.6 为准；本轮只有 `zh-CN`。
- **后端错误**：`AppError(code, args)`，例如 `track-out-of-range {start} {end}`；界面按当前语言渲染。日志只用英文消息键 + 参数。
- **稳定内部值**：性质、角色、分面、任务类型、来源种类等在数据里存内部值，显示名走资源（`nature-speech = 语音`）。
- **格式化**：数字、时长、文件大小、日期用 Babel 按界面语言格式化；秒数显示保留 3 位小数的规则写在格式化函数里。
- **导出文件名固定词**（原混音、人声、拉平-、卡拍-、片段、局部-、试听片段）来自文件名模板 + 当前界面语言的资源；切换语言只影响之后的导出。
- **两个独立设置**：界面语言（设置 → 通用）与首选采样语言（设置 → 原片，默认日语）。
- **测试**：自动生成伪语言 `x-pseudo`（每条文案加方括号并拉长 30%），pytest-qt 跑主要页面，断言控件文字都带方括号（R22.13）；
  再加一条静态检查：`app/`、`core/`、`domain/` 源码里除注释和测试外不得出现 CJK 字面量。
- Qt 自带控件（标准按钮、文件对话框）加载对应的 Qt 翻译。

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

## 9. 三大搜索的索引与性能方案

目标（规格 15 §15.2、09 §9.6.5、10 §10.2.7）：约 **3 万条 × 3 秒**的语音采样上，常见查询（S3：BPM 180 x-xx 到句末；C-E-G；几块带音高/元音条件的人力查询；
一两行的音高查询）**30 秒内**完成；检索并行、可取消、不阻塞界面。开发机：M1 Pro（8 性能核 + 2 能效核）、16 GB。

### 9.1 规模估算

- 3 万条 × 3 秒 ≈ 9 万秒语音；按每秒约 3–5 个音块 → 约 30–45 万个音块；每块约 20 个数值特征 → 约 70 MB（float64），可全部常驻 worker 内存。
- F0：9 万秒 × 100 帧 = 900 万帧 × 3 × 4 字节 ≈ 108 MB；50 ms 摘要约 180 万格 × 3 ≈ 22 MB。

### 9.2 语音检索（音块 / 节奏）

1. **范围快照**（Core，SQLite）：范围栏条件 ∩ 主表达式 → 候选采样 ID 列表（借助 `sample_effective_tag` 索引；1 万条时 < 100 ms）。
2. **分片**：候选按 ID 均分给进程池（N = 物理核数 − 2，M1 Pro 上 6 个）。
3. **worker 内**（只读）：批量读 `speech_index_row`（缺行的采样现场从测量构建投影——不推理；还缺就计入“缺少有效分析”）。
   - 逐块条件先**向量化**：每个条件生成一个“音块合格”布尔数组（未知 → False，规格 P7）；
   - 邻接窗口：对 n 块查询，用滑动窗口在合格数组上求“连续 n 块都合格 + 同一停顿段（不跨停顿时）+ 最大间隔”的起点集合——全部是数组运算；
   - **节奏证据**只对通过的窗口计算：近快/近慢方案需要真实时间映射（规格 09 §9.5），按 (采样, 方案身份, BPM) 缓存在 worker 内存和 `scheme_cache`；
     一个 BPM 下首次计算约 0.3–1 ms/采样（旧版约 1 ms），3 万条 / 6 进程 ≈ 2–5 秒；
   - 证据与评分逐项复现规格 09 §9.6.4（平移拟合、中位数平移、归一化形状），同分取近快。
4. **合并**：Core 归并各分片的有序结果（按 (最佳分数, 采样) 排序），**全部**写入 `result_member`（不截断），返回第一页。
5. **取消**：§2.2。

预估：常见查询 3–10 秒（3 万条）；最坏情况（“不限节奏 + 1 块 + 无条件”命中几乎所有音块）主要耗时在写入结果，分批写入、先返回第一页。
如果实测某类查询超过 15 秒，再按热点用 numba 编译（不改结果；改实现属于自由设计）。

### 9.3 音高检索

- 每段声音的 50 ms 摘要与原生帧以 `.npy` 内存映射；worker 按候选声音（采样模式：允许起点区间；原片音轨模式：整条资产）加载。
- 粗筛：对每个查询块，用累积和在摘要格上 O(1) 求每个起点的“带内可靠覆盖之和 / 格数”，全部起点向量化；
- 分组（盆地）→ 每组按（粗分, 起点）排序 → 轮询取候选至 2000 → 精排（±50 ms、10 ms 步、原始阈值逐帧判定）→ 每组留最优 → 去重 → 前 100。
  逐项复现规格 10 §10.2.4，含“只合并允许起点、不合并声音区间”。
- 预估：采样模式 3 万条 < 3 秒；原片模式 100 集 × 24 分钟（约 1400 万帧）< 10 秒。

### 9.4 单音指标筛选

指标随声音内容存在测量表里（准备是显式任务）；筛选是即时浏览（SQL 范围条件 + 缺失计数），不经进程池。

### 9.5 性能验证

`tools/synth_library.py` 生成 3 万条 × 3 秒的合成采样（合成对齐、F0、能量，固定随机种子），写入独立的临时工作区（不碰用户工作区）；
`tests/perf/` 用它跑 S3/S5 类查询与音高查询，记录 P50/P95 耗时与机器信息。阶段 7 验收时给出数字。

---

## 10. 播放与媒体

### 10.1 libmpv

- 每个窗口两个 mpv 实例：**原片播放器**（视频 + 音频，render API 画进 `QOpenGLWidget`，`hwdec=videotoolbox-copy`/`d3d11va-copy`）
  与**试听播放器**（`vid=no`，列表/命中/详情/弹窗试听共用）。PlaybackCoordinator 保证全应用同一时刻只有一个在响；切页暂停全部（PB17）。
- 范围播放：用 mpv 的 `ab-loop-a/b`（循环）与 `end`（单次）让**引擎**截停；任何普通跳转或播放/暂停先清除范围（规格 05 §5.3.1）。
- 外挂声部：`audio-files` + `aid` 切换 + `audio-delay`（= 原片范围起点 − 资产选区起点），加载期间原音轨静音；不转码不代理（R22.1）。
- 字幕：mpv 自带字幕关闭（`sid=no`）；当前字幕版本的原文由我们用 OSD 覆盖层（`osd-overlay`，纯文本、白字黑边、按画面高度缩放）画在画面内部底部。
- 时钟：50 ms 读一次播放位置，两次之间按速率插值；换源时用代次号丢弃旧事件（规格 14 §14.9）。
- **libmpv 动态库来源**（阶段 1 需要所有者同意下载）：macOS arm64 与 Windows x64 的预编译 libmpv（含 HEVC/FLAC/VideoToolbox/D3D11），
  放 `third_party/`，固定版本并校验 SHA-256。候选来源与大小在阶段 1 开始前单独列给所有者确认。
- 原生播放不可用（库缺失、render 初始化失败）→ 明确报错，不换其他播放方式（P6）。

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

- 拖出：Option/Alt 按下时冻结请求 → 移动 > 4 px 才请求 Core 生成 → 生成期间提示，Esc/松手/失焦放弃 → 完成且仍按住时 `QDrag.exec()`；
  进入系统拖拽后 Esc 交给系统。生成失败用消息提示（不吞错误）。
- REAPER：Core 生成未烘焙原声 WAV 与 `<ITEM …>` 文本（规格 12 §12.3，12 位小数、引号选择、单调性校验）；UI 写剪贴板类型 `REAPERMedia`
  （NUL 分隔、双 NUL 结尾），写后回读校验。Windows 实测前标“未验收”。

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
| 界面 | pytest-qt 无头：选择与右键规则、快捷键焦点、范围栏、伪语言；人工只验原生播放、拖放到 REAPER 这类自动化证明不了的 | 阶段验收前 |
| 性能 | 1 万条分页（R8.9）、3 万条三大搜索（R14.15） | 阶段 7、8 |
| 平台 | Windows x64：CI 构建 + 冒烟；实机验收前一律标“未验收” | 阶段 10 |

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
| libmpv render API 在 `QOpenGLWidget` 中播放 1080p HEVC10 的流畅度（macOS OpenGL 已弃用但可用） | 阶段 1 探针：YY1-01 整集播放、拖动、逐帧 | 改用 `wid` 原生子窗口嵌入（回到需要处理遮挡的方案），先问所有者 |
| mpv 对 LAME 无缝 MP3 的样本级对齐 | 合成斜坡 MP3 的偏移测试 | 正式音轨改存 FLAC（要所有者同意，涉及存储预算） |
| pydomino C++ 扩展在 Windows 上构建 | CI（Windows runner）构建 | 自写最小 pybind11 包装同一份上游 C++ 源码 |
| pyopenjtalk-plus 导入时加载旧读音模型 | 导入钩子 + 测试“导入不加载任何模型” | 延迟导入包装 |
| 检索 3 万条 30 秒 | 合成库基准 | numba 热点编译 |
| Python UI 在大列表与波形上的流畅度 | 虚拟化模型 + 峰值金字塔；pytest-qt 计时 | 热点控件改为 QML/OpenGL 绘制 |

---

## 14. 分发（阶段 10 细化）

- PyInstaller onedir：macOS `.app`（ad-hoc 签名，去绝对 rpath）、Windows 便携目录；各打成 ZIP，严格 < 2,000,000,000 字节。
- 包含：Python 运行时与依赖、ONNX Runtime、libmpv、ffmpeg/ffprobe、rubberband、G2P 辞典与 tokenizer、模型配置等非权重支持文件。
  不包含：模型权重、PyTorch、PyMSS Studio、用户素材。
- 程序目录只读；工作区与程序分离；首次启动不需要“释放运行库”（onedir 已是解开的目录）。
- 冒烟检查：含中文与空格的隔离路径、清空 Python/Conda 环境变量、空工作区、运行库探测、原生播放截停一段短区间、媒体工具可用。
- 许可证：GPL-3.0-or-later（Rubber Band 为 GPL）；随包附第三方声明。
