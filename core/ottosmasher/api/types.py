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


class EditHistoryParams(TypedDict):
    session: NotRequired[str | None]
    actorKind: NotRequired[Literal["user", "script", "agent"] | None]
    limit: NotRequired[int]


class EditHistoryActor(TypedDict):
    kind: str
    session: str | None


class EditHistoryItem(TypedDict):
    edit_id: str
    seq: int
    created_at: str
    label: EditLabel
    actor: EditHistoryActor
    # 这条本身是撤销（撤的是哪条）
    undoOf: str | None
    # 已被哪条撤销
    undoneBy: str | None
    changes: int
    # 现在能单独撤销（edits.undoOne）
    undoable: bool


class EditIdParams(TypedDict):
    editId: str


class SessionParams(TypedDict):
    session: str


class EditUndoBlocked(TypedDict):
    edit_id: str
    label: EditLabel


class SessionUndone(TypedDict):
    """整批撤回一个会话：撤了几条；停在哪条（被之后的修改改过）；还剩几条没撤。"""

    undone: int
    blocked: EditUndoBlocked | None
    remaining: int


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


# ---------------------------------------------------------------- 外部连接（命令行 / agent，阶段 A）


class Actor(TypedDict):
    kind: Literal["user", "script", "agent"]
    session: str | None


class AgentSession(TypedDict):
    """一条正在连着的命令行连接。"""

    id: str
    kind: Literal["agent", "script"]
    session: str | None
    connectedAt: str


class AgentConfirmReplyParams(TypedDict):
    id: str
    approve: bool


class AgentConfirmReplied(TypedDict):
    # 提问之后资料变了：没有执行，已带新的影响预览重新问（新的 agent.confirm）
    reasked: NotRequired[bool]


class AgentSkillsParams(TypedDict, total=False):
    """lang = 第一次把内置 skill 复制进工作区时用的语言；之后不再变。"""

    lang: Literal["zh-CN", "en"]


class AgentSkill(TypedDict):
    name: str
    description: str
    path: str
    # 是不是内置的（用户自己加的是 false）
    builtin: bool
    # 旁边有等着合并的新版本的文件（相对 skills 文件夹）
    update: list[str]


class AgentSkills(TypedDict):
    path: str
    playbook: str
    skills: list[AgentSkill]


class AgentMissed(TypedDict):
    """没人及时回答（timeout）或提问的连接断了（closed）的确认请求。"""

    id: str
    method: str
    params: dict[str, Any]
    preview: Any
    actor: Actor
    at: str
    reason: Literal["timeout", "closed"]


class DismissMissedParams(TypedDict):
    ids: NotRequired[list[str] | None]


class AgentConfirm(TypedDict):
    """事件 agent.confirm：外部连接要执行一条撤销不了的命令，等所有者在应用里确认。"""

    id: str
    method: str
    params: dict[str, Any]
    # 影响预览（有对应的预览命令时带上，例如 sources.deletePreview）
    preview: Any
    actor: Actor
    # 等多久算拒绝；0 = 不限时
    seconds: int


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
    # 权重的上游许可（SPDX 写法）与权重总字节数
    license: str
    bytes: int


class ModelsDownloadParams(TypedDict):
    # 只下载这几个模型；不给 = 全部缺少或不符的
    models: NotRequired[list[str]]


class ModelDownloadItem(TypedDict):
    model: str
    url: str
    path: str
    sha256: str
    size: int | None
    # 现在那个位置有一个大小或 SHA 不符的文件，下载会替换它
    replace: bool
    license: str


class ModelDownloadStarted(TypedDict):
    model: str
    job: "JobSummary"


class ModelsImportParams(TypedDict):
    # 用户选的文件或文件夹（文件夹里递归找）
    paths: list[str]


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
    # 正在下载（排队或运行）的模型 → 任务 ID
    downloading: dict[str, str]


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


