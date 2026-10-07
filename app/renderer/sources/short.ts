// 短音频原片（UI_PLAN §4「短音频原片的查看器」、ARCHITECTURE §4.10）：没有视频流、没有字幕（文件和标记都没有），
// 并且是从采样库导入的或不超过 60 秒——查看器不显示空的台本与准备清单，只显示画面（若绑定）、波形和它的采样。
import type { SourceRow } from "../api/types";

export const SHORT_MAX_SECONDS = 60;

export function isShort(r: SourceRow): boolean {
  return !r.has_video && !r.subtitle_path && !r.counts?.hasMarkers && (r.import_root != null || r.duration <= SHORT_MAX_SECONDS);
}

/** 文件相对导入根文件夹的子目录（“se/battle”）；不在根下或就在根下 → 空 */
export function relDir(r: Pick<SourceRow, "path" | "import_root">): string {
  if (!r.import_root) return "";
  const root = r.import_root.replace(/[\\/]+$/, "");
  const dir = r.path.replace(/[\\/][^\\/]*$/, "");
  if (!dir.startsWith(`${root}/`) && !dir.startsWith(`${root}\\`)) return "";
  return dir.slice(root.length + 1).replace(/\\/g, "/");
}
