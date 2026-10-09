-- 0013：删掉旧的标注与字幕版本（所有者 2026-10-09「原片上的四类对象」：文本层的段 / 音效提示 / 区段标签取代标注，取消字幕版本）。
-- 0012 已经把当前版本的标注迁成段、音效提示与区段标签，分析改挂到“段 + 资产”，采样的手输台词迁成段；这里只删已经没人读写的旧表与旧列。
-- 迁移在一个事务里、外键开着：先删引用别人的表（annotation_revision → annotation → subtitle_line → subtitle_version），
-- 再删两列（都没有索引、触发器、视图或外键引用它们）。旧编辑历史里的 annotation 修改在 0012 的屏障之前，不会再被撤销。
DROP TABLE annotation_revision;
DROP TABLE annotation;
DROP TABLE subtitle_line;
DROP TABLE subtitle_version;
ALTER TABLE sample DROP COLUMN align_text_manual;
ALTER TABLE source DROP COLUMN current_subtitle_version_id;