class SeparationDevice(TypedDict):
    """Frozen PyMSS request, not a claim about the backend selected by auto."""

    requested: Literal["auto", "cpu", "cuda", "mps"] | None
    deviceId: int | None


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
    separationDevice: NotRequired[SeparationDevice]
    retry_of: str | None
    items: JobItems | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    # 自动准备之类的后台任务（排在用户提交的任务后面）
    background: NotRequired[bool]
    # 排队时被提到最前（jobs.promote）
    promoted: NotRequired[bool]
    actor: NotRequired[Actor]


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
    # 已独立化的采样数（媒体已释放的原片里就是留下的采样，规格 04 §4.8）
    independent_samples: int
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
    # 删除后：原片保留为“媒体已释放”（有独立化采样时）与留下的采样数
    released: NotRequired[bool]
    keptSamples: NotRequired[int]


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
    # 读不了的段：最近一次就是按现在的文字分析、因文字读不出音而失败（例如只有“♪”）；不挡这一项完成
    unreadable: int


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
    # 从哪个回导成品来的（回导成品 = 自己；不是回导来的为 null）：音素读“段 + 原素材”还是“段 + 这个回导成品”那一份
    reimport_id: str | None
    # 是不是从分离声部来的（没开任何角色时据此区分“混音”与“没标角色的声部”）
    from_separation: int


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
    createdAt: str


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


class VisualBinding(TypedDict):
    """有效画面（规格 12 §12.4）。origin：sample = 采样自己的绑定，source = 原片的默认画面，stream = 原片自带的视频流。"""

    origin: Literal["sample", "source", "stream"]
    bindingId: str | None
    mode: Literal["sync", "image", "loop", "materialized_clip"]
    # 同步：画面时间 = 原片秒 + offset
    offset: float
    path: str
    kind: str
    ordinal: int
    duration: float | None
    state: Literal["ok", "missing", "changed"]


class SamplePicture(TypedDict):
    binding: VisualBinding | None
    start: float
    end: float
    # 资产映射控制点（本地秒 → 原片秒）
    mapping: list[list[float]] | None


class VisualPrepareParams(TypedDict):
    ownerType: Literal["sample", "source"]
    ownerId: str
    path: str
    mode: NotRequired[Literal["sync", "image", "loop"] | None]
    offset: NotRequired[float]


class VisualBindParams(TypedDict):
    ownerType: Literal["sample", "source"]
    ownerId: str
    # null = 摘下自己的绑定（采样回到原素材的画面）
    path: str | None
    # 缺省按文件：图片 = image、动图 = loop、视频 = sync
    mode: NotRequired[Literal["sync", "image", "loop"] | None]
    # 只对 sync：画面相对原素材 / 采样的偏移秒
    offset: NotRequired[float]


class VisualPrepared(TypedDict):
    bindingId: str


class SourceIdParams(TypedDict):
    sourceId: str


class MatchItem(TypedDict):
    sourceId: str
    picture: str | None
    kind: str | None
    conflicts: list[str]
    hasBinding: bool


class MatchApplyParams(TypedDict):
    items: list[MatchItem]


class SpectrumParams(TypedDict):
    assetId: str
    # 资产局部秒，最多 30 秒
    start: float
    end: float
    cols: int
    rows: int
    scale: Literal["log", "linear", "mel"]


class Spectrum(TypedDict):
    start: float
    end: float
    cols: int
    rows: int
    scale: str
    nyquist: float
    # rows × cols 的 uint8（行优先，第 0 行 = 最低频）：0 = −90 dB，255 = 0 dB（相对满幅正弦）
    data: bytes


class SampleGlyph(TypedDict):
    """列表行的副信息（用途视图）：语音 = 音块在整句窗口里的位置（0–1）；调谐 = 音名 + 音高曲线（MIDI，32 点）；非调谐 = 起音时间 + 包络（32 点）。"""

    blocks: NotRequired[list[list[float]]]
    note: NotRequired[str]
    curve: NotRequired[list[float | None]]
    attackMs: NotRequired[float]
    envelope: NotRequired[list[float | None]]


class ChainStep(TypedDict):
    asset: AssetRecord
    # 这条轨覆盖的原素材秒
    sourceStart: float
    sourceEnd: float
    # 整轨（完整覆盖且未变速）
    full: bool


class ProcessingChain(TypedDict):
    """加工链（所有者 2026-10-12）：第一步是采样所在的轨，沿输入往上；complete = 追到了原混音（删除原素材断开时为 false）。"""

    steps: list[ChainStep]
    complete: bool


