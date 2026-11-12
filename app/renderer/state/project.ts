import { useApp } from "./store";

// Core 本地标签上限 200 字符，包含前缀。
const PREFIX = "project:";
export const PROJECT_NAME_LIMIT = 200 - PREFIX.length;
export const projectTag = (name: string | null | undefined) => (name ? PREFIX + name : undefined);

export function currentProjectTags(): string[] {
  const tag = projectTag(useApp.getState().currentProject);
  return tag ? [tag] : [];
}
