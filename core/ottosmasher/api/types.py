"""命令的参数与返回类型（TypedDict）。生成前端类型与命令目录的唯一来源（见 ``api/__init__.py``）。

约定：
- 类名就是前端的类型名（全局唯一）；参数类型以 ``Params`` 结尾。
- 可选参数写成 ``NotRequired[X | None]``：界面发 ``undefined`` 时 msgpack 编成 nil。
- 时间值注明时钟：原片秒 / 资产局部秒 / 文件秒（AGENTS §9）。
- msgspec 不支持“多个字典类型的联合”，按情况返回不同形状的结果写成一个类型、可能缺的键用 ``NotRequired``。
"""

from typing import Any, Literal, NotRequired, TypedDict

Nature = Literal["speech", "pitched", "unpitched", "unclassified"]
Role = Literal["vocal", "sfx"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]


# ---------------------------------------------------------------- 通用


class NoParams(TypedDict):
    pass


class IdParams(TypedDict):
    id: str


class IdsParams(TypedDict):
    ids: list[str]


class SourceIdParams(TypedDict):
    sourceId: str


class SourceIdsParams(TypedDict):
    sourceIds: list[str]


class JobIdParams(TypedDict):
    jobId: str


class ErrorWire(TypedDict):
    """Core 的错误：错误码 + 参数（界面按当前语言生成提示）。"""

    code: str
    args: dict[str, Any]


class JobRef(TypedDict):
    id: str


# ---------------------------------------------------------------- 编辑通道（ARCHITECTURE §5）


class EditLabel(TypedDict):
    code: str
    args: dict[str, Any]


class EditOp(TypedDict):
    """一条编辑：``op`` 缺省为 update（要 ``id`` 与 ``version``）；create 只要 ``fields``。字段与取值由编辑通道逐条校验。"""

    entity: str
    op: NotRequired[str | None]
    id: NotRequired[str | None]
    version: NotRequired[int | None]
    fields: NotRequired[dict[str, Any] | None]


class EditBatch(TypedDict):
    label: NotRequired[EditLabel | None]
    ops: list[EditOp]


class EditBatchParams(TypedDict):
    batch: EditBatch


class EditDiff(TypedDict):
    field: str
    before: Any
    after: Any


class EditChange(TypedDict):
    index: int
    entity: str
    id: str
    op: str
    diffs: list[EditDiff]


class EditPreview(TypedDict):
    changes: list[EditChange]


class EditApplied(TypedDict):
    edit_id: str | None
    changes: list[EditChange]


class EditUndone(TypedDict):
    edit_id: str
    undone: str
    label: EditLabel
    changes: list[EditChange]


class UndoPeek(TypedDict):
    edit_id: str
    label: EditLabel


# ---------------------------------------------------------------- 应用、设置、模型、界面状态


class Hello(TypedDict):
    version: str
    pid: int
    workspace: str
    schema_version: int
    interrupted_on_start: int
    dev: bool


class SettingEntry(TypedDict):
    value: Any
    default: Any
    version: int
    group: str


class ModelFileStatus(TypedDict):
    path: str
    role: Literal["weight", "support"]
    state: Literal["ok", "missing", "size-mismatch", "sha-mismatch", "unverified"]


class ModelStatus(TypedDict):
    model: str
    state: Literal["ready", "missing", "mismatch", "unverified"]
    files: list[ModelFileStatus]
    url: str


class OnnxRuntimeStatus(TypedDict):
    loadable: bool
    version: NotRequired[str]
    providers: NotRequired[list[str]]
    error: NotRequired[str]


class RuntimeStatus(TypedDict):
    onnxruntime: OnnxRuntimeStatus


class ModelsStatus(TypedDict):
    models_dir: str
    support_dir: str
    files: list[ModelStatus]
    runtime: RuntimeStatus
    # 当前设备设置（实测只列这个设置下的记录）
    device: "JobDevice"
    probes: list["ModelProbe"]


class UiGetParams(TypedDict):
    page: str
    window: NotRequired[str]


class UiSetParams(TypedDict):
    page: str
    key: str
    value: Any
    window: NotRequired[str]


class QuitParams(TypedDict):
    cancel_jobs: NotRequired[bool]


class PrepareQuit(TypedDict):
    active: int


class Quit(TypedDict):
    cancelled: int


class DictionaryTextParams(TypedDict):
    text: str


class DictionaryLineError(TypedDict):
    line: int
    reason: str
    first: NotRequired[int]
    max: NotRequired[int]


class DictionaryCheck(TypedDict):
    entries: int
    errors: list[DictionaryLineError]


class DictionarySaveParams(TypedDict):
    text: str
    # 打开编辑器时读到的设置版本（乐观并发：期间被改过就拒绝保存）
    version: int


class DictionaryPreviewParams(TypedDict):
    sentence: str
    # 草稿辞典；缺省用当前生效的辞典
    text: NotRequired[str | None]


class InferTestParams(TypedDict):
    filename: str
    # 草稿规则（未保存）；缺省用当前设置
    rules: NotRequired[list[str] | None]


class InferTest(TypedDict):
    work: str | None
    episode: str | None
    rule: int | None
    timedOut: list[int]


# ---------------------------------------------------------------- 任务（ARCHITECTURE §11）


class JobProgress(TypedDict):
    stage: str | None
    done: float | None
    total: float | None
    percent: float | None
    code: str | None
    args: dict[str, Any] | None


class JobItems(TypedDict):
    total: int
    ok: int | None
    failed: int | None


class JobDevice(TypedDict):
    """提交时冻结的设备设置（13 §13.1.2）。"""

    accelerate: bool
    directml_device: int


class ModelProbe(TypedDict):
    """实测记录（14 §14.7）：passed 带各 EP 执行的节点数，failed 带原因。"""

    model: str
    device: JobDevice
    status: Literal["passed", "failed"]
    nodes: dict[str, int] | None
    error: str | None
    tested_at: str


class JobSummary(TypedDict):
    id: str
    kind: str
    channel: Literal["model", "light"]
    status: JobStatus
    affects: dict[str, list[str]]
    progress: JobProgress | None
    error: ErrorWire | None
    result: Any
    device: JobDevice
    retry_of: str | None
    items: JobItems | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    # 自动准备之类的后台任务（排在用户提交的任务后面）
    background: NotRequired[bool]


class JobsListParams(TypedDict):
    limit: NotRequired[int]


class JobSubmitParams(TypedDict):
    kind: str
    params: NotRequired[dict[str, Any]]
    affects: NotRequired[dict[str, list[str]] | None]


# ---------------------------------------------------------------- 原片（规格 05）


class SourceCounts(TypedDict):
    lines: int
    hasMarkers: bool
    oped: int
    samples: int
    # 语音性质的采样数与其中已分析（当前头为成功测量）的数
    speech: int
    analyzed: int


class SourceRow(TypedDict):
    id: str
    path: str
    work: str
    episode: str
    source_type: str
    duration: float
    media_state: Literal["available", "released"]
    subtitle_path: str | None
    default_audio_stream: int
    created_at: str
    version: int
    # 采样库导入时选的根文件夹（ARCHITECTURE §4.10）；原片页「＋」登记的为 null
    import_root: str | None
    # 所在的原片文件夹（阶段 3.13）；不在任何原片文件夹里为 null
    root_id: str | None
    # 相对原片文件夹的路径（/ 分隔）
    rel_path: str | None
    has_picture: bool
    audio_streams: int
    has_video: bool
    # 原片文件找不到（只看在不在）
    missing: bool
    counts: SourceCounts | None


