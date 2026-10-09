// 导出文件名里的固定词（规格 12 §12.1：随界面语言；Core 按资产角色与加工方式选用）。
import { t } from "./i18n";

export function exportWords(): Record<string, string> {
  return {
    original: t("track.original"),
    vocal: t("role.vocal"),
    sfx: t("role.sfx"),
    flatten: t("track.flatten"),
    reimport: t("track.reimport"),
    fragment: t("export.fragment"),
    local: t("naming.local"),
    stretch: t("export.stretch"),
    video: t("export.video"),
    originalSpeed: t("export.originalSpeed"),
  };
}
