# 桌面 Helper 0.9：统一素材目录

2026-09-15。采用 Electron + React/TypeScript，Python 提供共用业务操作、数据库和任务。
这是本机源码运行版，还没有制作签名安装包或完成 Windows 验收。

## 启动与窗口

```sh
./scripts/setup_desktop.sh
./otto ui library
./otto ui search
./otto ui cut
```

也可以双击根目录 `启动素材管理器.command`。每个窗口右上角可独立打开其他窗口。
首次安装需要 Node 22+、pnpm；当前机器已安装在隔离目录。脚本支持 `OTTO_NODE` 指定可执行文件。
三个窗口共用本机 `127.0.0.1:18765` 服务；只开素材管理器不创建截取窗口，不加载推理模型。
关闭窗口不取消后台任务。任务面板或 `./otto jobs list` 可查看日志、取消和重试。
原网页 demo 仍可通过 `./otto serve` 在 8765 使用。

- **素材管理**：来源／集合／多标签交集筛选，快速试听、波形、备注、评分、批量标签、偏好版本和 A/B 试听。
- **检索**：使用同一目录范围；音块属性、慢放偏好、三种量化、节奏／F0、同句模型对照与卡拍试听沿用成熟实现。
- **截取**：原片与字幕上下文、音轨选择、预计算波形、缩放和选区；Space 播放，I/O 设起止，方向键按标称视频帧步进，Shift 方向键按 1 ms 定位。最终音频输出按源采样帧计算。

节奏与 F0 编辑器当前通过 **共享 iframe 适配面板** 使用原有实现，外层目录及截取器为 React。
没有复制或重新实现三套量化算法。下一步可逐个把绘图部件提取成 React 组件，核心操作不依赖此迁移。

## 素材与文件

所有登记素材都可搜索，不存在第二套“正式入库”。收藏和集合只增加数据库关系。

| 操作 | 保存内容 |
|---|---|
| 原字幕台词迁移 | 原片范围引用；有分析时保留模型裁切范围和原字幕范围的区别 |
| 保存截取选区 | 原片、音轨和精确起止；不自动复制原片 |
| 登记外部音频 | 引用原路径；可另选复制到持久目录，副本作为同一素材的偏好版本 |
| 从分析详情保存语段 | 保留模型、原句和准确 `scope_id`；既有兼容分析可复用 |
| 准备 WAV／视频 | 实际文件、来源清单及版本关系，随后可从底栏拖出 |
| 分离为新版本 | 后台 pymss，保存实际声部名、源文件及权重指纹；不静默回退混音 |

路径：

- `data/catalog.sqlite3`：目录、版本、标签、集合、任务，以及既有分析记录。
- `data/backups/pre-materials-*.sqlite3`：迁移前 SQLite 一致性备份。
- `data/media/imports`：选择复制保存的原始文件副本。
- `data/media/subtitles`：已登记字幕版本的不可变快照。
- `data/media/exports`、`data/media/processed`：持久截取／分离文件。
- 既有严格卡拍输出继续位于 `outputs/clips`；REAPER 原声继续位于用户配置的持久目录。
- `data/cache`：可清理的波形、预览代理、普通试听；不能把整个 `data` 当缓存删除。
- `data/logs/jobs`：任务日志。

原片移动后会显示缺失；已经保存的版本仍可试听／导出。当前没有自动追踪文件移动。
从文件清单重新登记能恢复已知来源，任意未登记磁盘文件不会进入检索。
同一素材的多个处理版本在详情展开，不自动变成重复搜索结果。

## 分析、筛选与方案

只有存在兼容语音分析的素材参与节奏搜索。没有分析的采样仍能管理、试听和导出，**不提供虚构起音或 F0 零线**。
当前自动复用范围限于既有分析的整句和明确语段。任意裁切保存为待分析范围，尤其跨越节奏单元的切点不沿用整句分组。
当前版本没有新增任意音频 ASR、通用非语音起音或人工起音功能。

`material_operations` 将素材／版本／范围映射到已测量的分析身份；旧 `cue_id` 接口作为兼容适配器保留。
模型绑定的子范围不能使用另一个范围的方案。GUI、CLI 的卡拍试听与持久 WAV 都消费同一 `plan_id`。
检索在量化索引上预筛选集合／标签／素材范围，不在请求中运行推理。

`cluster:` 标签是相似声音分组；`character:` 标签来自人工角色标注。
“试听分组／角色标注”复用现有批量编辑视图；“更新讲话者标签”读取现有结果，不重新提取嵌入。
人工覆盖与撤销按原片时间范围处理，较新的标注优先。