class SourceStream(TypedDict):
    source_id: str
    kind: Literal["audio", "video"]
    ordinal: int
    container_index: int
    codec: str | None
    sample_rate: int | None
    channels: int | None
    bit_depth: int | None
    language: str | None
    title: str | None
    start_time: float | None
    duration: float | None
    is_attached_pic: bool


class SourceDetail(TypedDict):
    id: str
    path: str
    path_key: str | None
    import_root: str | None
    file_snapshot: dict[str, Any] | None
    duration: float
    work: str
    episode: str
    source_type: str
    subtitle_path: str | None
    default_audio_stream: int
    media_state: Literal["available", "released"]
    visual_binding_id: str | None
    root_id: str | None
    rel_path: str | None
    created_at: str
    updated_at: str
    version: int
    actor_kind: str
    actor_session: str | None
    streams: list[SourceStream]


class StreamAssetCreated(TypedDict):
    ordinal: int
    assetId: str | None
    skipped: str | None


class SourcesAddParams(TypedDict):
    paths: list[str]
    importRoot: NotRequired[str | None]


class AddResult(TypedDict):
    path: str
    ok: bool
    sourceId: NotRequired[str]
    existing: NotRequired[bool]
    work: NotRequired[str | None]
    episode: NotRequired[str | None]
    inferRule: NotRequired[int | None]
    inferTimedOut: NotRequired[list[int]]
    assets: NotRequired[list[StreamAssetCreated]]
    error: NotRequired[ErrorWire]


class RelocateParams(TypedDict):
    id: str
    path: str


class SourceRelocated(TypedDict):
    sourceId: str
    path: str
    streamsChanged: bool


class DeletePreview(TypedDict):
    sourceId: str
    path: str
    samples: int
    independentSamples: int
    generatedAssets: int
    # 文本层的段、音效提示、区段标签（所有者 2026-10-09）
    segments: int
    hints: int
    rangeTags: int
    oped: int
    activeJobs: list[str]


class PrepAsset(TypedDict):
    id: str
    origin: str
    streamOrdinal: int | None
    stem: str | None
    model: str | None


class PrepSubtitle(TypedDict):
    ok: bool
    markers: int
    associated: bool


class PrepTrack(TypedDict):
    ok: bool
    asset: PrepAsset | None


class PrepCount(TypedDict):
    ok: bool
    count: int


class PrepSpeech(TypedDict):
    ok: bool
    # 句（文本单元）：原片入口范围内的台词行（默认人声轨或原混音上）与语音采样自己的那一句；analyzed = 有成功的当前头
    speech: int
    analyzed: int


class Prep(TypedDict):
    """准备清单的现状（UI_PLAN §4；没有顺序、不强制）。"""

    speech: PrepSpeech
    subtitle: PrepSubtitle
    separation: PrepTrack
    defaultVocal: PrepTrack
    defaultSfx: PrepTrack
    oped: PrepCount
    lineSamples: PrepCount


class SamplesCreated(TypedDict):
    created: int
    ids: list[str]


# ---------------------------------------------------------------- 原片文件夹与作品（阶段 3.13）


class SourceRoot(TypedDict):
    id: str
    path: str
    online: bool
    sources: int
    works: int


class WorkFolder(TypedDict):
    """作品文件夹：原片文件夹的第一层子文件夹。"""

    id: str
    rootId: str
    name: str
    sourceType: str
    bindPictures: bool
    version: int
    path: str
    sources: int


class PathParams(TypedDict):
    path: str


class RootAdded(TypedDict):
    id: str
    adopted: int
    job: JobRef | None


class RootRemoved(TypedDict):
    released: int


class RootRelocated(TypedDict):
    moved: int
    job: JobRef | None


class WorkRenameParams(TypedDict):
    id: str
    name: str


class WorkRenamed(TypedDict):
    renamed: int


class WorkSettingsParams(TypedDict):
    id: str
    sourceType: NotRequired[str]
    bindPictures: NotRequired[bool]


# ---------------------------------------------------------------- 导入（06 §6.6、所有者 2026-10-07）


class PathsParams(TypedDict):
    paths: list[str]


class PathError(TypedDict):
    path: str
    error: ErrorWire


class ImportConflict(TypedDict):
    path: str
    picture: str
    others: list[str]


class ImportPreview(TypedDict):
    total: int
    importable: int
    videos: int
    existing: int
    withPicture: int
    withoutPicture: int
    unreadable: list[PathError]
    conflicts: list[ImportConflict]
    roots: list[str]
    # 按文件名推断时的分组：[作品, 个数]，"" = 未指定作品（只算新文件）
    inferredGroups: list[tuple[str, int]]
    # “统一设为”的预填：新文件推断出同一个作品就用它，否则唯一的文件夹名
    suggestedWork: str


class ImportCommitParams(TypedDict):
    jobId: str
    # unified = 统一设为 work；infer = 按文件名推断
    workMode: NotRequired[Literal["unified", "infer"]]
    work: NotRequired[str | None]
    sourceType: NotRequired[str | None]
    wholeSample: NotRequired[bool]
    nature: NotRequired[str]
    bindPictures: NotRequired[bool]


class ImportResult(TypedDict):
    created: int
    existing: int
    failed: list[PathError]
    sourceIds: list[str]
    sampleIds: list[str]


# ---------------------------------------------------------------- 声音资产、默认轨、播放（04 §4.2、05 §5.4）


AssetOrigin = Literal["stream", "separation", "flatten", "reimport"]


class AssetRecord(TypedDict):
    id: str
    source_id: str
    origin: AssetOrigin
    media_file_id: str | None
    stream_ordinal: int | None
    duration: float
    # 资产局部秒 ↔ 原片秒的分段映射 [[局部, 原片], …]
    mapping: list[list[float]]
    input_asset_id: str | None
    input_start: float | None
    input_end: float | None
    stem_name: str | None
    production: dict[str, Any] | None
    language: str | None
    created_at: str
    version: int
    updated_at: str | None
    actor_kind: str
    actor_session: str | None
    roles: list[Role]


class AssetInfo(AssetRecord):
    isFullTrack: bool


class TrackRow(TypedDict):
    id: str
    origin: AssetOrigin
    streamOrdinal: int | None
    stemName: str | None
    production: dict[str, Any] | None
    language: str | None
    isFullTrack: bool
    roles: list[Role]
    version: int
    duplicates: int


class Tracks(TypedDict):
    sourceVersion: int
    # 角色 → 默认轨资产 ID
    defaults: dict[str, str]
    tracks: list[TrackRow]


class ResolveSourceParams(TypedDict):
    sourceId: str
    ordinal: NotRequired[int | None]
    assetId: NotRequired[str | None]


class SourceHandle(TypedDict):
    path: str
    # mpv 的音轨号（音频流序号 + 1；外挂声部排在容器音轨之后）
    aid: int
    duration: float
    hasVideo: bool
    audioFile: str | None
    # 外挂声部的音频延迟 = 原片秒 − 局部秒
    audioDelay: float
    # 这条音源覆盖的原片秒范围
    coverage: list[float]


class AssetRangeParams(TypedDict):
    assetId: str
    start: float
    end: float


class AssetHandle(TypedDict):
    path: str
    aid: int
    fileStart: float
    fileEnd: float
    localStart: float
    localEnd: float


class RegisterStemParams(TypedDict):
    sourceId: str
    path: str


class StemRegistered(TypedDict):
    assetId: str
    stem: str
    model: str


class PeaksParams(TypedDict):
    assetId: str
    start: float
    end: float
    points: NotRequired[int]


