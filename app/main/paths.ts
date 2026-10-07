// 程序、工作区、运行库的位置（规格 13 §13.3.1、16 R23.1：三者分离，支持中文和空格路径）。
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { app } from "electron";

export interface Paths {
  repo: string | null; // 开发期仓库根目录；发布版为 null
  workspace: string;
  python: string;
  supportDir: string | undefined;
  rendererIndex: string;
  preload: string;
  locales: string;
}

export function resolvePaths(): Paths {
  // 打包前：out/main/main.cjs → 仓库根目录在上两级
  const repo = resolve(__dirname, "..", "..");
  const isDev = !app.isPackaged && existsSync(join(repo, "pyproject.toml"));
  if (!isDev) {
    // 发布版的布局在阶段 10 定；这里先明确报错而不是猜
    throw new Error("packaged layout not implemented yet (stage 10)");
  }
  const python = process.platform === "win32" ? join(repo, ".venv", "Scripts", "python.exe") : join(repo, ".venv", "bin", "python");
  return {
    repo,
    workspace: process.env.OTTO_WORKSPACE ?? join(repo, "dev-workspace"),
    python,
    supportDir: process.env.OTTO_MODEL_SUPPORT_DIR,
    rendererIndex: join(repo, "out", "renderer", "index.html"),
    preload: join(repo, "out", "preload", "preload.cjs"),
    locales: join(repo, "app", "renderer", "i18n", "locales"),
  };
}
