-- 阶段 4.5：测量记录也记“谁做的”（ROADMAP L1：新增“新建对象”的表要加同样两列并登记到 core/actor.py 的 TABLES）。
ALTER TABLE measure_run ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent'));
ALTER TABLE measure_run ADD COLUMN actor_session TEXT;
-- 逐条结果（规格 08 §8.4「语音分析结果」表）按任务查
CREATE INDEX IF NOT EXISTS job_item_target ON job_item(target);
-- 原片视口按资产读所有测量（08 §8.8）
CREATE INDEX IF NOT EXISTS measure_run_asset ON measure_run(asset_id, kind);
