-- 字幕说话人逐行读（所有者 2026-10-31【基线变更】）：原文里有标注，但没法确定每一行是谁说的，所以没记说话人
ALTER TABLE text_segment ADD COLUMN speakers_withheld INTEGER NOT NULL DEFAULT 0;
