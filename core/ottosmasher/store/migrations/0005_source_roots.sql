-- 阶段 3.13（所有者 2026-10-07）：原片文件夹。设置里指定一个或多个“原片文件夹”，第一层子文件夹名 = 作品；
-- 启动时与手动「重新扫描」时登记新文件、认出被移动/改名的文件；作品名在应用里改 = 改磁盘上的文件夹名。
CREATE TABLE source_root (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 作品文件夹（原片文件夹的第一层子文件夹）：作品级设置——来源类型（新文件沿用）、同名画面自动绑定
CREATE TABLE work_folder (
  id TEXT PRIMARY KEY,
  root_id TEXT NOT NULL REFERENCES source_root(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT '',
  bind_pictures INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  UNIQUE (root_id, name)
);

-- 原片在原片文件夹里的位置（相对路径，用 / 分隔）；不在任何原片文件夹里的为 NULL
ALTER TABLE source ADD COLUMN root_id TEXT REFERENCES source_root(id);
ALTER TABLE source ADD COLUMN rel_path TEXT;
