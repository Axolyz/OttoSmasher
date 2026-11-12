import { useApp } from "./store";

// Core 本地标签上限 200 字符，包含前缀。
const PREFIX = "project:";
export const isProjectTag = (tag: string) => tag.startsWith(PREFIX);
export const PROJECT_NAME_LIMIT = 200 - PREFIX.length;
export const projectTag = (name: string | null | undefined) => (name ? PREFIX + name : undefined);

// DECISIONS §8：桌面自动归类与 CLI 的 useCurrentProject 各自独立。
export function autoProjectTag(state: ReturnType<typeof useApp.getState>): string | undefined {
  return state.projectAutoJoin ? projectTag(state.currentProject) : undefined;
}

export function autoProjectTags(): string[] {
  const tag = autoProjectTag(useApp.getState());
  return tag ? [tag] : [];
}