class Peaks(TypedDict):
    """波形峰值；``min``/``max`` 是 float32 小端序列。``start`` 为资产局部秒。"""

    state: Literal["ready", "pending"]
    start: NotRequired[float]
    step: NotRequired[float]
    min: NotRequired[bytes]
    max: NotRequired[bytes]
    count: NotRequired[int]


ThumbKind = Literal["source", "sample"]
# list = 列表行（88×50 / 56×32）；poster = 查看器的画面（320×180）
ThumbSize = Literal["list", "poster"]


class ThumbRequest(TypedDict):
    kind: ThumbKind
    id: str
    size: NotRequired[ThumbSize]


class ThumbsParams(TypedDict):
    items: list[ThumbRequest]


class ThumbResult(TypedDict):
    kind: ThumbKind
    id: str
    size: ThumbSize
    state: Literal["ready", "pending", "none", "failed"]
    data: NotRequired[bytes]


# ---------------------------------------------------------------- 采样（04 §4.2.6、§4.7）


class EffectiveTag(TypedDict):
    tag: str
    facet: Literal["work", "type", "person", "pitch", "other"]
    provenance: Literal["local", "source", "segment", "auto"]
    ref: str | None


class SampleRow(TypedDict):
    id: str
    asset_id: str
    # 资产局部秒
    start: float
    end: float
    duration: float
    name: str
    nature: Nature
    starred: bool
    rating: int | None
    language: str | None
    created_via: str
    parent_sample_id: str | None
    parent_label: str | None
    created_at: str
    version: int
    source_id: str
    asset_origin: str
    stream_ordinal: int | None
    work: str
    episode: str
    source_name: str
    source_path: str
    # 起点的原片秒（映射坏了为 null）
    source_start: float | None
    media_state: str
    # 人物（说话人显示层：character: 在前，participants: 在后，只显示名字）
    people: list[str]
    # 语音分析（判定区间读到的段）：ok / manual 有人工版本 / partial 有被裁掉一部分的音素（◐）/ stale 段改过待重新分析 / incomplete 有的段还没分析 / failed 只有失败 / none 没有可用分析或没读到段
    analysis: Literal["ok", "manual", "partial", "stale", "incomplete", "failed", "none"]
    # 有效标签（只有 samples.get 返回）
    tags: NotRequired[list[EffectiveTag]]


class SamplePage(TypedDict):
    total: int
    offset: int
    rows: list[SampleRow]


class MetricCond(TypedDict):
    metric: str  # 指标名（algo/acoustic.ALL）
    min: NotRequired[float | None]
    max: NotRequired[float | None]


class MetricFilter(TypedDict):
    """单音 · 音色 / 瞬态的即时筛选（10 §10.3）：缺少所选指标的采样不命中。"""

    mode: Literal["timbre", "transient"]
    conditions: list[MetricCond]


Facet = Literal["work", "type", "person", "pitch", "other"]


class FacetCondition(TypedDict):
    facet: Facet
    # 同一分面多个值取并集；“其他”分面的值是完整标签，其余是冒号后的值
    values: list[str]
    # 人物分面：只要单人（只匹配 character:）
    single: NotRequired[bool]


class TagScope(TypedDict):
    """范围行的标签条件（也是保存筛选器的内容，Q16）：分面条件 + 可选的标签表达式。"""

    facets: NotRequired[list[FacetCondition]]
    expr: NotRequired[str]


class SampleFilter(TypedDict):
    natures: NotRequired[list[str] | None]
    starred: NotRequired[bool | None]
    text: NotRequired[str]
    sourceId: NotRequired[str | None]
    metrics: NotRequired[MetricFilter | None]
    # 范围行（标签条件）与查找栏的主标签表达式（07 §7.2–§7.3；UI_PLAN §2.3）
    tags: NotRequired[TagScope | None]
    expr: NotRequired[str]
    languages: NotRequired[list[str] | None]


class SavedFilter(TypedDict):
    id: str
    name: str
    conditions: TagScope
    sortOrder: int
    version: int


class FacetValue(TypedDict):
    value: str
    count: int
    # 人物分面：其中单人（character:）的采样数
    single: NotRequired[int]


class FacetValues(TypedDict):
    work: list[FacetValue]
    type: list[FacetValue]
    person: list[FacetValue]
    pitch: list[FacetValue]
    other: list[FacetValue]


class SamplesListParams(SampleFilter):
    offset: NotRequired[int]
    limit: NotRequired[int]
    sort: NotRequired[Literal["created", "name", "source", "duration"]]


class SuggestParams(TypedDict):
    assetId: str
    start: float
    end: float
    # 本地标记（“本地”这类文字由界面按语言给出）
    localMarker: NotRequired[str]


class SampleSuggestion(TypedDict):
    name: str
    nature: Nature
    roles: list[Role]
    start: float
    end: float


class SampleCreateParams(TypedDict):
    """单条选区建采样（与统一建采样动作同一套规则）。时间：资产局部秒。"""

    assetId: str
    start: float
    end: float
    name: NotRequired[str | None]
    nature: NotRequired[str | None]
    parentSampleId: NotRequired[str | None]
    via: NotRequired[Literal["manual", "hit"]]


class SamplePlanSource(TypedDict):
    """建采样的来源（所有者 2026-10-09：一个动作，单条与批量同一套规则）。

    selection：assetId + start/end（资产局部秒），可带 parentSampleId（详情里截取子采样）、via（hit = 命中保存）、localMarker；
    segments / hints：sourceId + 可选 ids（不给 = 全部）+ track（default 默认人声 / 音效轨；current 当前查看的轨 assetId）+ 可选 start/end（原片秒过滤）；
    stem：assetId（整条分离声部）；whole：sourceIds（整段原片）。"""

    kind: Literal["selection", "segments", "hints", "stem", "whole"]
    assetId: NotRequired[str | None]
    start: NotRequired[float | None]
    end: NotRequired[float | None]
    parentSampleId: NotRequired[str | None]
    via: NotRequired[Literal["manual", "hit"]]
    localMarker: NotRequired[str]
    sourceId: NotRequired[str]
    ids: NotRequired[list[str] | None]
    track: NotRequired[Literal["default", "current"]]
    sourceIds: NotRequired[list[str]]


# 键名 from 是 Python 保留字，用函数式写法（Python 里取 p["from"]）
SamplePlanParams = TypedDict("SamplePlanParams", {"from": SamplePlanSource})


class SamplePlanItem(TypedDict):
    key: str
    assetId: str | None
    # 资产局部秒
    start: float
    end: float
    # 判定区间（原片秒；决定标签继承与读哪些段）
    judgeStart: float | None
    judgeEnd: float | None
    name: str
    nature: Nature
    createdVia: str
    origin: dict[str, Any] | None
    snapshot: dict[str, Any] | None
    status: Literal["pending", "oped", "out-of-track", "no-name"]
    parentSampleId: str | None
    # 段 / 音效提示来源：原片秒与说话人
    sourceStart: NotRequired[float]
    sourceEnd: NotRequired[float]
    speakers: NotRequired[list[str]]


class SamplePlanTrack(TypedDict):
    assetId: str
    roles: list[Role]


class SamplePlan(TypedDict):
    kind: str
    token: str
    items: list[SamplePlanItem]
    track: SamplePlanTrack | None
    # 默认轨缺失（vocal / sfx）：就地指定，不回退混音
    missingDefault: Role | None
    pads: list[float] | None


class SampleOverride(TypedDict):
    name: NotRequired[str]
    nature: NotRequired[str]


SampleCreatePlannedParams = TypedDict(
    "SampleCreatePlannedParams",
    {"from": SamplePlanSource, "token": str, "keys": list[str], "overrides": NotRequired[dict[str, SampleOverride] | None], "nature": NotRequired[str | None]},
)


