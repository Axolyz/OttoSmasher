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
    current_subtitle_version_id: str | None
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
    annotations: int
    subtitleVersions: int
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


class WholeSamplesParams(TypedDict):
    ids: list[str]
    # None = 按默认音轨的角色预填
    nature: NotRequired[str | None]


class SampleIds(TypedDict):
    sampleIds: list[str]


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
    # 语音分析：ok 已分析 / manual 人工版本 / failed 分析失败（没有成功结果）/ none 未分析
    analysis: Literal["ok", "manual", "failed", "none"]
    # 有效标签（只有 samples.get 返回）
    tags: NotRequired[list[EffectiveTag]]


class SamplePage(TypedDict):
    total: int
    offset: int
    rows: list[SampleRow]


class SampleFilter(TypedDict):
    natures: NotRequired[list[str] | None]
    starred: NotRequired[bool | None]
    text: NotRequired[str]
    sourceId: NotRequired[str | None]


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
    assetId: str
    start: float
    end: float
    name: str
    nature: NotRequired[str | None]
    createdVia: NotRequired[str]
    parentSampleId: NotRequired[str | None]


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


class SubtitlePreviewLine(TypedDict):
    no: int
    ref: str
    # 原片秒
    start: float
    end: float
    text: str
    kind: Literal["line", "sfx"]
    name: str
    speakers: list[str]
    alignText: str
    status: Literal["importable", "oped", "invalid", "registered"]
    reason: NotRequired[Literal["negative-start", "empty", "beyond-end"]]
    oped: NotRequired[Literal["OP", "ED"]]
    opedPartial: NotRequired[bool]


class SubtitleCounts(TypedDict):
    importable: int
    oped: int
    invalid: int
    registered: int


class SubtitlePreviewParams(TypedDict):
    sourceId: str
    path: NotRequired[str | None]


class SubtitlePreview(TypedDict):
    sourceId: str
    path: str
    fileName: str
    format: str
    fingerprint: str
    token: str
    versionState: Literal["new", "current", "switch"]
    lines: list[SubtitlePreviewLine]
    counts: SubtitleCounts
    problems: list[SubtitleProblem]


class SubtitleImportParams(TypedDict):
    sourceId: str
    token: str
    lines: NotRequired[list[int] | None]
    path: NotRequired[str | None]


class SubtitleSkipped(TypedDict):
    invalid: int
    registered: int


class SubtitleInvalidLine(TypedDict):
    no: int
    ref: str
    reason: str


class SubtitleImportResult(TypedDict):
    sourceId: str
    editId: str | None
    imported: int
    versionId: str
    newVersion: bool
    switched: bool
    skipped: SubtitleSkipped
    invalid: list[SubtitleInvalidLine]
    problems: list[SubtitleProblem]


class SubtitleBatchRow(TypedDict):
    """批量预览的一行：没关联字幕（skipped）、出错（error）或可导入（其余键）。"""

    sourceId: str
    skipped: NotRequired[Literal["no-subtitle"]]
    error: NotRequired[ErrorWire]
    fileName: NotRequired[str]
    token: NotRequired[str]
    versionState: NotRequired[Literal["new", "current", "switch"]]
    counts: NotRequired[SubtitleCounts]
    problems: NotRequired[int]


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
    imported: NotRequired[int]
    versionId: NotRequired[str]
    newVersion: NotRequired[bool]
    switched: NotRequired[bool]
    skipped: NotRequired[SubtitleSkipped]
    invalid: NotRequired[list[SubtitleInvalidLine]]
    problems: NotRequired[list[SubtitleProblem]]


AnnotationKind = Literal["line", "sfx", "song", "tag"]


class AnnotationRow(TypedDict):
    id: str
    version: int
    kind: AnnotationKind
    scope: Literal["source", "role", "asset"]
    scopeRole: Role | None
    # 原片秒
    start: float
    end: float
    text: str
    name: str
    speakers: list[str]
    tags: list[str]
    fromSubtitle: bool
    oped: Literal["OP", "ED"] | None


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


class AnnotationList(TypedDict):
    annotations: list[AnnotationRow]
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


class SubtitleSamplesPreviewParams(TypedDict):
    sourceId: str
    kind: str
    start: NotRequired[float | None]
    end: NotRequired[float | None]


class SubtitleSampleLine(TypedDict):
    annotationId: str
    name: str
    rawText: str
    speakers: list[str]
    # 原片秒
    start: float
    end: float
    sampleStart: float
    sampleEnd: float
    status: Literal["pending", "oped", "out-of-track", "no-name"]




SubtitleSampleCounts = TypedDict("SubtitleSampleCounts", {"pending": int, "oped": int, "out-of-track": int, "no-name": int})


class SubtitleSamplePreview(TypedDict):
    sourceId: str
    kind: Literal["line", "sfx"]
    trackId: str | None
    missingDefault: bool
    # 前后扩展秒数
    pads: tuple[float, float]
    token: str
    lines: list[SubtitleSampleLine]
    counts: SubtitleSampleCounts
    noSubtitles: bool


class SubtitleSamplesCreateParams(TypedDict):
    sourceId: str
    kind: str
    token: str
    annotationIds: list[str]
    start: NotRequired[float | None]
    end: NotRequired[float | None]


class SubtitleSamplesCreated(TypedDict):
    created: int
    ids: list[str]


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
    # source = 原片入口（默认范围：语音、有对齐文本、原字幕区间不在 OP/ED 里）；samples = 所选采样（有对齐文本的）
    entry: Literal["source", "samples"]
    ids: list[str]
    # 也重新分析已是最新的（排查用，默认不勾）
    rerunFresh: NotRequired[bool]


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
    # 资产选区的分析为 null
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
    # 子采样借用的投影：来源测量的归属（采样 ID 或资产选区）；自己的测量为 null
    projectedFrom: str | None


class SpeechRun(TypedDict):
    id: str
    status: Literal["ok", "failed", "cancelled", "stale"]
    manual: bool
    createdAt: str
    error: ErrorWire | None
    text: str | None


class SpeechSampleView(TypedDict):
    sampleId: str
    # 当前会用的对齐文本（没有时给 reason：no-text / range-differs）
    text: str | None
    textSource: str | None
    reason: str | None
    head: SpeechHead | None
    runs: list[SpeechRun]


class AlignedPhone(TypedDict):
    label: str
    start: float
    end: float


class AssetAlignment(TypedDict):
    # 资产选区上的分析（不属于采样）为 null
    sampleId: str | None
    runId: str
    manual: bool
    phones: list[AlignedPhone]


class SpeechRangeParams(TypedDict):
    assetId: str
    start: float
    end: float
    text: str


class ManualPhone(TypedDict):
    label: str
    start: float
    end: float


class SpeechManualParams(TypedDict):
    sampleId: str
    # 读到的当前头版本（乐观并发）
    version: int
    phones: NotRequired[list[ManualPhone] | None]
    # 精确时间文本（每行 开始秒 Tab 结束秒 Tab 音素），给了就用它
    text: NotRequired[str | None]


class SpeechSwitchParams(TypedDict):
    sampleId: str
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
    projectedFrom: NotRequired[str | None]
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
    """REAPER 交接（12 §12.3）：多条 = 依次排开、间隔一小节。baked：卡好拍的声音 + 起音拉伸标记（默认 = 未烘焙原声 + 卡拍拉伸标记）。"""

    ids: list[str]
    words: NotRequired[dict[str, str]]
    plan: NotRequired[RhythmPlan | None]
    mora: NotRequired[bool | None]
    longVowel: NotRequired[bool | None]
    baked: NotRequired[bool | None]


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
