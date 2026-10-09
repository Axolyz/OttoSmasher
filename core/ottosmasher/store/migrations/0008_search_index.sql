-- 阶段 7：语音检索索引（规格 09 §9.6.5、ARCHITECTURE §4.6；ROADMAP L24 节奏分析落库）——可清理、随时可重建的派生数据。
-- 每采样一行：失效键（采样范围与节奏参数、语音测量头、F0 测量头、文件快照、台词标注、惩罚度、算法版本）+ msgpack 编码的索引
-- （逐块属性按列 + 整句与各语段的卡拍方案输入）。status = 'none' 表示分析了也建不出（没有音块、文件缺失……），reason 是错误码。
-- 检索只读这张表（不读波形、不推理）；行由「准备检索索引」任务构建，Core 采纳时核对失效键仍然相同。
CREATE TABLE speech_index (
  sample_id TEXT PRIMARY KEY REFERENCES sample(id) ON DELETE CASCADE,
  input_key TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok', 'none')),
  reason TEXT,
  data BLOB,
  built_at TEXT NOT NULL
);
-- 固定结果按创建时间列出、打开的在前
CREATE INDEX IF NOT EXISTS result_set_open ON result_set(closed, created_at);