class Deleted(TypedDict):
    deleted: int


class ExportSamplesParams(TypedDict):
    ids: list[str]
    # 导出文件名里的固定词（按语言由界面给出）
    words: NotRequired[dict[str, str]]
    # 拖出跟随最近一次成功试听的版本（12 §12.1）：采样 ID → original / stretched；没给 = 原声
    versions: NotRequired[dict[str, Literal["original", "stretched"]] | None]


class ExportWavParams(TypedDict):
    assetId: str
    start: float
    end: float
    content: str
    track: str
    localPrefix: NotRequired[str | None]
    processing: NotRequired[str]
    directory: NotRequired[str | None]


class ExportRangeParams(TypedDict):
    """时间：资产局部秒。words：导出文件名的固定词（音轨名、flatten、fragment「 · 片段」、local「局部」），随界面语言。"""

    assetId: str
    start: float
    end: float
    words: NotRequired[dict[str, str]]


class ExportedWav(TypedDict):
    path: str
    reused: bool
    key: str


class PromoteParams(TypedDict):
    sampleId: str
    tags: list[str]
    role: NotRequired[str | None]
    start: NotRequired[float | None]
    end: NotRequired[float | None]


class PromoteInfo(TypedDict):
    """本地标签提升为区段标签（R5.6）：编辑批次与它的作用域；不写库。"""

    batch: EditBatch
    scope: Literal["role", "asset"]
    role: Role | None
    roles: list[Role]
    assetId: str
    start: float
    end: float


# ---------------------------------------------------------------- 字幕标记、标注、OP/ED（规格 06、05 §5.6）


class SubtitleProblem(TypedDict):
    line: int
    reason: str


class Classified(TypedDict):
    kind: Literal["line", "sfx"]
    name: str
    speakers: list[str]
    alignText: str


class RuleTestParams(TypedDict):
    text: str
    # 草稿规则（未保存）；缺省用当前设置
    rules: NotRequired[dict[str, Any] | None]


class SubtitleImportOptions(TypedDict):
    """导入选项：四类开关（默认全开）、全局替换或保留（默认替换）、逐行不勾 / 强制替换、OP/ED 逐对确认（规则有错时）。"""

    segments: NotRequired[bool]
    hints: NotRequired[bool]
    speakers: NotRequired[bool]
    oped: NotRequired[bool]
    replace: NotRequired[bool]
    exclude: NotRequired[list[int]]
    force: NotRequired[list[int]]
    opedForce: NotRequired[list[int]]
    opedConfirm: NotRequired[list[dict[str, Any]]]


class SubtitleConflict(TypedDict):
    id: str
    start: float
    end: float
    text: str
    protected: bool
    edited: bool
    manual: bool
    analyzed: bool
    usedBy: int


SubtitleStatus = Literal["new", "unchanged", "replace", "skip", "excluded", "invalid"]


class SubtitleRow(TypedDict):
    no: int
    ref: str
    # 原片秒
    start: float
    end: float
    raw: str
    # 段文本（= 对齐文本）或音效提示文字
    text: str
    speakers: list[str]
    status: SubtitleStatus
    reason: str | None
    conflicts: list[SubtitleConflict]
    forced: bool
    same: NotRequired[str]


class SubtitlePairRow(TypedDict):
    index: int
    start: float
    end: float
    suggest: Literal["OP", "ED"]
    kind: Literal["OP", "ED"]
    refs: list[str]
    text: str
    status: SubtitleStatus
    reason: str | None
    conflicts: list[SubtitleConflict]
    forced: bool
    same: NotRequired[str]


class SubtitleOped(TypedDict):
    pairs: list[SubtitlePairRow]
    errors: list[dict[str, Any]]


class SubtitleCategoryCounts(TypedDict):
    new: int
    unchanged: int
    replace: int
    skip: int
    excluded: int
    invalid: int
    # 将被替换（软删除）的已有对象数；其中有分析结果（要重新分析）的、受保护的
    removed: int
    removedAnalyzed: int
    removedProtected: int


class SubtitleCounts(TypedDict):
    segments: SubtitleCategoryCounts
    hints: SubtitleCategoryCounts
    oped: SubtitleCategoryCounts


class SubtitleSpeaker(TypedDict):
    name: str
    count: int


class SubtitleRemoved(TypedDict):
    segments: list[SubtitleConflict]
    hints: list[SubtitleConflict]
    oped: list[SubtitleConflict]


class SubtitlePreviewParams(TypedDict):
    sourceId: str
    path: NotRequired[str | None]
    options: NotRequired[SubtitleImportOptions | None]


class SubtitlePreview(TypedDict):
    sourceId: str
    path: str
    fileName: str
    format: str
    fingerprint: str
    token: str
    options: dict[str, bool]
    segments: list[SubtitleRow]
    hints: list[SubtitleRow]
    speakers: list[SubtitleSpeaker]
    oped: SubtitleOped
    counts: SubtitleCounts
    removed: SubtitleRemoved
    problems: list[SubtitleProblem]


class SubtitleImportParams(TypedDict):
    sourceId: str
    token: str
    options: NotRequired[SubtitleImportOptions | None]
    path: NotRequired[str | None]


class SubtitleInvalidLine(TypedDict):
    no: int
    ref: str
    reason: str


class SubtitleCreated(TypedDict):
    segments: int
    hints: int
    oped: int


class SubtitleImportResult(TypedDict):
    sourceId: str
    editId: str | None
    created: SubtitleCreated
    counts: SubtitleCounts
    invalid: list[SubtitleInvalidLine]
    opedErrors: int
    problems: list[SubtitleProblem]


class SubtitleBatchRow(TypedDict):
    """批量预览的一行：没关联字幕（skipped）、出错（error）或可导入（其余键，默认选项）。"""

    sourceId: str
    skipped: NotRequired[Literal["no-subtitle"]]
    error: NotRequired[ErrorWire]
    fileName: NotRequired[str]
    token: NotRequired[str]
    counts: NotRequired[SubtitleCounts]
    problems: NotRequired[int]
    opedErrors: NotRequired[int]


class SubtitleImportItem(TypedDict):
    sourceId: str
    token: str


class SubtitleImportManyParams(TypedDict):
    items: list[SubtitleImportItem]


class SubtitleImportManyRow(TypedDict):
    """批量导入的一行：出错时只有 sourceId + error，否则同 SubtitleImportResult。"""

    sourceId: str
    error: NotRequired[ErrorWire]
    editId: NotRequired[str | None]
    created: NotRequired[SubtitleCreated]
    counts: NotRequired[SubtitleCounts]
    invalid: NotRequired[list[SubtitleInvalidLine]]
    opedErrors: NotRequired[int]
    problems: NotRequired[list[SubtitleProblem]]


class TextSegment(TypedDict):
    """文本层的一段（原片秒）：文本 = 对齐文本；受保护 = 改过（edited）或有人工音素版本（manual）。"""

    id: str
    version: int
    ordinal: int
    start: float
    end: float
    text: str
    speakers: list[str]
    origin: Literal["subtitle", "typed"]
    edited: bool
    speakerEdited: bool
    manual: bool
    protected: bool
    # 读这一段的采样数（P13：“这段被 N 个采样使用”）
    usedBy: int
    raw: str | None
    oped: Literal["OP", "ED"] | None
    # 给了 assetId 时：这段在那条资产上的分析状态
    analysis: Literal["ok", "stale", "failed", "none"] | None


class SfxHint(TypedDict):
    id: str
    version: int
    start: float
    end: float
    text: str
    origin: Literal["subtitle", "manual"]
    edited: bool
    protected: bool
    oped: Literal["OP", "ED"] | None


