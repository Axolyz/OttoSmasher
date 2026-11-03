// 只翻译文字（ARCHITECTURE §7）：按键查文案，替换 {名字} 参数；数字日期不随语言变化。
// 伪语言（测试用）：每条文案加方括号并拉长，用来发现写死在代码里的文字（规格 16 R22.13）。

export type Catalog = Record<string, string>;
export type TArgs = Record<string, string | number | null | undefined>;
export type TFunction = (key: string, args?: TArgs) => string;

export const PSEUDO = "pseudo";

export function pseudoize(text: string): string {
  // 保留 {参数} 原样，只给整条加括号并拉长约三成
  const pad = "·".repeat(Math.max(1, Math.round(text.length * 0.3)));
  return `[${text}${pad}]`;
}

export function format(template: string, args?: TArgs): string {
  if (!args) return template;
  return template.replace(/\{(\w+)\}/g, (m, name: string) => {
    const v = args[name];
    return v === undefined || v === null ? m : String(v);
  });
}

/** 文案里的 macOS 键符换成 Windows 的键名（代码里 ⌘ 与 Ctrl 同样处理，只有显示不同）。 */
export function windowsKeys(text: string, fileManager = "File Explorer"): string {
  return text
    .replace(/⌥\/Alt/g, "Alt")
    .replace(/⌘⇧/g, "Ctrl+Shift+")
    .replace(/⌥⇧/g, "Alt+Shift")
    .replace(/⌘/g, "Ctrl+")
    .replace(/⌥/g, "Alt")
    .replace(/⇧/g, "Shift+")
    .replace(/\bFinder\b/g, fileManager);
}

const ENGLISH_NOUNS: Record<string, string> = {
  lines: "line", samples: "sample", items: "item", sources: "source", tracks: "track", tags: "tag", segments: "segment",
  hints: "hint", files: "file", jobs: "job", models: "model", stems: "stem", episodes: "episode", phonemes: "phoneme",
  hits: "hit", results: "result", entries: "entry", rows: "row", groups: "group", blocks: "block", pauses: "pause", ranges: "range",
};
const ENGLISH_ONE = new RegExp(`(?<![\\d.,:])1 ((?:SFX |range |OP/ED )?)(${Object.keys(ENGLISH_NOUNS).join("|")})\\b`, "g");

/** 英文的单复数：文案写 “{n} lines” 或 “{n} sample(s)”，格式化后按数字改对（不用给每条拆 _one / _other）。 */
export function englishPlurals(text: string): string {
  return text
    .replace(/(?<![\d.,:])1 ([\w/-]+(?: [\w/-]+)?)\(s\)/g, "1 $1")
    .replace(/(\w)\(s\)/g, "$1s")
    .replace(ENGLISH_ONE, (_m, prefix: string, noun: string) => `1 ${prefix}${ENGLISH_NOUNS[noun]}`);
}

export function createT(catalog: Catalog, opts: { pseudo?: boolean; strict?: boolean; finish?: (text: string) => string } = {}): TFunction {
  return (key, args) => {
    const plural = typeof args?.n === "number" && catalog[`${key}_one`] !== undefined && catalog[`${key}_other`] !== undefined;
    const k = plural ? `${key}_${args!.n === 1 ? "one" : "other"}` : key;
    const raw = catalog[k];
    if (raw === undefined) {
      if (opts.strict) throw new Error(`missing i18n key: ${key}`);
      return opts.pseudo ? `[!${key}]` : key;
    }
    const text = opts.finish ? opts.finish(format(raw, args)) : format(raw, args);
    return opts.pseudo ? pseudoize(text) : text;
  };
}
