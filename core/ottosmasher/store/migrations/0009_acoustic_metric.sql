-- 阶段 7：单音声学指标（规格 10 §10.3、16 R16）——随声音内容缓存，内容变了失效。
-- 每采样一行；有效 = 资产、范围、存储签名（文件快照）与算法版本都等于现在的（在 SQL 里核对，筛选是即时浏览、可以分页）。
-- metrics 是 JSON：指标名 → 数值或 null（未知）。由「后台准备当前范围指标」任务写入（先补测 F0，再解码算指标）。
CREATE TABLE acoustic_metric (
  sample_id TEXT PRIMARY KEY REFERENCES sample(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL,
  start REAL NOT NULL,
  "end" REAL NOT NULL,
  storage_sig TEXT NOT NULL,
  algo TEXT NOT NULL,
  metrics TEXT NOT NULL,
  built_at TEXT NOT NULL
);
