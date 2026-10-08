// 原片行与查看器用的小工具。所有者 2026-10-07：原片只有一种（导入时是否直接建全长采样只是一个选项），
// 列表与查看器只按内容（有没有画面、有没有字幕）调整，不按入口或时长分类。
import type { SourceRow } from "../api/types";
import { clock } from "../format";
import { t } from "../i18n";

/** 时长：一分钟以内写“0.17 秒”，更长的写 0:00 时钟 */
export function durationText(d: number): string {
  return d < 60 ? t("format.sec", { v: d.toFixed(2) }) : clock(d, 0);
}

/** 文件相对导入根文件夹的子目录（“se/battle”）；不在根下或就在根下 → 空 */
export function relDir(r: Pick<SourceRow, "path" | "import_root">): string {
  if (!r.import_root) return "";
  const root = r.import_root.replace(/[\\/]+$/, "");
  const dir = r.path.replace(/[\\/][^\\/]*$/, "");
  if (!dir.startsWith(`${root}/`) && !dir.startsWith(`${root}\\`)) return "";
  return dir.slice(root.length + 1).replace(/\\/g, "/");
}

/** 没有字幕可看：没关联字幕文件、也没导入过标记 */
export function noSubtitles(r: Pick<SourceRow, "subtitle_path" | "counts">): boolean {
  return !r.subtitle_path && !r.counts?.hasMarkers;
}