class RangeTagRow(TypedDict):
    id: str
    version: int
    scope: Literal["source", "role", "asset"]
    scopeRole: Role | None
    scopeAssetId: str | None
    # 原片 / 角色作用域：原片秒；资产作用域：资产局部秒
    start: float
    end: float
    label: str
    tags: list[str]


class TextLayerParams(TypedDict):
    sourceId: str
    assetId: NotRequired[str | None]


class SegmentRangeParams(TypedDict):
    sourceId: str
    start: float
    end: float


class SegmentConflict(TypedDict):
    id: str
    start: float
    end: float
    text: str


class SegmentAddCheck(TypedDict):
    conflicts: list[SegmentConflict]
    canCut: bool


class SegmentAddParams(TypedDict):
    sourceId: str
    start: float
    end: float
    text: str
    resolve: NotRequired[Literal["replace", "cut"] | None]


class SegmentAdded(TypedDict):
    id: str | None
    editId: str | None


class SegmentSplitParams(TypedDict):
    id: str
    version: int
    # 原片秒
    at: float
    left: str
    right: str


class SegmentsSplit(TypedDict):
    ids: list[str]
    editId: str | None


class SegmentMergeParams(TypedDict):
    ids: list[str]
    text: NotRequired[str | None]


class SpeakersRegenerated(TypedDict):
    changed: int
    editId: str | None


class HintAddParams(TypedDict):
    sourceId: str
    start: float
    end: float
    text: str


class OpedRange(TypedDict):
    id: str
    version: int
    kind: Literal["OP", "ED"]
    start: float
    end: float


class DerivedSample(TypedDict):
    """派生采样车道（R7.6）：起止为原片秒。"""

    id: str
    name: str
    nature: Nature
    assetId: str
    start: float
    end: float


class TextLayerList(TypedDict):
    segments: list[TextSegment]
    hints: list[SfxHint]
    tags: list[RangeTagRow]
    opeds: list[OpedRange]
    derived: list[DerivedSample]


class Oped(TypedDict):
    id: str
    kind: Literal["OP", "ED"]
    start: float
    end: float
    via: Literal["rule", "confirm", "mark"]
    version: int


class OpedPair(TypedDict):
    start: float
    end: float
    suggest: Literal["OP", "ED"]
    refs: list[str]
    overlaps: str | None


class OpedRuleError(TypedDict):
    code: str
    refs: list[str]
    count: NotRequired[int]


class IdentifyResult(TypedDict):
    sourceId: str
    pairs: list[OpedPair]
    errors: list[OpedRuleError]
    applied: int
    skippedOverlap: int


class IdentifyManyRow(TypedDict):
    """批量识别的一行：出错时只有 sourceId + error，否则同 IdentifyResult。"""

    sourceId: str
    error: NotRequired[ErrorWire]
    pairs: NotRequired[list[OpedPair]]
    errors: NotRequired[list[OpedRuleError]]
    applied: NotRequired[int]
    skippedOverlap: NotRequired[int]


class OpedAddParams(TypedDict):
    sourceId: str
    kind: str
    start: float
    end: float
    via: NotRequired[str]
    refs: NotRequired[list[str] | None]


class OpedAdded(TypedDict):
    id: str
    editId: str


class EditRef(TypedDict):
    editId: str


# ---------------------------------------------------------------- 分离（PyMSS Studio，14 §14.6）


class StudioEnv(TypedDict):
    app: str
    resources: str
    worker: str
    data_dir: str
    runtime_file: str
    python: str
    model_dir: str
    version: str | None


class StudioModel(TypedDict):
    name: str
    aliases: list[str]
    stems: list[str]
    category: Any
    vocal: bool
    threeTrack: bool
    files: list[str]


class StudioStatus(TypedDict):
    """``ok`` 为假时只有 ``error``。"""

    ok: bool
    error: NotRequired[ErrorWire]
    env: NotRequired[StudioEnv]
    # 模型列表；还没列出来时为 null，并给出列模型任务
    models: NotRequired[list[StudioModel] | None]
    listingJob: NotRequired[str | None]


class SeparationSubmitParams(TypedDict):
    assetId: str
    start: NotRequired[float | None]
    end: NotRequired[float | None]
    model: str
    stems: NotRequired[list[str] | None]


class SeparationSubmitted(TypedDict):
    """同输入同模型已有结果时只返回 ``reused``（各声部资产 ID），否则返回任务。"""

    reused: NotRequired[list[str]]
    job: NotRequired[JobSummary]


# ---------------------------------------------------------------- 语音分析（规格 08 §8.4）


class SpeechPlanParams(TypedDict):
    # 分析的是“文本层的段 + 具体那条资产”（所有者 2026-10-09）。source = 所选原片的段（不在 OP/ED 里）；segments = 这几段；
    # samples = 各采样判定区间读到的段（在采样所在的资产上）；units = 指定的“段 + 资产”（结果表里再发起失败项）
    entry: Literal["source", "segments", "samples", "units"]
    ids: list[str]
    # 也重新分析已是最新的（排查用，默认不勾）
    rerunFresh: NotRequired[bool]
    # source / segments：用哪条轨（当前查看的轨）；不给 = 默认人声轨（没有就是原混音）
    assetId: NotRequired[str | None]


class SpeechBlocked(TypedDict):
    id: str
    name: str
    reason: str


class SpeechPreview(TypedDict):
    """确认框：将分析 M 条；N 条已是最新，跳过；K 条无法处理（原因）。"""

    run: int
    fresh: int
    blocked: int
    blockedList: list[SpeechBlocked]
    # 范围内绑在原混音或无角色资产上的采样数（提示：想用人声分析先分离、设默认人声轨）
    mixBound: int
    # 不勾「也重新分析」时已是最新的条数（复选框文案用）
    freshAll: int


class SpeechResultRow(TypedDict):
    idx: int
    # 句（文本单元）；旧格式（归属采样）的任务为 null，那时给 sampleId
    unitId: str | None
    sampleId: str | None
    name: str | None
    status: Literal["queued", "ok", "failed", "skipped"]
    error: ErrorWire | None
    deleted: bool


class F0Frames(TypedDict):
    """F0 帧（10 §10.1）：float32 小端序列；没测的帧为 NaN。第 i 帧中心 = t0 + i × step（资产局部秒）。"""

    t0: float
    step: float
    count: int
    f0: bytes
    confidence: bytes
    energy: bytes
    measured: int


class SpeechPhone(TypedDict):
    """一个音素（资产局部秒）。``orig`` = 前端给的原标签（清音 I/U）；``eff`` = 有效范围；``strength`` = 起音强度 0–1。"""

    label: str
    start: float
    end: float
    mora: int | None
    word: int | None
    orig: NotRequired[str]
    eff: NotRequired[list[float]]
    strength: NotRequired[float]
    # 合成结果里：来自读到的第几段（units 的序号）；被采样范围裁掉一部分的非停顿音素（◐）
    seg: NotRequired[int]
    clipped: NotRequired[bool]


class SpeechWord(TypedDict):
    text: str
    start: int | None
    end: int | None
    reading: str
    mapped: bool
    moraStart: int


class SpeechResult(TypedDict):
    phones: list[SpeechPhone]
    morae: list[str]
    words: list[SpeechWord]
    frontend: dict[str, Any]
    aligner: NotRequired[dict[str, Any]]
    derived: NotRequired[dict[str, Any]]
    window: NotRequired[list[float]]