class SampleDetail(TypedDict):
    note: str
    origin: Any
    independent: bool
    # 判定区间（原片秒）
    judge: list[float] | None
    stemName: str | None
    updatedAt: str
    chain: ProcessingChain


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
    created_at: str
    version: int
    source_id: str
    asset_origin: str
    stream_ordinal: int | None
    work: str
    episode: str
    source_name: str
    source_path: str
    # 原素材起止（原素材秒，建采样时算好、不变）
    source_start: float | None
    source_end: float | None
    # 「返回原素材」换到的整轨（沿加工链往上第一条整轨；所有者 2026-10-12）
    back_asset_id: str | None
    media_state: str
    # 已独立化（规格 04 §4.8：声音与画面已物化，删原片后仍可用）
    independent: bool
    # 人物（说话人显示层：character: 在前，participants: 在后，只显示名字）
    people: list[str]
    # 语音分析（判定区间读到的段）：ok / manual 有人工版本 / partial 只读到某段的一部分（◐）/ stale 段改过待重新分析 / incomplete 有的段还没分析 / failed 只有失败 / none 没有可用分析或没读到段
    # / novoice 采样所在的轨不含人声（不读音素）
    analysis: Literal["ok", "manual", "partial", "stale", "incomplete", "failed", "none", "novoice"]
    # 有效标签（只有 samples.get 返回）
    tags: NotRequired[list[EffectiveTag]]
    # 资料与来源（只有 samples.get 返回）
    detail: NotRequired[SampleDetail]


class RelatedParams(TypedDict):
    id: str
    limit: NotRequired[int]


class RelatedSample(TypedDict):
    sample: SampleRow
    # 与这个采样交叠的原素材秒
    overlap: float
    # 它所在的轨（显示名用）
    stemName: str | None
    model: str | None


class RelatedSamples(TypedDict):
    total: int
    rows: list[RelatedSample]


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


class ExprParams(TypedDict):
    expr: str


class ExprCheck(TypedDict):
    ok: bool
    position: NotRequired[int]
    reason: NotRequired[str]


class BatchEditFields(TypedDict):
    name: NotRequired[str]
    nature: NotRequired[Literal["speech", "pitched", "unpitched", "unclassified"]]
    starred: NotRequired[bool]
    # 评分 1–5；None = 不评分
    rating: NotRequired[int | None]
    addTags: NotRequired[list[str]]
    removeTags: NotRequired[list[str]]


class BatchEditParams(TypedDict):
    ids: list[str]
    fields: BatchEditFields


class BatchEditPlan(TypedDict):
    """预览（不写库）；确认后把 ``batch`` 原样交给 ``edits.apply``（版本不符整批拒绝）。"""

    batch: EditBatch
    preview: EditPreview
    samples: int
    unchanged: int
    # 有变化的采样的名称（预览表用）
    names: dict[str, str]


class TagSourceRef(TypedDict):
    kind: Literal["rangeTag", "segment", "source", "asset"]
    id: str
    sourceId: str | None
    start: NotRequired[float]
    end: NotRequired[float]


class SampleTagCount(TypedDict):
    tag: str
    facet: str
    local: int
    inherited: int
    sources: list[TagSourceRef]


class TagUsage(TypedDict):
    tag: str
    facet: str
    samples: int
    local: int
    rangeTags: int
    sources: int
    segments: int


class GlobalTagParams(TypedDict):
    op: Literal["rename", "remove"]
    tag: str
    to: NotRequired[str | None]


class GlobalTagReport(TypedDict):
    samples: int
    rangeTags: int
    sources: int
    segments: int
    # 原片文件夹里的原片（作品跟文件夹走，不改）；派生的 speaker-status（改不了）
    folderSources: int
    derived: int


class GlobalTagPlan(TypedDict):
    batch: EditBatch
    report: GlobalTagReport
    changes: int


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
    via: NotRequired[Literal["manual", "hit"]]


