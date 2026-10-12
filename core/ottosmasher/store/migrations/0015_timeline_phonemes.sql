-- 0015：音素回到原素材时间线、去掉父采样（所有者 2026-10-12，docs/QUESTIONS.md「音素回到原素材时间线、去掉父采样」）。
-- 旧数据不兼容（所有者：“旧数据完全不必兼容，可以直接清空”）：旧的语音分析直接删掉（键与时间的存法都变了），要重新语音分析；
-- 迁移在一个事务里、外键开着。

-- ---------- 音轨：建音轨时抄下的两个事实（core/units.py）
-- reimport_id：它是不是从某个回导成品来的（回导成品 = 自己；分离 / 拉平 = 抄输入音轨的；其余为空）。音素按“段 + 原素材”或“段 + 回导成品”各一份。
-- from_separation：它是不是从分离声部来的（分离 = 1；其余抄输入音轨的；原混音 = 0）。没开任何角色的音轨靠它区分“混音”与“没标角色的声部”。
ALTER TABLE sound_asset ADD COLUMN reimport_id TEXT;
ALTER TABLE sound_asset ADD COLUMN from_separation INTEGER NOT NULL DEFAULT 0;
WITH RECURSIVE re(id, rid) AS (
  SELECT id, id FROM sound_asset WHERE origin = 'reimport'
  UNION SELECT a.id, re.rid FROM sound_asset a JOIN re ON a.input_asset_id = re.id WHERE a.origin <> 'reimport'
) UPDATE sound_asset SET reimport_id = (SELECT rid FROM re WHERE re.id = sound_asset.id) WHERE id IN (SELECT id FROM re);
WITH RECURSIVE sep(id) AS (
  SELECT id FROM sound_asset WHERE origin = 'separation'
  UNION SELECT a.id FROM sound_asset a JOIN sep ON a.input_asset_id = sep.id
) UPDATE sound_asset SET from_separation = 1 WHERE id IN (SELECT id FROM sep);

CREATE TRIGGER sound_asset_lineage AFTER INSERT ON sound_asset
BEGIN
  UPDATE sound_asset SET
    reimport_id = CASE WHEN NEW.origin = 'reimport' THEN NEW.id ELSE (SELECT i.reimport_id FROM sound_asset i WHERE i.id = NEW.input_asset_id) END,
    from_separation = CASE WHEN NEW.origin = 'separation' THEN 1 ELSE COALESCE((SELECT i.from_separation FROM sound_asset i WHERE i.id = NEW.input_asset_id), 0) END
  WHERE id = NEW.id;
END;

-- ---------- 采样：原素材起止（原素材秒，不可变；排序、相关采样、采样车道、返回原素材都用它）
-- 与 0012 的判定区间默认值同一个分段插值；没有映射的资产按局部秒。
ALTER TABLE sample ADD COLUMN src_start REAL;
ALTER TABLE sample ADD COLUMN src_end REAL;

UPDATE sample SET
  src_start = COALESCE(ROUND((
    SELECT json_extract(p.value, '$[1]') + (sample.start - json_extract(p.value, '$[0]'))
           * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
    FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
    WHERE a.id = sample.asset_id AND q.key = p.key + 1
      AND sample.start >= json_extract(p.value, '$[0]') - 1e-9 AND sample.start <= json_extract(q.value, '$[0]') + 1e-9
    ORDER BY p.key LIMIT 1), 6), sample.start),
  src_end = COALESCE(ROUND((
    SELECT json_extract(p.value, '$[1]') + (sample."end" - json_extract(p.value, '$[0]'))
           * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
    FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
    WHERE a.id = sample.asset_id AND q.key = p.key + 1
      AND sample."end" >= json_extract(p.value, '$[0]') - 1e-9 AND sample."end" <= json_extract(q.value, '$[0]') + 1e-9
    ORDER BY p.key LIMIT 1), 6), sample."end");

CREATE TRIGGER sample_source_range AFTER INSERT ON sample
BEGIN
  UPDATE sample SET
    src_start = COALESCE(ROUND((
      SELECT json_extract(p.value, '$[1]') + (NEW.start - json_extract(p.value, '$[0]'))
             * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
      FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
      WHERE a.id = NEW.asset_id AND q.key = p.key + 1
        AND NEW.start >= json_extract(p.value, '$[0]') - 1e-9 AND NEW.start <= json_extract(q.value, '$[0]') + 1e-9
      ORDER BY p.key LIMIT 1), 6), NEW.start),
    src_end = COALESCE(ROUND((
      SELECT json_extract(p.value, '$[1]') + (NEW."end" - json_extract(p.value, '$[0]'))
             * (json_extract(q.value, '$[1]') - json_extract(p.value, '$[1]')) / (json_extract(q.value, '$[0]') - json_extract(p.value, '$[0]'))
      FROM sound_asset a, json_each(a.mapping) p, json_each(a.mapping) q
      WHERE a.id = NEW.asset_id AND q.key = p.key + 1
        AND NEW."end" >= json_extract(p.value, '$[0]') - 1e-9 AND NEW."end" <= json_extract(q.value, '$[0]') + 1e-9
      ORDER BY p.key LIMIT 1), 6), NEW."end")
  WHERE id = NEW.id;
END;

CREATE INDEX sample_src ON sample(src_start);

-- ---------- 去掉父采样（只留创建方式）；拉平采样的创建方式不再记“从哪个采样”
ALTER TABLE sample DROP COLUMN parent_sample_id;
ALTER TABLE sample DROP COLUMN parent_label;
UPDATE sample SET origin = json_remove(origin, '$.from') WHERE json_valid(origin) AND json_extract(origin, '$.kind') = 'flatten';

-- ---------- 旧的语音分析：键（段 + 音轨 → 段 + 原素材 / 回导成品）与时间（音轨局部秒 → 原素材秒）都变了，直接删掉
DELETE FROM measure_head WHERE owner_type = 'asset_text';
DELETE FROM measure_run WHERE owner_type = 'asset_text';
