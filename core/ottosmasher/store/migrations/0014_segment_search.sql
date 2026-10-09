-- 阶段 8：文字搜索（规格 07 §7.1）——采样读到的段的原文与读音。
-- 每段一行：text = 算的时候的段文本，dict_version = 用户辞典版本；两者有一个和现在不同就重算（检索前补齐，资料变化后在后台补）。
-- norm = NFKC、小写、去掉标点/空白/控制字符；reading = 平假名读音（pyopenjtalk-plus + 用户辞典）再按 norm 规范化。可重建，不是测量。
CREATE TABLE segment_search (
  segment_id TEXT PRIMARY KEY REFERENCES text_segment(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  dict_version TEXT NOT NULL,
  norm TEXT NOT NULL,
  reading TEXT NOT NULL
);
