-- 阶段 2.2：原片路径键（规格 04 §4.6：同一路径重复登记返回已有原片）。
-- path_key = 绝对路径经 Unicode NFC 与平台大小写规范化（Windows 不区分大小写），唯一。
ALTER TABLE source ADD COLUMN path_key TEXT;
CREATE UNIQUE INDEX source_path_key ON source(path_key);