class SamplePlanSource(TypedDict):
    """建采样的来源（所有者 2026-10-09：一个动作，单条与批量同一套规则）。

    selection：assetId + start/end（资产局部秒），可带 via（hit = 命中保存）、localMarker；
    segments / hints 也可以给 sourceIds（多个原素材，各用各的默认轨；此时 ids、track、范围都不用）；
    segments / hints：sourceId + 可选 ids（不给 = 全部）+ track（default 默认人声 / 音效轨；current 当前查看的轨 assetId）+ 可选 start/end（原片秒过滤）；
    stem：assetId（整条分离声部）；whole：sourceIds（整段原片）。"""

    kind: Literal["selection", "segments", "hints", "stem", "whole"]
    assetId: NotRequired[str | None]
    start: NotRequired[float | None]
    end: NotRequired[float | None]
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
    # 段 / 音效提示来源：原片秒与说话人
    sourceStart: NotRequired[float]
    sourceEnd: NotRequired[float]
    speakers: NotRequired[list[str]]
    # 多个原素材一起建时：这一条属于哪个原素材
    sourceId: NotRequired[str]
    sourceName: NotRequired[str]


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
    # 多个原素材一起建时：缺默认轨、没有列出来的原素材
    missingSources: NotRequired[list[str]]


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
    # 每个采样导出哪个版本：采样 ID → original / stretched；没给 = 原声
    versions: NotRequired[dict[str, Literal["original", "stretched"]] | None]
    # 卡拍用的方案；没给 = 就近偏快，不用 mora 和长音补格
    plan: NotRequired["RhythmPlan | None"]
    mora: NotRequired[bool | None]
    longVowel: NotRequired[bool | None]


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
    """交给外部工具的坐标：``range`` = 实际导出的资产区间（资产秒，按源样本取整后）；``mapping`` = 导出文件秒 → 原片秒的折线点
    ``[[文件秒, 原片秒], …]``（原声 = 资产映射截取这段；卡拍 = 清单里的合成映射）；``frames`` / ``sampleRate`` = 文件本身。"""

    path: str
    reused: bool
    key: str
    sourceId: str
    assetId: str
    range: list[float]
    sampleRate: int
    frames: int
    mapping: list[list[float]]


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
    """一条字幕按规则读成什么：有台词 = line（台词与音效可以同时有）；``sfx`` = 这一条的音效（没有 = 空）；
    ``withheld`` = 原文里有标注，但没法确定每一行是谁说的，所以没记说话人。"""

    kind: Literal["line", "sfx"]
    name: str
    speakers: list[str]
    alignText: str
    sfx: str
    withheld: bool


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
    # 段：原文里有标注，但没法确定每一行是谁说的，所以没记说话人
    withheld: NotRequired[bool]
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


class SubtitleClearParams(TypedDict):
    """删除这些原素材上从字幕导入的标记（段、音效提示、字幕规则标的 OP/ED）；``protected`` 为真时连改过的 / 有人工音素的也删（缺省留下）。"""

    sourceIds: list[str]
    protected: NotRequired[bool]


class SubtitleClearPlan(TypedDict):
    """会删多少：段（其中受保护、做过语音分析的数目，被多少采样读着）、手输的段（不删）、音效提示、OP/ED。"""

    segments: int
    segmentsProtected: int
    segmentsAnalyzed: int
    usedBy: int
    typedKept: int
    hints: int
    hintsProtected: int
    oped: int
    opedProtected: int


class SubtitleCleared(TypedDict):
    editId: str | None
    segments: int
    hints: int
    oped: int


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
    # 按规则**确定能读出**的说话人；空 = 不知道（不是“没人说”）。完整的标注信息看 ``raw``
    speakers: list[str]
    origin: Literal["subtitle", "typed"]
    edited: bool
    speakerEdited: bool
    # 原文（``raw``）里有标注，但没法确定每一行是谁说的，所以没记；说话人被改过之后为假
    speakersWithheld: bool
    manual: bool
    protected: bool
    # 读这一段的采样数（P13：“这段被 N 个采样使用”）
    usedBy: int
    # 原字幕这一条的原文（编辑、拆分后仍保留；合并后 = 各段原文按时间连起来）；手动加的段没有
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


class TextLayerSearchParams(TypedDict):
    """在文本层（段与音效提示）里搜关键词：规范化原文子串，或读音子串（同采样的“原句”筛选）。``sourceIds`` 缺省 = 全部原素材；
    ``hints`` 缺省为真（音效提示也搜，只按原文）；``speakers`` 只要这些说话人的段（给了就不搜音效提示）。"""

    query: str
    sourceIds: NotRequired[list[str] | None]
    hints: NotRequired[bool]
    speakers: NotRequired[list[str] | None]
    limit: NotRequired[int]
    offset: NotRequired[int]


