// 与 Core 命令返回值对应的类型（阶段 1 手写；之后由 Core 的命令定义生成）。

export interface SettingEntry {
  value: unknown;
  default: unknown;
  version: number;
  group: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";

export interface JobSummary {
  id: string;
  kind: string;
  channel: "model" | "light";
  status: JobStatus;
  affects: Record<string, string[]>;
  progress: { stage: string; done: number; total: number; percent: number | null; code: string; args: Record<string, unknown> } | null;
  error: { code: string; args: Record<string, unknown> } | null;
  result: unknown;
  device: { accelerate: boolean; directml_device: number };
  retry_of: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EditLabel {
  code: string;
  args: Record<string, unknown>;
}

export interface ModelFileStatus {
  path: string;
  role: "weight" | "support";
  state: "ok" | "missing" | "size-mismatch" | "sha-mismatch" | "unverified";
}

export interface ModelsStatus {
  models_dir: string;
  support_dir: string;
  files: Array<{ model: string; state: "ready" | "missing" | "mismatch" | "unverified"; files: ModelFileStatus[]; url: string }>;
  runtime: { onnxruntime: { loadable: boolean; version?: string; providers?: string[]; error?: string } };
  probes: Array<{ model: string; status: string }>;
}

export interface Hello {
  version: string;
  workspace: string;
  schema_version: number;
  interrupted_on_start: number;
  dev: boolean;
}

// ---------- 原片与资产（阶段 2）

export interface SourceRow {
  id: string;
  path: string;
  work: string;
  episode: string;
  source_type: string;
  duration: number;
  media_state: "available" | "released";
  subtitle_path: string | null;
  default_audio_stream: number;
  created_at: string;
  version: number;
  audio_streams: number;
  has_video: boolean;
  counts?: { lines: number; hasMarkers: boolean; oped: number; samples: number };
}

export interface SourceStream {
  kind: "audio" | "video";
  ordinal: number;
  codec: string | null;
  sample_rate: number | null;
  channels: number | null;
  language: string | null;
  title: string | null;
  duration: number | null;
  is_attached_pic: boolean;
}

export interface SourceDetail extends Omit<SourceRow, "audio_streams" | "has_video"> {
  streams: SourceStream[];
}

export interface AssetInfo {
  id: string;
  source_id: string;
  origin: "stream" | "separation" | "flatten" | "reimport";
  stream_ordinal: number | null;
  duration: number;
  language: string | null;
  roles: string[];
  isFullTrack: boolean;
  mapping: number[][];
  stem_name: string | null;
  production: { model?: string | null } | null;
}

export interface AddResult {
  path: string;
  ok: boolean;
  sourceId?: string;
  existing?: boolean;
  error?: { code: string; args: Record<string, unknown> };
  inferTimedOut?: number[];
}

export interface DeletePreview {
  sourceId: string;
  path: string;
  samples: number;
  independentSamples: number;
  generatedAssets: number;
  annotations: number;
  subtitleVersions: number;
  oped: number;
  activeJobs: string[];
}

// ---------- 采样（阶段 2）

export type Nature = "speech" | "pitched" | "unpitched" | "unclassified";

export interface SampleRow {
  id: string;
  asset_id: string;
  start: number;
  end: number;
  duration: number;
  name: string;
  nature: Nature;
  starred: boolean;
  rating: number | null;
  language: string | null;
  created_via: string;
  parent_sample_id: string | null;
  parent_label: string | null;
  created_at: string;
  version: number;
  source_id: string;
  source_name: string;
  source_path: string;
  source_start: number | null;
  stream_ordinal: number | null;
  media_state: string;
  /** 人物（说话人显示层：character: 在前，participants: 在后，只显示名字） */
  people: string[];
  /** 有效标签（只有 samples.get 返回） */
  tags?: EffectiveTag[];
}

export interface EffectiveTag {
  tag: string;
  facet: "work" | "type" | "person" | "pitch" | "other";
  provenance: "local" | "source" | "segment" | "auto";
  ref: string | null;
}

export interface SamplePage {
  total: number;
  offset: number;
  rows: SampleRow[];
}

export interface SampleSuggestion {
  name: string;
  nature: Nature;
  roles: string[];
  start: number;
  end: number;
}

// ---------- 字幕标记导入（阶段 3.2）

export type SubtitleLineStatus = "importable" | "oped" | "invalid" | "registered";
export interface SubtitlePreviewLine {
  no: number;
  ref: string;
  start: number;
  end: number;
  text: string;
  kind: "line" | "sfx";
  name: string;
  speakers: string[];
  alignText: string;
  status: SubtitleLineStatus;
  reason?: "negative-start" | "empty" | "beyond-end";
  oped?: "OP" | "ED";
  opedPartial?: boolean;
}
export type SubtitleVersionState = "new" | "current" | "switch";
export interface SubtitlePreview {
  sourceId: string;
  path: string;
  fileName: string;
  format: string;
  token: string;
  versionState: SubtitleVersionState;
  lines: SubtitlePreviewLine[];
  counts: Record<SubtitleLineStatus, number>;
  problems: Array<{ line: number; reason: string }>;
}
export interface SubtitleImportResult {
  sourceId: string;
  editId: string | null;
  imported: number;
  versionId: string;
  newVersion: boolean;
  switched: boolean;
  skipped: { invalid: number; registered: number };
}
export type SubtitleBatchRow =
  | { sourceId: string; skipped: "no-subtitle" }
  | { sourceId: string; error: { code: string; args: Record<string, unknown> } }
  | { sourceId: string; fileName: string; token: string; versionState: SubtitleVersionState; counts: Record<SubtitleLineStatus, number>; problems: number };