class SpeechHead(TypedDict):
    runId: str
    version: int
    status: str
    manual: bool
    createdAt: str
    text: str | None
    textSource: str | None
    window: list[float] | None
    result: SpeechResult | None
    # 采样读到的句（合成的头才有）；partial = 没有自己文本的采样只读到某句的一部分（◐）
    units: NotRequired[list[str]]
    partial: NotRequired[bool]


class SpeechRun(TypedDict):
    id: str
    status: Literal["ok", "failed", "cancelled", "stale"]
    manual: bool
    createdAt: str
    error: ErrorWire | None
    text: str | None
    # 这个版本对应的段内容与段现在一致（不一致 = 段改过，停用）
    matches: NotRequired[bool]


class SpeechUnit(TypedDict):
    """采样读到的一段在采样所在资产上的分析。人工修正改的是“这段在这条轨上”的分析，所有读到它的采样同时生效。"""

    unitId: str
    segmentId: str
    # 段在文本层里的序号（读取时按存活段的起点排出）
    ordinal: int
    name: str
    text: str
    speakers: list[str]
    # 资产局部秒；段不在这条轨的范围里时为 null
    target: list[float] | None
    # ok 可用 / stale 段改过待重新分析 / failed 只有失败记录 / none 还没分析 / other-sound 文件内容变了
    state: Literal["ok", "stale", "failed", "none", "other-sound"]
    # 可用分析的音素跨度超出采样范围（◐）
    partial: bool
    # 可用的分析（内容与段一致；音素不裁剪）
    head: SpeechHead | None
    # 实际的当前头（可能已停用）
    current: SpeechHead | None
    headVersion: int
    runs: list[SpeechRun]


class SpeechConflict(TypedDict):
    # 两段的序号，交叠区间（原片秒）
    a: int
    b: int
    start: float
    end: float
    units: list[str]


class SpeechReadBlock(TypedDict):
    """节奏分析不可用的原因（错误码 + 参数）：rhythm-segments-missing / rhythm-segment-stale / rhythm-units-conflict。"""

    code: str
    args: dict[str, Any]


class SpeechSampleView(TypedDict):
    sampleId: str
    # 判定区间（原片秒）；judgeLocal = 同一区间换到采样所在资产的局部秒（舞台上显示、编辑用）
    judge: list[float] | None
    judgeLocal: list[float] | None
    # 读到的段的文本连起来；没读到段时给 reason：no-text
    text: str | None
    textSource: str | None
    reason: str | None
    # 读到的段合成的结果（音素裁到采样范围）；任何一段不可用或冲突时为 null
    head: SpeechHead | None
    conflict: SpeechConflict | None
    blocked: SpeechReadBlock | None
    units: list[SpeechUnit]


class AlignedPhone(TypedDict):
    label: str
    start: float
    end: float


class AssetAlignment(TypedDict):
    unitId: str
    segmentId: str
    ordinal: int
    name: str
    runId: str
    manual: bool
    phones: list[AlignedPhone]


class ManualPhone(TypedDict):
    label: str
    start: float
    end: float


class SpeechManualParams(TypedDict):
    # 改的是这句（文本单元）：所有读这句的采样和原片页音素层同时生效
    unitId: str
    # 读到的当前头版本（乐观并发）
    version: int
    phones: NotRequired[list[ManualPhone] | None]
    # 精确时间文本（每行 开始秒 Tab 结束秒 Tab 音素），给了就用它
    text: NotRequired[str | None]


class SpeechSwitchParams(TypedDict):
    unitId: str
    runId: str
    version: int


class SpeechHeadRef(TypedDict):
    runId: str
    version: int


# ---------------------------------------------------------------- 拉平（规格 11）

FlattenRange = Literal["whole", "vowels", "first", "inner"]
FlattenTargetMethod = Literal["auto", "edge", "manual"]
FlattenSide = Literal["left", "right"]


class FlattenToken(TypedDict):
    """打开拉平台时冻结的音源与外选区（资产局部秒）和存放它的文件快照（指纹字符串）；提交时核对。"""

    assetId: str
    start: float
    end: float
    media: str
    snapshot: str


class FlattenOpenParams(TypedDict):
    assetId: str
    start: float
    end: float
    # detail = 采样详情（舞台）；single = 其他单个入口；batch 不用打开
    entry: Literal["detail", "single", "batch"]
    sampleId: NotRequired[str | None]


class FlattenDefaults(TypedDict):
    range: FlattenRange
    target: FlattenTargetMethod
    side: FlattenSide


class FlattenPhone(TypedDict):
    """输入局部秒（外选区起点 = 0）。"""

    label: str
    start: float
    end: float


class FlattenAlignment(TypedDict):
    manual: bool
    runId: str
    phones: list[FlattenPhone]


class FlattenOpened(TypedDict):
    token: FlattenToken
    duration: float
    defaults: FlattenDefaults
    alignment: FlattenAlignment | None
    name: str
    # 内部拉平的初始内区（输入局部秒）与默认过渡
    inner: list[float]
    transition: float


class FlattenOptions(TypedDict):
    range: FlattenRange
    target: FlattenTargetMethod
    side: NotRequired[FlattenSide | None]
    manual: NotRequired[str | None]
    # 输入局部秒
    inner: NotRequired[list[float] | None]
    transition: NotRequired[list[float] | None]


class FlattenTarget(TypedDict):
    midi: float
    name: str
    hz: float
    method: str
    originalMidi: float | None
    shiftSemitones: float | None
    ref: list[float] | None
    side: str | None


class FlattenEstimateParams(TypedDict):
    token: FlattenToken
    options: FlattenOptions
    sampleId: NotRequired[str | None]


class FlattenEstimate(TypedDict):
    # ok = 缓存预估；in-job = 没有缓存的音高，任务中确定；insufficient = 缓存里证据不足（error 说明）
    status: Literal["ok", "in-job", "insufficient"]
    target: FlattenTarget | None
    intervals: list[list[float]]
    error: NotRequired[ErrorWire]


class FlattenSubmitParams(TypedDict):
    token: FlattenToken
    options: FlattenOptions
    name: str
    sampleId: NotRequired[str | None]


class FlattenBatchParams(TypedDict):
    ids: list[str]
    options: FlattenOptions


class FlattenResultRow(TypedDict):
    idx: int
    sampleId: str | None
    name: str | None
    deleted: bool
    status: Literal["queued", "ok", "failed", "skipped"]
    error: ErrorWire | None
    # 成品采样与目标音名（成功时）
    productId: str | None
    target: str | None


# ---------------------------------------------------------------- 节奏与卡拍（阶段 6；规格 09 §9.2–§9.5）

RhythmPlan = Literal["near_fast", "near_slow", "double"]
RhythmSound = Literal["voice", "voice+click", "click"]


class BpmParams(TypedDict):
    # 20–400；null = 原速卡拍
    bpm: float | None


class Bpm(TypedDict):
    bpm: float | None


class RhythmViewParams(TypedDict):
    id: str
    # 临时用纯 mora（所有者 2026-10-08：只作临时试听与临时导出，不保存）与长音补格
    mora: NotRequired[bool | None]
    longVowel: NotRequired[bool | None]


class RhythmParamsState(TypedDict):
    sensitivity: float
    segmentThreshold: float


class RhythmManual(TypedDict):
    # 人工项绑定的分析版本；applied = 与当前分析一致并已套用；stale = 属于旧的分析版本（未套用）；ignored = 序号越界没有套用的项
    run: str | None
    splits: list[int]
    cells: dict[str, int]
    cuts: list[int]
    merges: list[int]
    applied: bool
    stale: bool
    ignored: list[str]


class RhythmPhone(TypedDict):
    """采样范围内的音素（资产局部秒）；拆点“在第 k 个音素之前”按这里的序号。"""

    label: str
    start: float
    end: float


