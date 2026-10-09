-- 所有者 2026-10-08【基线变更，细化 D41】：语音分析只挂在“声音资产 + 文本单元”上，不属于任何采样。
-- 文本单元 = 一段有文本的音轨区间：字幕的一行（line:<标注>@<资产>），或用户给一段选区手输的台词（typed:<资产>@<起>-<止>）。
-- 当前版本、历史版本、人工修正都属于这句；采样只按规则读取覆盖它的文本单元（core/units.py）。
-- 归属类型沿用 asset_text（“资产 + 文本”）；旧的 sample 归属按当时用的文本迁到对应的文本单元。

-- 音素跨度（首个到末个非停顿音素；资产局部秒）：采样按它判断读哪些句、是否只读到一部分（◐）
ALTER TABLE measure_run ADD COLUMN span_start REAL;
ALTER TABLE measure_run ADD COLUMN span_end REAL;

UPDATE measure_run SET
  span_start = (SELECT MIN(json_extract(p.value, '$.start')) FROM json_each(measure_run.result, '$.phones') p WHERE json_extract(p.value, '$.label') <> 'pau'),
  span_end = (SELECT MAX(json_extract(p.value, '$.end')) FROM json_each(measure_run.result, '$.phones') p WHERE json_extract(p.value, '$.label') <> 'pau')
WHERE kind = 'alignment' AND status = 'ok' AND result IS NOT NULL;

-- 旧的“资产选区 + 文字区段”归属（区间哈希）→ 手输单元
UPDATE measure_head SET owner_id = (SELECT 'typed:' || r.asset_id || '@' || printf('%.6f-%.6f', r.range_start, r.range_end) FROM measure_run r WHERE r.id = measure_head.run_id)
WHERE owner_type = 'asset_text' AND kind = 'alignment';
UPDATE measure_run SET owner_id = 'typed:' || asset_id || '@' || printf('%.6f-%.6f', range_start, range_end)
WHERE owner_type = 'asset_text' AND kind = 'alignment';

-- 采样归属 → 文本单元：用字幕行文本做的（字幕采样）→ 这一行在该资产上的单元；其余（手输台词、采样已删）→ 手输单元（采样选区）
UPDATE measure_run SET
  owner_type = 'asset_text',
  owner_id = COALESCE(
    (SELECT 'line:' || json_extract(s.origin, '$.annotation') || '@' || measure_run.asset_id FROM sample s
      WHERE s.id = measure_run.owner_id AND json_extract(s.origin, '$.kind') = 'subtitle' AND json_extract(s.origin, '$.annotation') IS NOT NULL
        AND json_extract(measure_run.inputs, '$.textSource') IN ('line-auto', 'line-manual', 'snapshot')),
    'typed:' || asset_id || '@' || printf('%.6f-%.6f', range_start, range_end))
WHERE owner_type = 'sample' AND kind = 'alignment';

-- 当前头跟着它指向的版本走；同一句被几个采样各分析过 → 人工版本优先，再取最新的
INSERT OR IGNORE INTO measure_head(owner_type, owner_id, kind, run_id, version)
SELECT 'asset_text', r.owner_id, h.kind, h.run_id, h.version FROM measure_head h JOIN measure_run r ON r.id = h.run_id
WHERE h.owner_type = 'sample' AND h.kind = 'alignment'
ORDER BY r.manual DESC, r.created_at DESC, r.rowid DESC;
DELETE FROM measure_head WHERE owner_type = 'sample';

CREATE INDEX IF NOT EXISTS measure_head_run ON measure_head(run_id);
CREATE INDEX IF NOT EXISTS measure_run_span ON measure_run(asset_id, kind, span_start);
