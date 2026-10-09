-- 所有者 2026-10-09【巨大的基线变更】原片上的四类对象（docs/QUESTIONS.md「原片上的四类对象」）：
--   文本层的段（说了什么，给分析）/ 音效提示（给人工拣选）/ 区段标签（时间上的属性）/ 采样（哪段有价值）。
-- 取消字幕版本；分析属于“段 + 具体那条资产”；采样按可编辑的判定区间读取。
-- 这个迁移只增不删：旧的 annotation / subtitle_version / subtitle_line 表与 sample.align_text_manual、source.current_subtitle_version_id
-- 列留到 0013 再删（代码从这里起不再读写它们）。

-- ---------- 文本层：每个原片一层“台词段”（原片秒，作用于整个原片，允许重叠）
CREATE TABLE text_segment (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  -- 文本 = 对齐文本（导入时按当时规则去掉注释括号，保留换行）
  text TEXT NOT NULL,
  -- 说话人（属性，有序名单）：一人 → character:名；多人 → participants:名 + speaker-status:多人未分段（只对带人声角色的资产生效）
  speakers TEXT NOT NULL DEFAULT '[]',
  origin TEXT NOT NULL CHECK (origin IN ('subtitle', 'typed')),
  -- 来源记录（字幕来源）：{file, fingerprint, line, raw, importedAt}
  provenance TEXT,
  -- 受保护的第一个标记：段本身被用户改过（文本、边界、拆分合并产物、切开后缩短的旧段、手输段）
  edited INTEGER NOT NULL DEFAULT 0,
  -- 说话人改过（不算受保护，只让「按当前规则重新生成说话人」跳过）
  speaker_edited INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent')),
  actor_session TEXT,
  CHECK ("end" > start)
);
CREATE INDEX text_segment_live ON text_segment(source_id, start) WHERE deleted = 0;

-- ---------- 字幕音效提示层（作用于整个原片，所有轨可见；不进文本层、不做对齐、不带标签）
CREATE TABLE sfx_hint (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  -- 括号内容（多个用“ / ”连接）
  text TEXT NOT NULL,
  origin TEXT NOT NULL CHECK (origin IN ('subtitle', 'manual')),
  provenance TEXT,
  edited INTEGER NOT NULL DEFAULT 0,
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent')),
  actor_session TEXT,
  CHECK ("end" > start)
);
CREATE INDEX sfx_hint_live ON sfx_hint(source_id, start) WHERE deleted = 0;

-- ---------- 区段标签（用户显式画的；原片 / 角色 / 资产三种作用域；资产作用域用资产局部秒）
CREATE TABLE range_tag (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  scope TEXT NOT NULL CHECK (scope IN ('source', 'role', 'asset')),
  scope_role TEXT CHECK (scope_role IN ('vocal', 'sfx')),
  scope_asset_id TEXT REFERENCES sound_asset(id),
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '[]',
  deleted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent')),
  actor_session TEXT,
  CHECK ("end" > start)
);
CREATE INDEX range_tag_live ON range_tag(source_id, start) WHERE deleted = 0;
CREATE INDEX range_tag_asset ON range_tag(scope_asset_id);

-- 迁移后在 Core 里补做的 Python 步骤（有效标签重算）
CREATE TABLE upgrade_pending (name TEXT PRIMARY KEY);
INSERT INTO upgrade_pending(name) VALUES ('effective-tags');

-- OP/ED：改过边界的算受保护（人工标记 / 确认的按 origin 判断）
ALTER TABLE oped ADD COLUMN edited INTEGER NOT NULL DEFAULT 0;
UPDATE oped SET edited = 1 WHERE EXISTS (
  SELECT 1 FROM edit_change c WHERE c.entity = 'oped' AND c.entity_id = oped.id AND c.op = 'update'
    AND (json_extract(c.after, '$.start') IS NOT NULL OR json_extract(c.after, '$.end') IS NOT NULL));

