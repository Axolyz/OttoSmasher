// 程序、工作区、运行库的位置（规格 13 §13.3.1、16 R23.1：三者分离，支持中文和空格路径）。
// 源码运行：仓库；发布版（阶段 10，2026-10-30 只做 macOS）：.app 的 Contents/Resources，布局见 tools/package_mac.py。
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { app } from "electron";

export interface Paths {
  repo: string | null; // 开发期仓库根目录；发布版为 null
  /** 程序自带文件的根目录：源码运行 = 仓库，发布版 = Contents/Resources（Python 侧的 OTTO_RESOURCES） */
  resources: string;
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
    // 发布版：Resources/app 是应用代码（out/ 与 app/ 的必要部分），其余随包文件与它并列
    const res = process.resourcesPath;
    const code = join(res, "app");
    return {
      repo: null,
      resources: res,
      workspace: process.env.OTTO_WORKSPACE ?? join(homedir(), "Documents", "OttoSmasher Workspace"),
      python: join(res, "python", "bin", "python3"),
      supportDir: join(res, "third_party", "model-support"),
      rendererIndex: join(code, "out", "renderer", "index.html"),
      preload: join(code, "out", "preload", "preload.cjs"),
      locales: join(code, "app", "renderer", "i18n", "locales"),
    };
  }
  const python = process.platform === "win32" ? join(repo, ".venv", "Scripts", "python.exe") : join(repo, ".venv", "bin", "python");
  return {
    repo,
    resources: repo,
    workspace: process.env.OTTO_WORKSPACE ?? join(repo, "dev-workspace"),
    python,
    supportDir: process.env.OTTO_MODEL_SUPPORT_DIR,
    rendererIndex: join(repo, "out", "renderer", "index.html"),
    preload: join(repo, "out", "preload", "preload.cjs"),
    locales: join(repo, "app", "renderer", "i18n", "locales"),
  };
}
