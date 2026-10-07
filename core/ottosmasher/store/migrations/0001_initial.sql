-- 0001 初始结构（ARCHITECTURE §4）。
-- 约定：ID 是 32 位十六进制文本；时间是 UTC ISO 8601 文本；JSON 列存 msgspec 编码的 JSON 文本；
-- 布尔用 0/1；所有用户可编辑对象带 version（乐观并发）与 created_at/updated_at。
-- 显示文字不入库：性质、角色、来源种类等存稳定的内部值。

-- ---------- 原片与流（§4.1） ----------
CREATE TABLE source (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  import_root TEXT,
  file_snapshot TEXT,
  duration REAL,
  work TEXT NOT NULL DEFAULT '',
  episode TEXT NOT NULL DEFAULT '',
  source_type TEXT NOT NULL DEFAULT '',
  subtitle_path TEXT,
  default_audio_stream INTEGER,
  media_state TEXT NOT NULL DEFAULT 'available' CHECK (media_state IN ('available', 'released')),
  visual_binding_id TEXT,
  current_subtitle_version_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE source_stream (
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('audio', 'video')),
  ordinal INTEGER NOT NULL,
  container_index INTEGER NOT NULL,
  codec TEXT,
  sample_rate INTEGER,
  channels INTEGER,
  bit_depth INTEGER,
  language TEXT,
  title TEXT,
  start_time REAL,
  duration REAL,
  is_attached_pic INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (source_id, kind, ordinal)
);

-- ---------- 声音资产、角色、默认轨（§4.2） ----------
CREATE TABLE media_file (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  location TEXT NOT NULL CHECK (location IN ('external', 'library')),
  file_snapshot TEXT,
  format TEXT,
  sample_rate INTEGER,
  frames INTEGER,
  encode_manifest TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE sound_asset (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id),
  origin TEXT NOT NULL CHECK (origin IN ('stream', 'separation', 'flatten', 'reimport')),
  media_file_id TEXT REFERENCES media_file(id),
  stream_ordinal INTEGER,
  duration REAL NOT NULL,
  mapping TEXT NOT NULL,
  input_asset_id TEXT REFERENCES sound_asset(id),
  input_start REAL,
  input_end REAL,
  stem_name TEXT,
  production TEXT,
  language TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX sound_asset_source ON sound_asset(source_id);

CREATE TABLE asset_storage (
  asset_id TEXT NOT NULL REFERENCES sound_asset(id) ON DELETE CASCADE,
  range_start REAL NOT NULL,
  range_end REAL NOT NULL,
  media_file_id TEXT NOT NULL REFERENCES media_file(id),
  kind TEXT NOT NULL CHECK (kind IN ('primary', 'materialized_slice'))
);
CREATE INDEX asset_storage_asset ON asset_storage(asset_id);

CREATE TABLE asset_role (
  asset_id TEXT NOT NULL REFERENCES sound_asset(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('vocal', 'sfx')),
  state TEXT NOT NULL CHECK (state IN ('on', 'removed_by_user')),
  version INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (asset_id, role)
);

CREATE TABLE default_track (
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('vocal', 'sfx')),
  asset_id TEXT NOT NULL REFERENCES sound_asset(id),
  version INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (source_id, role)
);

-- ---------- 字幕、标注、OP/ED（§4.3） ----------
CREATE TABLE subtitle_version (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  content_hash TEXT NOT NULL,
  file_name TEXT NOT NULL,
  language TEXT,
  rules_snapshot TEXT,
  imported_at TEXT NOT NULL,
  UNIQUE (source_id, content_hash)
);

CREATE TABLE subtitle_line (
  id TEXT PRIMARY KEY,
  version_id TEXT NOT NULL REFERENCES subtitle_version(id) ON DELETE CASCADE,
  line_no INTEGER NOT NULL,
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  raw_text TEXT NOT NULL
);
CREATE INDEX subtitle_line_version ON subtitle_line(version_id, line_no);

CREATE TABLE annotation (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('line', 'sfx', 'song', 'tag')),
  scope TEXT NOT NULL CHECK (scope IN ('source', 'role', 'asset')),
  scope_role TEXT,
  scope_asset_id TEXT REFERENCES sound_asset(id),
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  raw_text TEXT NOT NULL DEFAULT '',
  clean_text TEXT NOT NULL DEFAULT '',
  align_text_auto TEXT,
  align_text_manual TEXT,
  tags TEXT NOT NULL DEFAULT '[]',
  subtitle_version_id TEXT REFERENCES subtitle_version(id),
  subtitle_line_id TEXT,
  user_edited INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX annotation_source ON annotation(source_id, start);

CREATE TABLE annotation_revision (
  annotation_id TEXT NOT NULL REFERENCES annotation(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  snapshot TEXT NOT NULL,
  edit_id TEXT,
  PRIMARY KEY (annotation_id, version)
);

CREATE TABLE oped (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('OP', 'ED')),
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('subtitle_rule', 'manual')),
  evidence TEXT,
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

-- ---------- 采样（§4.4） ----------
CREATE TABLE sample (
  id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL REFERENCES sound_asset(id),
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  name TEXT NOT NULL,
  nature TEXT NOT NULL DEFAULT 'unclassified'
    CHECK (nature IN ('speech', 'pitched', 'unpitched', 'unclassified')),
  starred INTEGER NOT NULL DEFAULT 0,
  rating INTEGER,
  note TEXT NOT NULL DEFAULT '',
  language TEXT,
  created_via TEXT NOT NULL,
  parent_sample_id TEXT REFERENCES sample(id) ON DELETE SET NULL,
  parent_label TEXT,
  origin TEXT,
  text_snapshot TEXT,
  tag_judge_start REAL,
  tag_judge_end REAL,
  align_text_manual TEXT,
  independent INTEGER NOT NULL DEFAULT 0,
  visual_binding_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  CHECK ("end" > start)
);
CREATE INDEX sample_asset ON sample(asset_id);
CREATE INDEX sample_created ON sample(created_at);