-- 分析版本对应的段内容（分析时的段区间与文本）：与段现在的内容不一致 = 段改过，这个版本停用
ALTER TABLE measure_run ADD COLUMN seg_start REAL;
ALTER TABLE measure_run ADD COLUMN seg_end REAL;
ALTER TABLE measure_run ADD COLUMN seg_text TEXT;

-- ---------- 迁移旧标注（只要当前字幕版本或没有版本的、未删除的；其余在任何地方都不参与）

-- 台词（含用户标的歌词：所有者 2026-10-09 去掉歌词概念）→ 段，保留原 id
INSERT INTO text_segment(id, source_id, start, "end", text, speakers, origin, provenance, edited, speaker_edited, deleted, created_at, updated_at, version)
SELECT a.id, a.source_id, a.start, a."end",
  CASE
    WHEN TRIM(COALESCE(a.align_text_manual, '')) <> '' THEN a.align_text_manual
    WHEN TRIM(a.clean_text) <> '' AND a.clean_text <> replace(COALESCE(a.align_text_auto, ''), char(10), ' ') THEN a.clean_text
    ELSE COALESCE(NULLIF(a.align_text_auto, ''), a.clean_text)
  END,
  COALESCE((SELECT json_group_array(substr(j.value, instr(j.value, ':') + 1)) FROM
    (SELECT value FROM json_each(a.tags) WHERE value LIKE 'character:%' OR value LIKE 'participants:%' ORDER BY key) j), '[]'),
  CASE WHEN a.subtitle_version_id IS NULL THEN 'typed' ELSE 'subtitle' END,
  CASE WHEN l.id IS NULL THEN NULL
       ELSE json_object('file', v.file_name, 'fingerprint', v.content_hash, 'line', l.line_no, 'raw', l.raw_text, 'importedAt', v.imported_at) END,
  CASE WHEN l.id IS NULL OR abs(a.start - l.start) > 1e-9 OR abs(a."end" - l."end") > 1e-9
         OR TRIM(COALESCE(a.align_text_manual, '')) <> ''
         OR (TRIM(a.clean_text) <> '' AND a.clean_text <> replace(COALESCE(a.align_text_auto, ''), char(10), ' '))
       THEN 1 ELSE 0 END,
  CASE WHEN EXISTS (SELECT 1 FROM edit_change c WHERE c.entity = 'annotation' AND c.entity_id = a.id AND c.op = 'update'
                    AND json_extract(c.after, '$.tags') IS NOT NULL) THEN 1 ELSE 0 END,
  0, a.created_at, a.updated_at, 1
FROM annotation a
JOIN source s ON s.id = a.source_id
LEFT JOIN subtitle_line l ON l.id = a.subtitle_line_id
LEFT JOIN subtitle_version v ON v.id = a.subtitle_version_id
WHERE a.kind IN ('line', 'song') AND a.deleted = 0
  AND (a.subtitle_version_id IS NULL OR a.subtitle_version_id = s.current_subtitle_version_id)
  AND a.scope <> 'asset' AND a."end" > a.start;

-- 音效 → 音效提示，保留原 id
INSERT INTO sfx_hint(id, source_id, start, "end", text, origin, provenance, edited, deleted, created_at, updated_at, version)
SELECT a.id, a.source_id, a.start, a."end", a.clean_text,
  CASE WHEN a.subtitle_version_id IS NULL THEN 'manual' ELSE 'subtitle' END,
  CASE WHEN l.id IS NULL THEN NULL
       ELSE json_object('file', v.file_name, 'fingerprint', v.content_hash, 'line', l.line_no, 'raw', l.raw_text, 'importedAt', v.imported_at) END,
  CASE WHEN l.id IS NULL OR abs(a.start - l.start) > 1e-9 OR abs(a."end" - l."end") > 1e-9
         OR EXISTS (SELECT 1 FROM edit_change c WHERE c.entity = 'annotation' AND c.entity_id = a.id AND c.op = 'update'
                    AND (json_extract(c.after, '$.clean_text') IS NOT NULL OR json_extract(c.after, '$.raw_text') IS NOT NULL))
       THEN 1 ELSE 0 END,
  0, a.created_at, a.updated_at, 1
