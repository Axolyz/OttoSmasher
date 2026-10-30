-- L50（2026-10-30）：排队中的任务可以提到同一通道的最前面；最近提的在前，之后才是用户提交的、后台的。
-- promote_seq：第几次“提到最前”（递增；同一毫秒里连提两次也分得清先后）
ALTER TABLE job ADD COLUMN promote_seq INTEGER;