CREATE TABLE sample_tag (
  sample_id TEXT NOT NULL REFERENCES sample(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  PRIMARY KEY (sample_id, tag)
);

CREATE TABLE sample_effective_tag (
  sample_id TEXT NOT NULL REFERENCES sample(id) ON DELETE CASCADE,
  tag TEXT NOT NULL,
  facet TEXT NOT NULL,
  provenance TEXT NOT NULL CHECK (provenance IN ('local', 'source', 'segment', 'auto')),
  provenance_ref TEXT
);
CREATE INDEX sample_effective_tag_tag ON sample_effective_tag(tag);
CREATE INDEX sample_effective_tag_sample ON sample_effective_tag(sample_id);

-- ---------- 测量（§4.5） ----------
CREATE TABLE measure_run (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('alignment', 'f0', 'acoustic')),
  owner_type TEXT NOT NULL CHECK (owner_type IN ('sample', 'asset_text', 'asset')),
  owner_id TEXT NOT NULL,
  asset_id TEXT NOT NULL REFERENCES sound_asset(id),
  range_start REAL,
  range_end REAL,
  inputs TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok', 'failed', 'cancelled', 'stale')),
  manual INTEGER NOT NULL DEFAULT 0,
  result TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX measure_run_owner ON measure_run(owner_type, owner_id, kind);

CREATE TABLE measure_head (
  owner_type TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  run_id TEXT NOT NULL REFERENCES measure_run(id),
  version INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (owner_type, owner_id, kind)
);

-- ---------- 检索结果与筛选（§4.7） ----------
CREATE TABLE result_set (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('speech', 'pitch')),
  created_at TEXT NOT NULL,
  title TEXT NOT NULL,
  query TEXT NOT NULL,
  scope_snapshot TEXT NOT NULL,
  params TEXT NOT NULL,
  stats TEXT NOT NULL,
  ui_state TEXT,
  closed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE result_member (
  result_id TEXT NOT NULL REFERENCES result_set(id) ON DELETE CASCADE,
  rank INTEGER NOT NULL,
  sample_id TEXT,
  asset_id TEXT,
  binding_snapshot TEXT NOT NULL,
  hits TEXT NOT NULL,
  PRIMARY KEY (result_id, rank)
);

CREATE TABLE saved_filter (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  conditions TEXT NOT NULL,
  sort_order INTEGER NOT NULL,
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

-- ---------- 编辑记录（§5） ----------
CREATE TABLE edit (
  id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  label_code TEXT NOT NULL,
  label_args TEXT NOT NULL DEFAULT '{}',
  undo_of TEXT REFERENCES edit(id),
  undone_by TEXT REFERENCES edit(id)
);

CREATE TABLE edit_change (
  edit_id TEXT NOT NULL REFERENCES edit(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('create', 'update')),
  before TEXT,
  after TEXT NOT NULL,
  version_before INTEGER,
  version_after INTEGER NOT NULL,
  PRIMARY KEY (edit_id, idx)
);
CREATE INDEX edit_change_entity ON edit_change(entity, entity_id);

-- ---------- 任务（§4.8，规格 13 §13.1） ----------
CREATE TABLE job (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  channel TEXT NOT NULL CHECK (channel IN ('model', 'light')),
  status TEXT NOT NULL
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'interrupted')),
  params TEXT NOT NULL,
  device TEXT NOT NULL,
  affects TEXT NOT NULL DEFAULT '{}',
  progress TEXT,
  error TEXT,
  result TEXT,
  retry_of TEXT REFERENCES job(id),
  items_total INTEGER,
  items_ok INTEGER,
  items_failed INTEGER,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX job_status ON job(status, created_at);

CREATE TABLE job_item (
  job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  target TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  result_ref TEXT,
  PRIMARY KEY (job_id, idx)
);

-- ---------- 导出、画面、辞典、设置、界面状态、模型（§4.8） ----------
CREATE TABLE export_file (
  stable_key TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  kind TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE visual_binding (
  id TEXT PRIMARY KEY,
  owner_type TEXT NOT NULL CHECK (owner_type IN ('source', 'sample')),
  owner_id TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('sync', 'image', 'loop', 'materialized_clip')),
  media_file_id TEXT REFERENCES media_file(id),
  clip_offset REAL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE user_dictionary (
  version INTEGER PRIMARY KEY,
  source_text TEXT NOT NULL,
  compiled_path TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE setting (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE ui_state (
  window TEXT NOT NULL,
  page TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (window, page, key)
);

CREATE TABLE model_probe (
  model TEXT NOT NULL,
  device_setting TEXT NOT NULL,
  file_sha TEXT,
  status TEXT NOT NULL CHECK (status IN ('passed', 'failed')),
  ep_node_counts TEXT,
  error TEXT,
  tested_at TEXT NOT NULL,
  PRIMARY KEY (model, device_setting)
);

-- 大文件 SHA-256 的缓存：键是文件快照（路径 + 大小 + 修改时间），快照变了就重算
CREATE TABLE file_hash_cache (
  path TEXT PRIMARY KEY,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  computed_at TEXT NOT NULL
);