class TextLayerHit(TypedDict):
    """一处命中：原片上的位置（原片秒），不是采样。``match`` = 按原文还是按读音命中；``spans`` = 原文命中在 ``text`` 里的字符范围（读音命中没有）。"""

    sourceId: str
    kind: Literal["segment", "hint"]
    id: str
    start: float
    end: float
    text: str
    speakers: list[str]
    match: Literal["text", "reading"]
    spans: list[list[int]]


class TextLayerSourceCount(TypedDict):
    sourceId: str
    count: int


class TextLayerSearchResult(TypedDict):
    """``total`` = 全部命中数（``hits`` 只是这一页，按原素材、时间排）；``notImported`` = 关联了字幕但文本层是空的原素材（搜不到）；
    ``readingPending`` = 读音还没算好的段数（这些段只按原文匹配，后台会补上）。"""

    query: str
    total: int
    hits: list[TextLayerHit]
    bySource: list[TextLayerSourceCount]
    notImported: list[str]
    readingPending: int


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
    kind: Literal["OP", "ED"]
    start: float
    end: float
    # mark = 手动标记（缺省）；confirm = 确认识别给出的建议（带 refs）
    via: NotRequired[Literal["confirm", "mark"]]
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
    """``ranges``：一次分离多段（``[[start, end], ...]``，资产秒；和 ``start`` / ``end`` 二选一）——同一个任务、模型只加载一次，每段各出一组声部。"""

    assetId: str
    start: NotRequired[float | None]
    end: NotRequired[float | None]
    ranges: NotRequired[list[list[float]] | None]
    model: str
    stems: NotRequired[list[str] | None]


class SeparationSubmitted(TypedDict):
    """全部的段进一个任务。不做自动复用：点一次跑一次（DECISIONS §9）。"""

    job: JobSummary


# ---------------------------------------------------------------- 语音分析（规格 08 §8.4）


class SpeechPlanParams(TypedDict):
    # 分析的是“文本层的段 + 具体那条资产”（所有者 2026-10-09）。source = 所选原片的段（不在 OP/ED 里）；segments = 这几段；
    # samples = 各采样判定区间读到的段；units = 指定的分析单元（结果表里再发起失败项，在上次测它用的轨上）
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
    # 合成结果里：来自读到的第几段（units 的序号）；被采样范围或这条轨的边界裁掉一部分的非停顿音素（◐）
    seg: NotRequired[int]
    clipped: NotRequired[bool]
    # 在这句完整结果里的序号（读取方这条轨只看到一部分音素时，人工修时间用）
    i: NotRequired[int]


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
    """采样读到的一段的音素（原素材时间线上一份、回导来的另一份），换到采样所在的轨上。人工修正改的是这句的那一份，所有读到它的采样同时生效。"""

    unitId: str
    segmentId: str
    # 段在文本层里的序号（读取时按存活段的起点排出）
    ordinal: int
    name: str
    text: str
    speakers: list[str]
    # 资产局部秒；段不在这条轨的范围里时为 null
    target: list[float] | None
    # ok 可用 / stale 段改过待重新分析 / failed 只有失败记录 / none 还没分析
    state: Literal["ok", "stale", "failed", "none"]
    # 采样只读到这段的一部分（◐）
    partial: bool
    # 可用的音素测在哪条轨上（只作记录）
    measuredOn: AssetRecord | None
    # 可用版本的对齐窗口（原素材秒）
    windowSource: list[float] | None
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
    # 读到的段的文本连起来；没读到段时给 reason：no-text；采样所在的轨不含人声时给 reason：no-voice（units 为空）
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
    # 测在哪条轨上
    measuredOn: str
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
    # 时间是哪条轨的局部秒（读取方；只含这条轨盖得住的音素）；不给 = 测量用的那条轨
    assetId: NotRequired[str | None]


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
    """REAPER 交接（12 §12.3）：多条 = 依次排开、间隔一小节。kind：original = 原声 + 音头处的 1 倍速拉伸标记 / fitted = 原声 + 卡拍拉伸标记 /
    不给 = 按设置 export.reaper_kind（⌘C 用）。"""

    ids: list[str]
    words: NotRequired[dict[str, str]]
    plan: NotRequired[RhythmPlan | None]
    mora: NotRequired[bool | None]
    longVowel: NotRequired[bool | None]
    kind: NotRequired[Literal["original", "fitted"] | None]
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
    # 与 SampleFilter 相同的标签条件（采样模式按采样的有效标签；原片模式按查询窗与标注交叠，L28）。
    # 以前没声明，参数校验时被静默丢掉（阶段 A 写说明书时发现）
    tags: NotRequired[TagScope | None]
    expr: NotRequired[str]
    metrics: NotRequired[MetricFilter | None]
    languages: NotRequired[list[str] | None]