FROM annotation a
JOIN source s ON s.id = a.source_id
LEFT JOIN subtitle_line l ON l.id = a.subtitle_line_id
LEFT JOIN subtitle_version v ON v.id = a.subtitle_version_id
WHERE a.kind = 'sfx' AND a.deleted = 0
  AND (a.subtitle_version_id IS NULL OR a.subtitle_version_id = s.current_subtitle_version_id)
  AND a.scope <> 'asset' AND a."end" > a.start;

-- 区段标签（用户画的、提升来的）→ range_tag，保留原 id
INSERT INTO range_tag(id, source_id, scope, scope_role, scope_asset_id, start, "end", label, tags, deleted, created_at, updated_at, version)
SELECT a.id, a.source_id, a.scope, a.scope_role, a.scope_asset_id, a.start, a."end", a.clean_text, a.tags, 0, a.created_at, a.updated_at, 1
FROM annotation a
WHERE a.kind = 'tag' AND a.deleted = 0 AND a."end" > a.start;

-- 台词 / 音效标注上用户另加的非说话人标签 → 同作用域、同区间的区段标签（不丢）
INSERT INTO range_tag(id, source_id, scope, scope_role, scope_asset_id, start, "end", label, tags, deleted, created_at, updated_at, version)
SELECT lower(hex(randomblob(16))), a.source_id, a.scope, a.scope_role, a.scope_asset_id, a.start, a."end", '',
  (SELECT json_group_array(value) FROM (SELECT value FROM json_each(a.tags)
     WHERE value NOT LIKE 'character:%' AND value NOT LIKE 'participants:%' AND value NOT LIKE 'speaker-status:%' ORDER BY value)),
  0, a.created_at, a.updated_at, 1
FROM annotation a
JOIN source s ON s.id = a.source_id
WHERE a.kind IN ('line', 'song', 'sfx') AND a.deleted = 0 AND a."end" > a.start
  AND (a.subtitle_version_id IS NULL OR a.subtitle_version_id = s.current_subtitle_version_id)
  AND EXISTS (SELECT 1 FROM json_each(a.tags)
              WHERE value NOT LIKE 'character:%' AND value NOT LIKE 'participants:%' AND value NOT LIKE 'speaker-status:%');

-- ---------- 采样：来源记录、判定区间

UPDATE sample SET origin = json_object('kind', 'segment', 'segment', json_extract(origin, '$.annotation')), created_via = 'segment'
WHERE created_via = 'subtitle' AND json_extract(origin, '$.annotation') IN (SELECT id FROM text_segment);
UPDATE sample SET origin = json_object('kind', 'hint', 'hint', json_extract(origin, '$.annotation')), created_via = 'hint'
WHERE created_via = 'subtitle' AND json_extract(origin, '$.annotation') IN (SELECT id FROM sfx_hint);
UPDATE sample SET origin = json_object('kind', 'segment', 'segment', NULL), created_via = 'segment' WHERE created_via = 'subtitle';

-- 判定区间：没有的 = 选区（经资产映射分段插值到原片秒，统一到 1e-6）
UPDATE sample SET
  tag_judge_start = ROUND((
    SELECT json_extract(p.value, '$[1]') + (sample.start - json_extract(p.value, '$[0]'))
           * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
    FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
    WHERE a.id = sample.asset_id AND q.key = p.key + 1
      AND sample.start >= json_extract(p.value, '$[0]') - 1e-9 AND sample.start <= json_extract(q.value, '$[0]') + 1e-9
    ORDER BY p.key LIMIT 1), 6),
  tag_judge_end = ROUND((
    SELECT json_extract(p.value, '$[1]') + (sample."end" - json_extract(p.value, '$[0]'))
           * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
    FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
    WHERE a.id = sample.asset_id AND q.key = p.key + 1
      AND sample."end" >= json_extract(p.value, '$[0]') - 1e-9 AND sample."end" <= json_extract(q.value, '$[0]') + 1e-9
    ORDER BY p.key LIMIT 1), 6)
