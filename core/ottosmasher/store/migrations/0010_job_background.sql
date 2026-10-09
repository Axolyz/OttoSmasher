-- 阶段 7 验收（所有者 2026-10-08）：检索的准备工作自动在后台做（语音检索索引、F0）。
-- 后台任务排在用户提交的任务后面：同一通道里先启动 background = 0 的，再按提交时间。
ALTER TABLE job ADD COLUMN background INTEGER NOT NULL DEFAULT 0;