复制到 REAPER 沿用已有原生 Item 方案；桌面底栏的“拖出”交接已经准备好的真实文件。
拖出 WAV 是烘焙音频，复制到 REAPER 是带伸缩标记的原声，两者是不同的交接方式。

## CLI 组合

以下命令输出 JSON；`--json` 接收 JSON 文件或 `-`（标准输入）。尖括号为待替换值。

```sh
# 无须打开桌面的文件处理
./otto media probe /absolute/path/input.wav
./otto media cut /absolute/path/input.wav --start 1.2 --end 3.8 --output /absolute/path/cut.wav
./otto media cut /absolute/path/input.mkv --start 12 --end 16 --audio-stream 1 --video --register

# 登记引用，或保存持久副本；集合不会复制文件
./otto library register /absolute/path/input.wav
./otto library register /absolute/path/input.wav --copy
./otto library manifest /absolute/path/cut.wav.json
./otto library search '台词' --tag character:角色名
./otto library collection '本次作品候选'
./otto library add-to <material_id> <collection_id>
./otto library range <source_id> 12.25 15.8 --audio-stream 1 --title '选区'
./otto library get <material_id>

# 已分析素材：方案返回 plans；取其中 plan_id 供试听和导出使用
printf '%s' '{"analysis_kind":"sofa","strategy":"acoustic","bpm":140,"density":4}' |
  ./otto process plans <material_id> --json -
printf '%s' '{"analysis_kind":"sofa","mode":"strict","plan_id":"<plan_id>"}' |
  ./otto process preview <material_id> --json -
./otto process export <material_id> --plan-id <plan_id> --analysis-kind sofa

# 路径输入的分离不自动登记；素材输入会把结果登记为新版本
./otto process separate /absolute/path/input.wav --stem vocals
./otto process separate --material-id <material_id> --stem vocals
./otto jobs list
./otto jobs log <job_id>
./otto jobs cancel <job_id>
./otto jobs retry <job_id>

# 原有字幕预处理与固定语料分析脚本的后台入口；按需运行，不是启动时自动执行
./otto subtitles prepare --source-id <source_id>
./otto subtitles sub-align --source-id <source_id>
./otto subtitles subplz --source-id <source_id>
./otto analyze phones --backend sofa --limit 200
./otto analyze features
./otto analyze speakers
./otto analyze index --kind sofa
```

字幕预处理输出与旧分析保持分离，不自动以新字幕覆盖已有音素身份。`library sync` 登记已有 cue 并保存其字幕版本快照，不重新对齐。
当前 `analyze phones/features/speakers` 封装既有语料脚本；不是任意无文本采样的分析接口。
任务由独立进程运行，重任务串行，失败保留日志，重试生成新任务 ID。

## 本轮验证与边界

- 迁移 4,730 条原字幕记录，保留分析／人工标注；迁移备份存在，外键检查通过；12 个字幕快照已登记。
- 真实 HEVC Main 10／FLAC 原片在当前 Electron 中直接播放成功。提供局部／整片 H.264/AAC 预览代理作为兼容路径，最终切点仍按原片时间计算。
- 自动检查覆盖精确采样裁切（比较真实输出样本）、中文日文路径、来源清单回导、收藏不复制、版本持久性、被修改输出拒绝复用、独立语段集合筛选、跨范围方案拒绝和任务取消／重试。
- 一条真实分析台词验证方案、严格试听、持久 WAV 登记使用相同 `plan_id`；1 秒真实片段通过新的 pymss 后台任务，保留两个权重文件的指纹。故意提交缺失输入也能明确记录失败。
- 54 项相关自动检查通过；TypeScript 检查与 Vite 构建通过。固定 SOFA 全句检索示例热搜索 0.29 秒，50 条目录记录读取 0.015 秒；首次更新 199 条派生索引耗时 14.38 秒，未运行模型。此为一个查询的本机测量，不代表全部查询上限。
- 本轮没有重跑 200 句模型或 12 集聚类，没有重新执行 REAPER 完整回归。
- **实际跨应用拖入 REAPER 尚未通过验收**：本机原生 UI 控制读取 REAPER／Electron 连续超时，停止反复尝试。`startDrag` 接口接入与文件存在，不代替实际拖放验收。
- 新 UI 还需要日常使用打磨。未宣称桌面框架性能最优；未宣称音素边界或聚类已经人工确认。
