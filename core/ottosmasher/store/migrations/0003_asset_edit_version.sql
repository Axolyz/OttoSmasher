-- 阶段 3.4：资产的角色可编辑（规格 04 §4.2.3；统一编辑通道要求对象带版本）。
-- 资产本身仍不可变（时间关系、文件、映射不改）；version / updated_at 只随角色修改递增。
ALTER TABLE sound_asset ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE sound_asset ADD COLUMN updated_at TEXT;
