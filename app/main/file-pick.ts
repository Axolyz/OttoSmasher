// 打开文件对话框的选项（纯函数，好测）。Windows 的系统对话框不能同时选文件和文件夹（所有者 2026-11-04 实测只能选文件夹），
// 所以导入先问选哪种；macOS 虽然能同时选，也走同样的流程，两个平台表现一致（所有者 2026-11-04）。
export type PickKind = "media" | "media-one" | "subtitle" | "import" | "folder" | "picture" | "reimport" | "models";
export type PickMode = "files" | "folder";
export type PickProperty = "openFile" | "openDirectory" | "multiSelections" | "createDirectory";

export function needsChoice(kind: PickKind): boolean {
  return kind === "import" || kind === "models";
}

export function pickProperties(kind: PickKind, mode?: PickMode): PickProperty[] {
  if (needsChoice(kind)) return mode === "folder" ? ["openDirectory", "multiSelections"] : ["openFile", "multiSelections"];
  if (kind === "folder") return ["openDirectory", "createDirectory"];
  if (kind === "media") return ["openFile", "multiSelections"];
  return ["openFile"];
}