WHERE tag_judge_start IS NULL OR tag_judge_end IS NULL;

-- 新采样没给判定区间的 = 选区（所有建采样的路径都经过这里；从段 / 音效提示建的由调用方给出段 / 提示的区间）
CREATE TRIGGER sample_judge_default AFTER INSERT ON sample WHEN NEW.tag_judge_start IS NULL OR NEW.tag_judge_end IS NULL
BEGIN
  UPDATE sample SET
    tag_judge_start = ROUND((
      SELECT json_extract(p.value, '$[1]') + (NEW.start - json_extract(p.value, '$[0]'))
             * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
      FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
      WHERE a.id = NEW.asset_id AND q.key = p.key + 1
        AND NEW.start >= json_extract(p.value, '$[0]') - 1e-9 AND NEW.start <= json_extract(q.value, '$[0]') + 1e-9
      ORDER BY p.key LIMIT 1), 6),
    tag_judge_end = ROUND((
      SELECT json_extract(p.value, '$[1]') + (NEW."end" - json_extract(p.value, '$[0]'))
             * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
      FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
      WHERE a.id = NEW.asset_id AND q.key = p.key + 1
        AND NEW."end" >= json_extract(p.value, '$[0]') - 1e-9 AND NEW."end" <= json_extract(q.value, '$[0]') + 1e-9
      ORDER BY p.key LIMIT 1), 6)
  WHERE id = NEW.id;
END;

-- ---------- 分析：line:<标注>@<资产> → seg:<段>@<资产>；对应的段内容 = 段的区间 + 当时分析用的文本

UPDATE measure_run SET
  owner_id = 'seg:' || substr(owner_id, 6),
  seg_start = (SELECT t.start FROM text_segment t WHERE t.id = substr(measure_run.owner_id, 6, instr(substr(measure_run.owner_id, 6), '@') - 1)),
  seg_end = (SELECT t."end" FROM text_segment t WHERE t.id = substr(measure_run.owner_id, 6, instr(substr(measure_run.owner_id, 6), '@') - 1)),
  seg_text = json_extract(inputs, '$.text')
WHERE owner_type = 'asset_text' AND kind = 'alignment' AND owner_id LIKE 'line:%'
  AND substr(owner_id, 6, instr(substr(owner_id, 6), '@') - 1) IN (SELECT id FROM text_segment);
UPDATE measure_head SET owner_id = 'seg:' || substr(owner_id, 6)
WHERE owner_type = 'asset_text' AND kind = 'alignment' AND owner_id LIKE 'line:%'
  AND substr(owner_id, 6, instr(substr(owner_id, 6), '@') - 1) IN (SELECT id FROM text_segment);

-- 字幕采样上手输的台词与它那一行的文本相同：手输文本作废，分析改挂到那一行（目标本来就是那一行 ± 扩展）
CREATE TEMP TABLE m_same AS
SELECT DISTINCT r.owner_id AS unit, 'seg:' || json_extract(s.origin, '$.segment') || '@' || s.asset_id AS seg_unit, t.start AS a, t."end" AS b
FROM sample s
JOIN text_segment t ON t.id = json_extract(s.origin, '$.segment')
JOIN measure_run r ON r.owner_type = 'asset_text' AND r.kind = 'alignment' AND r.owner_id LIKE 'typed:%' AND r.asset_id = s.asset_id
  AND abs(r.range_start - s.start) < 1e-6 AND abs(r.range_end - s."end") < 1e-6