class SearchCoverageParams(TypedDict):
    # pitch = 已保存采样；pitchSources = 已分析原片音轨（整轨测 F0）
    mode: Literal["speech", "pitch", "pitchSources"]
    # 当前浏览范围（与 samples.list 同一套条件）；pitchSources 另可按音轨角色（roles）。
    # 以前类型是 SampleFilter，roles 在参数校验时被静默丢掉（阶段 A 严格检查在真实素材测试里抓到）
    scope: NotRequired[PitchSourceScope | None]


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


class VideoExportParams(TypedDict):
    id: str
    version: Literal["original", "stretched"]
    # 卡拍版的画面：synced = 同映射变速（音画同步）；original = 原速画面（带原声，另存卡拍 WAV 与映射清单）
    picture: NotRequired[Literal["synced", "original"]]
    audio: NotRequired[bool]
    words: NotRequired[dict[str, str]]
    plan: NotRequired[RhythmPlan]
    mora: NotRequired[bool]
    longVowel: NotRequired[bool]


class VideoRangeParams(TypedDict):
    assetId: str
    start: float
    end: float
    audio: NotRequired[bool]
    words: NotRequired[dict[str, str]]


class HitVideoParams(TypedDict):
    resultId: str
    rank: int
    index: int
    version: NotRequired[Literal["original", "stretched"]]
    picture: NotRequired[Literal["synced", "original"]]
    audio: NotRequired[bool]
    words: NotRequired[dict[str, str]]


class VideoExportStarted(TypedDict):
    """已导出过（reused = true，path）或排队的任务（job）；完成后发 exports.videoDone。"""

    reused: bool
    path: str | None
    job: JobSummary | None
    stretchedWav: NotRequired[str]


class ReimportParams(TypedDict):
    assetId: str
    # 选区起点（资产局部秒）；终点按文件时长
    start: float
    path: str


class ReimportPreview(TypedDict):
    duration: float
    sampleRate: int
    start: float
    end: float
    ok: bool
    reason: str | None
    sourceStart: float
    sourceEnd: float | None
    assetDuration: float
    # 回导成品的建议名（它落到的那段的建议名；放不下时为 null）
    suggestedName: str | None


class ReimportCommitParams(ReimportParams):
    name: NotRequired[str | None]
    nature: NotRequired[Literal["speech", "pitched", "unpitched", "unclassified"]]


class IndependItem(TypedDict):
    id: str
    name: str
    duration: float
    # 切片大约多大（字节）
    bytes: int
    # 要不要生成画面片段（有效画面是原片自带的视频流）
    picture: bool
    independent: bool


class IndependParams(TypedDict):
    ids: list[str]
    # 独立化完成后接着删除这个原片（原片保留为“媒体已释放”）
    deleteSource: NotRequired[str | None]


class StorageCategory(TypedDict):
    key: Literal["cache", "searchIndex", "measurements", "tracks", "independent", "exports", "jobs", "database", "backups"]
    bytes: int
    # 现在可以清理的量（15 分钟内生成的不算）；永不当缓存删的类别为 0
    cleanable: int
    files: int
    # 15 分钟内生成 / 修改的文件数（受保护）
    recent: int


class StorageSource(TypedDict):
    sourceId: str
    name: str
    bytes: int
    files: int


class StorageReport(TypedDict):
    categories: list[StorageCategory]
    sources: list[StorageSource]
    idleCleanup: bool
    lastAuto: float | None
    # 给“打开文件夹”用
    folders: dict[str, str]