class RhythmCut(TypedDict):
    k: int  # 切在第 k 块之前
    kind: Literal["auto", "manual"]
    at: float  # 左段终点（资产局部秒）
    rightStart: float
    merged: bool


class RhythmBlock(TypedDict):
    """一个音块（资产局部秒）与逐音属性（未知为 null）。"""

    onset: float
    end: float
    vowel: str | None
    text: str
    strength: float | None
    pauseSegment: int
    cells: int
    restCells: int | None
    manual: bool
    duration: float
    rest: float
    firstPhone: int
    midi: float | None
    spreadCents: float | None
    coverage: float | None
    trend: float | None
    loudnessDb: float | None
    consonants: list[str]
    relPitch: float | None
    relLoudness: float | None


class RhythmPoint(TypedDict):
    src: float  # 资产局部秒
    tgt: float  # 卡拍输出的秒
    beat: float
    kind: Literal["onset", "segment-tail", "tail"]


class RhythmScheme(TypedDict):
    density: float  # 每拍格数
    bpm: float  # 原速卡拍时为求出的 BPM
    speed: float  # 语音播放速度（倍速）
    ratio: float
    restCells: list[int]
    sourceSeconds: float
    outSeconds: float
    points: list[RhythmPoint]


class RhythmMora(TypedDict):
    cells: list[int | None]
    available: bool


class RhythmView(TypedDict):
    sampleId: str
    # ok = 有节奏分析；none = 没有语音分析或没有音块（reason 说明）
    status: Literal["ok", "none"]
    reason: ErrorWire | None
    bpm: float | None
    version: int
    run: NotRequired[str]
    # 读到的句（文本单元）；partial = 只读到某句的一部分（◐）
    units: NotRequired[list[str]]
    partial: NotRequired[bool]
    window: NotRequired[list[float]]
    params: NotRequired[RhythmParamsState]
    manual: NotRequired[RhythmManual]
    penalty: NotRequired[float]
    phones: NotRequired[list[RhythmPhone]]
    pauses: NotRequired[list[list[float]]]
    cuts: NotRequired[list[RhythmCut]]
    segments: NotRequired[list[list[float]]]
    tick: NotRequired[float | None]
    alternatives: NotRequired[list[list[int]]]
    mora: NotRequired[RhythmMora]
    cells: NotRequired[list[int]]
    route: NotRequired[Literal["raw", "mora"]]
    routeError: NotRequired[ErrorWire]
    blocks: NotRequired[list[RhythmBlock]]
    schemes: NotRequired[dict[str, RhythmScheme]]
    schemeError: NotRequired[ErrorWire | None]


class RhythmMoraToCells(TypedDict):
    longVowel: bool


class RhythmSetParams(TypedDict):
    id: str
    version: int  # 采样的版本（乐观并发）
    sensitivity: NotRequired[float | None]
    segmentThreshold: NotRequired[float | None]
    splits: NotRequired[list[int] | None]
    cells: NotRequired[dict[str, int | None] | None]
    cuts: NotRequired[list[int] | None]
    merges: NotRequired[list[int] | None]
    # 把当前纯 mora 占格写进人工占格（所有者 2026-10-08）
    moraToCells: NotRequired[RhythmMoraToCells | None]
    clearManual: NotRequired[bool | None]
    reapply: NotRequired[bool | None]


class RhythmEdited(TypedDict):
    editId: str | None


class RhythmRenderParams(TypedDict):
    id: str
    version: Literal["original", "stretched"]
    sound: RhythmSound
    plan: NotRequired[RhythmPlan | None]
    mora: NotRequired[bool | None]
    longVowel: NotRequired[bool | None]


class RhythmRendered(TypedDict):
    key: str
    duration: float
    version: Literal["original", "stretched"]
    sound: RhythmSound
    plan: RhythmPlan | None
    bpm: float | None
    density: float | None
    speed: float | None
    originalSpeed: bool


class RenderKeyParams(TypedDict):
    key: str


class StretchedExportParams(TypedDict):
    """卡拍 WAV（只能完整采样，12 §12.1）。mora / longVowel：舞台上的临时纯 mora（不保存）。"""

    id: str
    words: NotRequired[dict[str, str]]
    plan: NotRequired[RhythmPlan | None]
    mora: NotRequired[bool | None]
    longVowel: NotRequired[bool | None]


class ReaperParams(TypedDict):
    """REAPER 交接（12 §12.3）：多条 = 依次排开、间隔一小节。baked：卡好拍的声音 + 起音拉伸标记 / false = 未烘焙原声 + 卡拍拉伸标记 /
    不给 = 按设置 export.reaper_kind（⌘C 用）。"""

    ids: list[str]
    words: NotRequired[dict[str, str]]
    plan: NotRequired[RhythmPlan | None]
    mora: NotRequired[bool | None]
    longVowel: NotRequired[bool | None]
    baked: NotRequired[bool | None]
    # 检索命中（09 §9.7）：用各自证据所选的方案；给了就只交接这些命中（ids 留空）
    hits: NotRequired[list["HitRefParams"] | None]


class ReaperHandoff(TypedDict):
    # 剪贴板文本（各行 NUL 分隔、末尾两个 NUL）；由主进程写入 REAPERMedia 并回读校验
    clipboard: str
    files: list[str]
    manifest: str
    count: int


class ReaperTemplate(TypedDict):
    path: str
    files: list[str]
    manifest: str
    count: int


# ---------------------------------------------------------------- 三大搜索（阶段 7）


class SearchCoverageParams(TypedDict):
    # pitch = 已保存采样；pitchSources = 已分析原片音轨（整轨测 F0）
    mode: Literal["speech", "pitch", "pitchSources"]
    # 当前浏览范围（与 samples.list 同一套条件）
    scope: NotRequired[SampleFilter | None]


class SearchCoverage(TypedDict):
    """范围的检索准备情况：ready = 可以检索；stale = 要先「准备当前范围索引」；noAnalysis = 没有可用的语音分析（语音检索里计入“缺少有效分析”）。"""

    mode: Literal["speech", "pitch", "pitchSources"]
    total: int
    ready: int
    stale: int
    noAnalysis: int


class SpeechBlockCond(TypedDict):
    """语音检索的一个音块条件（09 §9.6.3）；留空 = 不限。节奏策略下 note 必填。"""

    note: NotRequired[list[float] | None]  # [起拍, 止拍)
    pitch: NotRequired[int | None]  # 音级 0–11（C = 0）
    octave: NotRequired[int | None]
    pitchTolerance: NotRequired[float | None]  # 音分，默认 50
    spreadMax: NotRequired[float | None]  # 音分
    coverageMin: NotRequired[float | None]  # 默认 0.5
    vowel: NotRequired[Literal["a", "i", "u", "e", "o"] | None]
    consonants: NotRequired[list[str] | None]  # [] = 无前导辅音
    duration: NotRequired[list[float | None] | None]  # 原声时值 [下, 上]（秒）
    durationMode: NotRequired[Literal["effective", "span"] | None]
    character: NotRequired[str | None]
    trend: NotRequired[Literal["up", "down"] | None]
    trendThreshold: NotRequired[float | None]
    relPitch: NotRequired[Literal["high", "low"] | None]
    relPitchThreshold: NotRequired[float | None]
    loudnessMin: NotRequired[float | None]
    strengthMin: NotRequired[float | None]
    beats: NotRequired[list[float | None] | None]  # 时值（拍）[下, 上]
    sustain: NotRequired[bool | None]


