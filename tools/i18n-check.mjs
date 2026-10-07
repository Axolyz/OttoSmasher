// 静态检查（ARCHITECTURE §7、规格 16 R22.13）：界面与 Core 源码里，除注释、测试与文案资源外不得出现中日文字面量。
// 另检查：代码里用到的固定文案键都在 zh-CN.json 里。
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = new URL("..", import.meta.url).pathname;
const CJK = /[　-〿぀-ヿ㐀-鿿＀-￯]/;
const roots = ["app/main", "app/preload", "app/renderer", "app/shared", "core/ottosmasher"];
const skip = (p) => p.includes("/locales/") || p.endsWith(".test.ts") || p.endsWith(".test.tsx") || p.includes("/migrations/");

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.(ts|tsx|py|css)$/.test(name)) yield p;
  }
}

function stripComments(src, py) {
  if (py) {
    // 去掉 # 注释和三引号文档字符串
    return src.replace(/"""[\s\S]*?"""/g, "").replace(/'''[\s\S]*?'''/g, "").replace(/#.*$/gm, "");
  }
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1").replace(/\{\/\*[\s\S]*?\*\/\}/g, "");
}

const problems = [];
for (const r of roots) {
  for (const file of walk(join(ROOT, r))) {
    const rel = relative(ROOT, file);
    if (skip(rel)) continue;
    const code = stripComments(readFileSync(file, "utf8"), file.endsWith(".py"));
    code.split("\n").forEach((line, i) => {
      if (CJK.test(line)) problems.push(`${rel}:${i + 1}: ${line.trim()}`);
    });
  }
}

const catalog = JSON.parse(readFileSync(join(ROOT, "app/renderer/i18n/locales/zh-CN.json"), "utf8"));
for (const r of ["app/main", "app/renderer"]) {
  for (const file of walk(join(ROOT, r))) {
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(/\bt\(\s*"([\w.\-]+)"/g)) {
      if (!(m[1] in catalog)) problems.push(`${relative(ROOT, file)}: missing key "${m[1]}"`);
    }
  }
}

if (problems.length) {
  console.error(problems.join("\n"));
  console.error(`\n${problems.length} problem(s)`);
  process.exit(1);
}
console.log("i18n check ok");
