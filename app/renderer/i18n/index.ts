// 界面文案入口：所有用户可见文字都经 t()（AGENTS.md §9）。
import { type Catalog, PSEUDO, type TArgs, createT, englishPlurals, windowsKeys } from "../../shared/i18n";
import en from "./locales/en.json";
import zhCN from "./locales/zh-CN.json";

const catalogs: Record<string, Catalog> = { "zh-CN": zhCN as Catalog, en: en as Catalog };

function currentLocale(): string {
  if (typeof window !== "undefined" && window.otto) return window.otto.app.locale;
  return "zh-CN";
}

const locale = currentLocale();
const pseudo = locale === PSEUDO;
if (typeof document !== "undefined" && !pseudo) document.documentElement.lang = locale;

const isMac = typeof window === "undefined" || !window.otto || window.otto.app.platform === "darwin";

/** 代码里写的快捷键文字（⌘K）按当前系统显示。 */
export const keys = (text: string): string => (isMac ? text : windowsKeys(text));

const rawCatalog = catalogs[pseudo ? "zh-CN" : locale] ?? (zhCN as Catalog);
export const t = createT(
  isMac ? rawCatalog : Object.fromEntries(Object.entries(rawCatalog).map(([k, v]) => [k, windowsKeys(v, rawCatalog["common.fileManagerWindows"])])),
  { pseudo, strict: import.meta.env.DEV, finish: locale === "en" ? englishPlurals : undefined },
);

export type { TArgs };

/** Core 返回的“错误码 + 参数” → 当前语言的提示（规格 15 §15.7）。 */
export function errorText(err: { code: string; args?: Record<string, unknown> }): string {
  const args: TArgs = {};
  for (const [k, v] of Object.entries(err.args ?? {})) {
    if (k === "reason" && typeof v === "string") {
      // 没有规则序号时（单条规则，如字幕规则）用不带“第 N 条”的说法
      const one = `reason.${v}.one`;
      const key = err.args?.rule === undefined && hasKey(one) ? one : `reason.${v}`;
      if (hasKey(key)) args[k] = t(key, err.args as TArgs);
    } else if (k === "role" && typeof v === "string" && hasKey(`role.${v}`)) args[k] = t(`role.${v}`);
    else if (k === "setting" && typeof v === "string") args[k] = hasKey(`settings.${v}.label`) ? t(`settings.${v}.label`) : v;
    else if (k === "field" && typeof v === "string") args[k] = v;
    else if (typeof v === "string" || typeof v === "number") args[k] = k === "index" ? Number(v) + 1 : v;
  }
  return hasKey(`error.${err.code}`) ? t(`error.${err.code}`, args) : t("error.unknown", { code: err.code });
}

export function hasKey(key: string): boolean {
  const cat = catalogs[pseudo ? "zh-CN" : locale] ?? (zhCN as Catalog);
  return key in cat;
}