class AssetDeletePreview(TypedDict):
    assetId: str
    sourceId: str
    deletable: bool
    # 不能删的原因：asset-stream 原混音 / asset-samples 有采样在用 / asset-jobs 有任务在用
    reason: str | None
    samples: int
    # 它是哪些角色的默认轨（删除后这个角色没有默认轨，不会自动换一条）
    defaults: list[str]
    # 连带删掉的语音分析（段数）
    analyses: int
    bytes: int


class UnusedAsset(TypedDict):
    """没有采样在用、也不是默认轨的音轨与成品。"""

    assetId: str
    sourceId: str
    sourceName: str
    origin: AssetOrigin
    model: str | None
    stem: str | None
    createdAt: str
    bytes: int
    analyses: int
    fileMissing: bool


class AssetDeleteParams(TypedDict):
    ids: list[str]


class AssetsDeleted(TypedDict):
    deleted: int
    bytes: int
    # 记录已删、文件暂时删不掉的个数（Windows 上文件正被占用）
    filesLeft: int


class StorageCleanParams(TypedDict):
    # 同时清掉语音检索索引与单音指标（数据库里的派生数据，之后后台重建）
    derived: NotRequired[bool]


class StorageCleaned(TypedDict):
    files: int
    bytes: int
    rows: int


class RelocatePlanParams(TypedDict):
    ids: list[str]
    folder: str


class RelocateItem(TypedDict):
    sourceId: str
    oldPath: str
    path: str | None
    # relative = 按相对导入根文件夹的路径找到；name = 按文件名找到（唯一）；ambiguous = 同名多个；missing = 没找到；
    # in-root = 原片文件夹里的（用「更换位置…」）；released = 媒体已释放
    how: Literal["relative", "name", "ambiguous", "missing", "in-root", "released"] | None
    candidates: list[str]


class RelocateManyParams(TypedDict):
    items: list[RelocateItem]


class TrackDefaultParams(TypedDict):
    sourceId: str
    role: Role
    # null = 取消这个角色的默认轨
    assetId: str | None


class TrackRoleParams(TypedDict):
    assetId: str
    role: Role
    on: bool


class SeparatedVocalOption(TypedDict):
    """所选原素材里已有的整轨人声声部：哪个模型的哪个声部，有几个原素材有。"""

    model: str
    stem: str
    sources: int


class TrackDefaultFromSeparationParams(TypedDict):
    sourceIds: list[str]
    model: str
    stem: str


class OriginalAsVocal(TypedDict):
    """原混音设为人声与默认人声轨：改了几个原素材、跳过几个（已有默认人声轨 / 媒体已释放 / 没有原混音）。"""

    edit_id: str | None
    applied: int
    skipped: int



# ---------------------------------------------------------------- 原始能力（layer = primitive，所有者 2026-10-30）


class AudioRef(TypedDict):
    """一段声音：库里的音轨（``assetId``，时间 = 资产秒）或任意音频 / 视频文件（``path``，时间 = 文件秒；``stream`` = 第几条音频流，缺省 0）。
    ``start`` / ``end`` 缺省 = 整条。两者给且只给一个。"""

    assetId: NotRequired[str]
    path: NotRequired[str]
    stream: NotRequired[int]
    start: NotRequired[float]
    end: NotRequired[float]


class AlignItemParams(TypedDict):
    """一句文字 + 它所在的那段声音（同 AudioRef）。窗口要紧贴实际说话（误差零点一到零点二秒），对齐不会自己找这句话在哪。
    ``lines``（代替 ``text``）：同一段声音里先后说的几行（例如一条字幕的两行），每行当一句对齐，结果另给每行的起止。"""

    text: NotRequired[str]
    lines: NotRequired[list[str]]
    assetId: NotRequired[str]
    path: NotRequired[str]
    stream: NotRequired[int]
    start: NotRequired[float]
    end: NotRequired[float]


class SpeechAlignParams(TypedDict):
    items: list[AlignItemParams]


class TextAnalyzeParams(TypedDict):
    texts: list[str]


class SubtitleParseParams(TypedDict):
    """``duration``：媒体时长（秒），用于 OP/ED 区间的范围检查与 OP / ED 判定；缺省用最后一条字幕的结束时间。"""

    path: str
    duration: NotRequired[float | None]


