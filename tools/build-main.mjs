// 打包 Electron 主进程与 preload（esbuild）。preload 在沙箱里运行，必须是单文件 CommonJS。
import { build } from "esbuild";

const common = { bundle: true, platform: "node", target: "node24", sourcemap: true, external: ["electron"], logLevel: "warning" };
await build({ ...common, entryPoints: ["app/main/main.ts"], outfile: "out/main/main.cjs", format: "cjs", loader: { ".json": "json" } });
await build({ ...common, entryPoints: ["app/preload/preload.ts"], outfile: "out/preload/preload.cjs", format: "cjs" });
console.log("main + preload built");