WHERE TRIM(COALESCE(s.align_text_manual, '')) <> '' AND TRIM(s.align_text_manual) = TRIM(t.text);
INSERT OR IGNORE INTO measure_head(owner_type, owner_id, kind, run_id, version)
SELECT 'asset_text', m.seg_unit, h.kind, h.run_id, h.version FROM measure_head h JOIN m_same m ON m.unit = h.owner_id JOIN measure_run r ON r.id = h.run_id
ORDER BY r.manual DESC, r.created_at DESC, r.rowid DESC;
UPDATE measure_run SET
  owner_id = (SELECT seg_unit FROM m_same WHERE unit = measure_run.owner_id LIMIT 1),
  seg_start = (SELECT a FROM m_same WHERE unit = measure_run.owner_id LIMIT 1),
  seg_end = (SELECT b FROM m_same WHERE unit = measure_run.owner_id LIMIT 1),
  seg_text = json_extract(inputs, '$.text')
WHERE owner_id IN (SELECT unit FROM m_same);
DELETE FROM measure_head WHERE owner_id IN (SELECT unit FROM m_same);
UPDATE sample SET align_text_manual = NULL WHERE TRIM(COALESCE(align_text_manual, '')) <> '' AND json_extract(origin, '$.kind') = 'segment'
  AND TRIM(align_text_manual) = (SELECT TRIM(t.text) FROM text_segment t WHERE t.id = json_extract(sample.origin, '$.segment'));

-- 其余的手输台词（typed: 单元与采样上的手输文本）→ 手输段：按（资产、选区）去重，新 id 一次生成
CREATE TEMP TABLE m_typed AS
SELECT r.asset_id, r.range_start AS a, r.range_end AS b,
  (SELECT json_extract(r2.inputs, '$.text') FROM measure_run r2 WHERE r2.owner_id = r.owner_id AND r2.status = 'ok'
   ORDER BY (r2.id IN (SELECT run_id FROM measure_head)) DESC, r2.created_at DESC, r2.rowid DESC LIMIT 1) AS text
FROM measure_run r WHERE r.owner_type = 'asset_text' AND r.kind = 'alignment' AND r.owner_id LIKE 'typed:%'
GROUP BY r.owner_id;
INSERT INTO m_typed(asset_id, a, b, text)
SELECT s.asset_id, s.start, s."end", TRIM(s.align_text_manual) FROM sample s
WHERE TRIM(COALESCE(s.align_text_manual, '')) <> ''
  AND NOT EXISTS (SELECT 1 FROM m_typed t WHERE t.asset_id = s.asset_id AND abs(t.a - s.start) < 1e-6 AND abs(t.b - s."end") < 1e-6);
CREATE TEMP TABLE m_seg AS
SELECT lower(hex(randomblob(16))) AS seg, asset_id, a, b, text FROM (
  SELECT asset_id, ROUND(a, 6) AS a, ROUND(b, 6) AS b, MIN(text) AS text FROM m_typed
  WHERE text IS NOT NULL AND TRIM(text) <> '' GROUP BY asset_id, ROUND(a, 6), ROUND(b, 6));
