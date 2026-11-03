// 用 Electron 的头文件编译 mpv 渲染桥（node-gyp）。头文件缓存在仓库内 .cache/node-gyp（AGENTS.md §4）。
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL("..", import.meta.url));
const electronVersion = require("electron/package.json").version;
const python = process.platform === "win32" ? join(root, ".venv", "Scripts", "python.exe") : join(root, ".venv", "bin", "python");
const nodeGyp = join(root, "node_modules", "node-gyp", "bin", "node-gyp.js");

// macOS：命令行工具里可能装着与链接器不匹配的测试版 SDK（例如 27.0 beta），只给本次编译挑一个正式版 SDK
const env = { ...process.env, npm_config_cache: join(root, ".cache", "npm") };
if (process.platform === "darwin" && !process.env.SDKROOT) {
  const dir = "/Library/Developer/CommandLineTools/SDKs";
  if (existsSync(dir)) {
    const stable = readdirSync(dir)
      .filter((n) => /^MacOSX\d+\.\d+\.sdk$/.test(n))
      .map((n) => ({ n, v: n.match(/(\d+)\.(\d+)/).slice(1).map(Number) }))
      .filter((x) => x.v[0] <= 26)
      .sort((a, b) => b.v[0] - a.v[0] || b.v[1] - a.v[1])[0];
    if (stable) env.SDKROOT = join(dir, stable.n);
  }
}

execFileSync(
  process.execPath,
  [
    nodeGyp,
    "rebuild",
    `--target=${electronVersion}`,
    "--dist-url=https://electronjs.org/headers",
    `--arch=${process.arch}`,
    `--devdir=${join(root, ".cache", "node-gyp")}`,
    `--python=${python}`,
  ],
  { cwd: join(root, "app", "native", "mpv-bridge"), stdio: "inherit", env },
);
console.log("mpv-bridge built for Electron", electronVersion, env.SDKROOT ? `(SDK ${env.SDKROOT})` : "");