class SubtitleParsedCue(TypedDict):
    no: int
    ref: str
    start: float
    end: float
    raw: str
    kind: Literal["line", "sfx"]
    text: str
    speakers: list[str]
    # 这一条的音效（台词条里也可能有音效行；没有 = 空）
    sfx: str
    # 原文里有标注，但没法确定每一行是谁说的，所以没记说话人
    withheld: bool


class SubtitleParsedPair(TypedDict):
    start: float
    end: float
    kind: Literal["OP", "ED"]
    refs: list[str]


class SubtitleParsedOped(TypedDict):
    pairs: list[SubtitleParsedPair]
    errors: list[dict[str, Any]]


class SubtitleParsed(TypedDict):
    """应用按当前字幕规则会把这个文件读成什么（不登记、不导入）：台词（``kind: line``，``text`` = 对齐用文字）与音效（``sfx``）、说话人、OP/ED 配对、读不出时间的块。"""

    path: str
    format: str
    fingerprint: str
    cues: list[SubtitleParsedCue]
    speakers: list[SubtitleSpeaker]
    oped: SubtitleParsedOped
    problems: list[SubtitleProblem]


class PrimitiveResultsParams(TypedDict):
    jobId: str
    offset: NotRequired[int]
    limit: NotRequired[int]


class TextAnalysisWord(TypedDict):
    """``start`` / ``end`` = 原文里的字符范围（数字展开等对不上时为 null）；``moraStart`` = 第一个音拍在整句里的序号。"""

    text: str
    reading: str
    start: int | None
    end: int | None
    morae: list[str]
    moraStart: int
    mapped: bool


class TextAnalysis(TypedDict):
    """日语前端（tsqyomi + pyopenjtalk-plus + 用户辞典，与语音分析同一套）：音素（含停顿 pau）、音拍（片假名）、词与读音。"""

    text: str
    normalized: str
    phonemes: list[str]
    morae: list[str]
    words: list[TextAnalysisWord]
    dictionary: str


class TextAnalysisRow(TypedDict):
    idx: int
    status: str
    error: dict[str, Any] | None
    result: NotRequired[TextAnalysis]


class AlignPhone(TypedDict):
    """时间 = 输入的时钟（资产秒或文件秒）；音轨输入另给 ``sourceStart`` / ``sourceEnd``（原片秒）。``mora`` / ``word`` = 序号。"""

    label: str
    start: float
    end: float
    mora: int | None
    word: int | None
    sourceStart: NotRequired[float]
    sourceEnd: NotRequired[float]


class AlignSpan(TypedDict):
    text: str
    start: float
    end: float
    sourceStart: NotRequired[float]
    sourceEnd: NotRequired[float]


class AlignResult(TypedDict):
    """对齐结果。对齐总会把整句放进窗口，不会报“找不到”：``edges`` = 窗口两端到首尾音素的空白秒数（接近 0 = 说话可能被窗口截断），
    ``longestPhone`` = 最长的音素；这些只是事实，判断交给你。"""

    text: str
    clock: Literal["asset", "file"]
    window: list[float]
    phones: list[AlignPhone]
    morae: list[AlignSpan]
    words: list[AlignSpan]
    speech: AlignSpan
    edges: dict[str, float]
    longestPhone: dict[str, Any]
    # 输入是 ``lines`` 时：每行的起止（首个到最后一个音素）
    lines: NotRequired[list[AlignSpan]]


class AlignRow(TypedDict):
    idx: int
    status: str
    error: dict[str, Any] | None
    result: NotRequired[AlignResult]


class F0Track(TypedDict):
    """FCPE（与应用的音高检索同一个模型）：float32 小端序列，第 i 帧中心 = t0 + i × step（输入的时钟）；``summary`` = 置信度 ≥ 0.5 的帧的统计。"""

    clock: Literal["asset", "file"]
    t0: float
    step: float
    count: int
    f0: bytes
    confidence: bytes
    energy: bytes
    summary: dict[str, Any]


class F0TrackRow(TypedDict):
    idx: int
    status: str
    error: dict[str, Any] | None
    result: NotRequired[F0Track]