INSERT INTO text_segment(id, source_id, start, "end", text, speakers, origin, provenance, edited, speaker_edited, deleted, created_at, updated_at, version)
SELECT m.seg, x.source_id, x.sa, x.sb, m.text, '[]', 'typed', NULL, 1, 0, 0, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 1
FROM m_seg m JOIN (
  SELECT m2.seg, a.source_id,
    ROUND((SELECT json_extract(p.value, '$[1]') + (m2.a - json_extract(p.value, '$[0]'))
                  * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
           FROM json_each(a.mapping) p, json_each(a.mapping) q
           WHERE q.key = p.key + 1 AND m2.a >= json_extract(p.value, '$[0]') - 1e-9 AND m2.a <= json_extract(q.value, '$[0]') + 1e-9
           ORDER BY p.key LIMIT 1), 6) AS sa,
    ROUND((SELECT json_extract(p.value, '$[1]') + (m2.b - json_extract(p.value, '$[0]'))
                  * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
           FROM json_each(a.mapping) p, json_each(a.mapping) q
           WHERE q.key = p.key + 1 AND m2.b >= json_extract(p.value, '$[0]') - 1e-9 AND m2.b <= json_extract(q.value, '$[0]') + 1e-9
           ORDER BY p.key LIMIT 1), 6) AS sb
  FROM m_seg m2 JOIN sound_asset a ON a.id = m2.asset_id
) x ON x.seg = m.seg
WHERE x.sb > x.sa;
INSERT OR IGNORE INTO measure_head(owner_type, owner_id, kind, run_id, version)
SELECT 'asset_text', 'seg:' || m.seg || '@' || r.asset_id, h.kind, h.run_id, h.version
FROM measure_head h JOIN measure_run r ON r.id = h.run_id
JOIN m_seg m ON m.asset_id = r.asset_id AND abs(m.a - r.range_start) < 1e-6 AND abs(m.b - r.range_end) < 1e-6
WHERE h.owner_type = 'asset_text' AND h.owner_id LIKE 'typed:%' AND m.seg IN (SELECT id FROM text_segment)
ORDER BY r.manual DESC, r.created_at DESC, r.rowid DESC;
UPDATE measure_run SET
  owner_id = 'seg:' || (SELECT m.seg FROM m_seg m WHERE m.asset_id = measure_run.asset_id AND abs(m.a - measure_run.range_start) < 1e-6
                         AND abs(m.b - measure_run.range_end) < 1e-6 LIMIT 1) || '@' || asset_id,
  seg_start = (SELECT t.start FROM m_seg m JOIN text_segment t ON t.id = m.seg WHERE m.asset_id = measure_run.asset_id
               AND abs(m.a - measure_run.range_start) < 1e-6 AND abs(m.b - measure_run.range_end) < 1e-6 LIMIT 1),
  seg_end = (SELECT t."end" FROM m_seg m JOIN text_segment t ON t.id = m.seg WHERE m.asset_id = measure_run.asset_id
             AND abs(m.a - measure_run.range_start) < 1e-6 AND abs(m.b - measure_run.range_end) < 1e-6 LIMIT 1),
  seg_text = json_extract(inputs, '$.text')
WHERE owner_type = 'asset_text' AND kind = 'alignment' AND owner_id LIKE 'typed:%'
  AND EXISTS (SELECT 1 FROM m_seg m JOIN text_segment t ON t.id = m.seg WHERE m.asset_id = measure_run.asset_id
              AND abs(m.a - measure_run.range_start) < 1e-6 AND abs(m.b - measure_run.range_end) < 1e-6);
UPDATE sample SET align_text_manual = NULL WHERE TRIM(COALESCE(align_text_manual, '')) <> '';

-- 没有落到任何段上的旧分析（非当前字幕版本的行、没有文本的手输单元）：先删头再删版本
DELETE FROM measure_head WHERE owner_type = 'asset_text' AND kind = 'alignment' AND owner_id NOT LIKE 'seg:%';
DELETE FROM measure_run WHERE owner_type = 'asset_text' AND kind = 'alignment' AND owner_id NOT LIKE 'seg:%'
  AND id NOT IN (SELECT run_id FROM measure_head);

DROP TABLE m_same;
DROP TABLE m_typed;
DROP TABLE m_seg;

-- ---------- 编辑历史的屏障：之前的修改（涉及旧的标注 / 字幕版本）不再可撤销
INSERT INTO edit(id, seq, created_at, label_code, label_args)
SELECT 'barrier-0012', (SELECT COALESCE(MAX(seq), 0) + 1 FROM edit), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 'barrier', '{}'
WHERE EXISTS (SELECT 1 FROM edit);
