-- 阶段 6：逐采样的节奏参数（规格 09 §9.3、§9.4、03 §3.3「分组与停顿」「人工占格」）。
-- JSON：{"sensitivity", "segmentThreshold", "manual": {"run", "splits", "cells", "cuts", "merges"}}；
-- 新采样创建时写入设置里的默认值（之后改设置不影响已有采样）；为空 = 内置默认（阶段 6 之前建的采样）。
-- 人工项（拆点、占格、手动切分/合并）绑定当时的分析版本（run），分析换了不自动套用。经编辑通道修改（可撤销）。
ALTER TABLE sample ADD COLUMN rhythm TEXT;
-- 新采样取设置里的默认值（停顿灵敏度、语段阈值）：所有新建采样的路径（截取、字幕采样、导入、拉平……）都经过这里。
-- 设置没存过时用内置默认（与 core/settings.py 一致：1.0、0.28）。
CREATE TRIGGER sample_rhythm_defaults AFTER INSERT ON sample WHEN NEW.rhythm IS NULL
BEGIN
  UPDATE sample SET rhythm = json_object(
    'sensitivity', COALESCE((SELECT json_extract(value, '$') FROM setting WHERE key = 'analysis.pause_sensitivity'), 1.0),
    'segmentThreshold', COALESCE((SELECT json_extract(value, '$') FROM setting WHERE key = 'analysis.segment_threshold'), 0.28),
    'manual', json_object('run', NULL, 'splits', json_array(), 'cells', json_object(), 'cuts', json_array(), 'merges', json_array())
  ) WHERE id = NEW.id;
END;