class SpeechQueryInput(TypedDict):
    blocks: list[SpeechBlockCond]
    strategy: NotRequired[Literal["free", "strict", "rank"] | None]
    edge: NotRequired[Literal["any", "head", "tail", "both"] | None]
    edgeBasis: NotRequired[Literal["pause", "sample"] | None]
    cross: NotRequired[bool | None]
    maxGap: NotRequired[float | None]
    scope: NotRequired[Literal["both", "sentence", "segment"] | None]
    tolerance: NotRequired[float | None]  # 拍
    speedPreference: NotRequired[float | None]
    speedRange: NotRequired[list[float] | None]
    restAdjust: NotRequired[bool | None]
    length: NotRequired[float | None]  # 查询长度（拍）


class SearchSpeechParams(TypedDict):
    query: SpeechQueryInput
    scope: NotRequired[SampleFilter | None]


class PitchBand(TypedDict):
    low: str  # 音名，如 A4、C♯5
    high: NotRequired[str | None]  # 范围上端（闭区间）；留空 = 单个音


class PitchBlockInput(TypedDict):
    seconds: float
    low: str
    high: NotRequired[str | None]
    glide: NotRequired[PitchBand | None]  # 滑音块的终点音带（所有者 2026-10-08）


class PitchParamsInput(TypedDict):
    tolerance: NotRequired[float | None]  # 音分，默认 50
    coverage: NotRequired[float | None]  # 默认 0.8
    maxGap: NotRequired[float | None]  # 秒，默认 0.12
    stability: NotRequired[float | None]
    energyMin: NotRequired[float | None]
    energyMax: NotRequired[float | None]
    ignoreOctave: NotRequired[bool | None]
    elastic: NotRequired[list[float] | None]  # [下限, 上限] 倍
    headTolerance: NotRequired[float | None]  # 原片模式：句首容差（秒）
    tailTolerance: NotRequired[float | None]


class PitchSourceScope(TypedDict):
    natures: NotRequired[list[str] | None]  # 原片模式下给了就拒绝（采样专用）
    starred: NotRequired[bool | None]
    text: NotRequired[str]
    sourceId: NotRequired[str | None]
    roles: NotRequired[list[Literal["vocal", "sfx", "mix"]] | None]


class SearchPitchParams(TypedDict):
    blocks: list[PitchBlockInput]
    params: NotRequired[PitchParamsInput | None]
    mode: Literal["samples", "sources"]
    scope: NotRequired[PitchSourceScope | None]


class PitchCheckParams(TypedDict):
    blocks: NotRequired[list[PitchBlockInput] | None]
    text: NotRequired[str | None]


class PitchProblem(TypedDict):
    block: NotRequired[int | None]  # 块号从 1 起；null = 整条查询
    line: NotRequired[int | None]  # 文本格式的行号
    reason: str
    min: NotRequired[float | None]
    max: NotRequired[float | None]


class PitchChecked(TypedDict):
    """就地提示：problems 为空才能查找。text = 规范的文本格式（复制用）；blocks = 文本解析出的块（粘贴用）。"""

    ok: bool
    problems: list[PitchProblem]
    frames: list[int]
    text: str | None
    blocks: list[PitchBlockInput]


class SearchStarted(TypedDict):
    searchId: str


class SearchIdParams(TypedDict):
    searchId: str


class SearchCancelled(TypedDict):
    searchId: str
    cancelling: bool


class SearchStats(TypedDict):
    total: int  # 范围内的采样（原片模式：音轨）
    searched: int  # 实际检索的（索引就绪）
    noAnalysis: int  # 缺少有效分析
    stale: int  # 索引未就绪（要准备）
    samples: int  # 结果行数
    hits: int
    ms: int  # 后端耗时
    windows: int
    noEvidence: int  # 算不出节奏证据的窗口
    unknownBounds: int  # 句首/句尾条件下没有标注的音轨
    bpm: float | None
    truncated: bool


class SearchFinished(TypedDict):
    """事件 ``search.finished`` 与 ``search.status`` 的内容。status = running / done / cancelled / failed。"""

    searchId: str
    kind: Literal["speech", "pitch"]
    status: Literal["running", "done", "cancelled", "failed"]
    resultId: str | None
    stats: SearchStats | None
    error: ErrorWire | None


class SpeechEvidence(TypedDict):
    strict: bool
    cost: float
    error: float  # 平均起音误差（拍）
    conflicts: int
    deficit: float
    speed: float | None
    density: float | None
    bpm: float | None
    plan: Literal["near_fast", "near_slow"] | None
    scope: int  # -1 整句 / 语段号
    shift: float
    deform: float
    rests: list[int]
    changed: int


class ResultHit(TypedDict):
    """一处命中。语音：start/end 资产局部秒，first/count 是音块；音高：start/end 资产局部秒，frames、octave、ratio、blocks〔每块：帧数, 带内可靠帧, 平均距离（音分）〕，原片模式另有原片秒。"""

    start: float
    end: float
    score: float
    first: NotRequired[int]
    count: NotRequired[int]
    blockScore: NotRequired[float]
    evidence: NotRequired[SpeechEvidence | None]
    frames: NotRequired[int]
    octave: NotRequired[int]
    ratio: NotRequired[float]
    blocks: NotRequired[list[list[float]]]
    sourceStart: NotRequired[float]
    sourceEnd: NotRequired[float]


class ResultHeader(TypedDict):
    id: str
    kind: Literal["speech", "pitch"]
    createdAt: str
    query: Any
    scope: Any
    params: Any
    stats: SearchStats
    uiState: Any


class ResultAsset(TypedDict):
    id: str
    sourceId: str
    stemName: str | None
    origin: str
    work: str
    episode: str
    path: str


class ResultRow(TypedDict):
    """固定结果的一行。state：ok / deleted（采样已删除）/ changed（音源已变化）/ stale（分析或测量变了：命中已失效，请重新查询）。"""

    rank: int
    sampleId: str | None
    assetId: str | None
    sample: SampleRow | None
    asset: ResultAsset | None
    state: Literal["ok", "deleted", "changed", "stale"]
    hits: list[ResultHit]


class ResultPageParams(TypedDict):
    id: str
    offset: NotRequired[int]
    limit: NotRequired[int]


class ResultPage(TypedDict):
    result: ResultHeader
    total: int
    offset: int
    rows: list[ResultRow]


class ResultUiParams(TypedDict):
    id: str
    uiState: Any


class MetricsStatusParams(TypedDict):
    scope: NotRequired[SampleFilter | None]
    metrics: NotRequired[list[str] | None]


class MetricsStatus(TypedDict):
    total: int
    ready: int  # 已准备（有有效指标）
    stale: int  # 未准备（「后台准备当前范围指标」）
    missing: dict[str, int]  # 每个指标：缺失（未准备或未知）的采样数


class MetricsPrepareParams(TypedDict):
    scope: NotRequired[SampleFilter | None]


class HitRefParams(TypedDict):
    """固定结果里的一处命中：结果、行（rank）、行内第几处。"""

    resultId: str
    rank: int
    index: int


class HitInfo(TypedDict):
    """核对过仍有效的命中（资产局部秒）；plan/bpm = 证据所选的方案（不限节奏 = 近快、当前 BPM；音高命中没有卡拍）。"""

    kind: Literal["speech", "pitch"]
    sampleId: str | None
    assetId: str
    start: float
    end: float
    stretch: bool
    plan: RhythmPlan | None
    bpm: float | None
    sourceStart: float | None
    sourceEnd: float | None


class HitRenderParams(HitRefParams):
    version: Literal["original", "stretched"]
    sound: RhythmSound


class HitExportParams(HitRefParams):
    version: Literal["original", "stretched"]
    words: NotRequired[dict[str, str]]

