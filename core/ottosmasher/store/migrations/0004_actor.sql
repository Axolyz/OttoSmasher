-- ROADMAP L1 / QUESTIONS Q23（所有者 2026-10-07 同意）：编辑记录、任务、新建的原片 / 资产 / 采样记录“谁做的”——
-- 用户（界面）/ 脚本 / agent，加会话 ID。界面暂不显示；阶段 11 的脚本修改能按来源筛选、整批撤回（ARCHITECTURE §15）。
-- 已有数据都记为 user。新行由 Core 连接上的临时触发器按当前请求的来源填写（core/actor.py）。
ALTER TABLE edit ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent'));
ALTER TABLE edit ADD COLUMN actor_session TEXT;
ALTER TABLE job ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent'));
ALTER TABLE job ADD COLUMN actor_session TEXT;
ALTER TABLE source ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent'));
ALTER TABLE source ADD COLUMN actor_session TEXT;
ALTER TABLE sound_asset ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent'));
ALTER TABLE sound_asset ADD COLUMN actor_session TEXT;
ALTER TABLE sample ADD COLUMN actor_kind TEXT NOT NULL DEFAULT 'user' CHECK (actor_kind IN ('user', 'script', 'agent'));
ALTER TABLE sample ADD COLUMN actor_session TEXT;
