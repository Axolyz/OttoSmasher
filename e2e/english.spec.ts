// 英语界面（所有者 2026-11-03）：看得到的地方不能有中文（用户数据、日文除外）；文字变长后布局也要放得下，截图留着看。
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type Page, expect, test } from "@playwright/test";
import { launch } from "./helpers";

const SHOTS = ".cache/playwright-results";

/** 页面上看得见的中文（用户数据、标了日文的除外）。汉字本身也可能是日文，所以只放过明确标记的。 */
async function chineseLeft(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const bad: string[] = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n: Node | null = walker.nextNode();
    while (n) {
      const el = n.parentElement;
      const text = n.textContent ?? "";
      if (el && /[一-鿿]/.test(text) && text.trim() !== "简体中文" && !el.closest("[data-user-data], [lang=ja], [data-testid=specimen]")) {
        const s = window.getComputedStyle(el);
        if (s.display !== "none" && s.visibility !== "hidden") bad.push(text.trim().slice(0, 60));
      }
      n = walker.nextNode();
    }
    return bad;
  });
}

test("英语界面：主要页面和设置都没有中文", async () => {
  test.setTimeout(120_000);
  const dir = mkdtempSync(join(tmpdir(), "otto-en-"));
  const wav = join(dir, "[Group] English Show [01].wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6", "-ac", "2", "-c:a", "pcm_s16le", wav]);
  writeFileSync(wav.replace(/\.wav$/, ".srt"), "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n");
  // 工作区路径也用英文：默认的临时工作区名带中文（测路径用的），会出现在模型页、顶栏
  const { app, page } = await launch({ locale: "en", workspace: join(dir, "workspace") });
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const added = (await req("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string; assets: Array<{ assetId: string }> }> };
    await req("subtitles.importDefault", { sourceId: added.r[0]!.sourceId });
    await req("samples.create", { assetId: added.r[0]!.assets[0]!.assetId, start: 1, end: 2, name: "こんにちは", nature: "speech" });
  }, wav);

  const check = async (name: string) => {
    await page.screenshot({ path: `${SHOTS}/en-${name}.png` });
    expect(await chineseLeft(page), name).toEqual([]);
  };

  await page.keyboard.press("ControlOrMeta+1");
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("otto:refresh-lists")));
  await page.getByTestId("sample-row").first().click();
  await check("library");

  await page.keyboard.press("ControlOrMeta+2");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await check("sources");
  await page.getByTestId("source-row").first().click({ button: "right" });
  await check("sources-menu");
  await page.keyboard.press("Escape");

  await page.getByTestId("nav-tools").click();
  await check("tools");

  await page.keyboard.press("ControlOrMeta+,");
  for (const group of ["general", "models", "storage", "agent"]) {
    await page.getByTestId(`settings-group-${group}`).click();
    await check(`settings-${group}`);
  }
  await app.close();
});

test("设置里切换语言：窗口重载后生效，重新启动还是这个语言", async () => {
  test.setTimeout(90_000);
  const root = mkdtempSync(join(tmpdir(), "otto-lang-"));
  const opts = { locale: null, workspace: join(root, "ws"), userData: join(root, "ud") };
  const { app, page } = await launch(opts);
  const nav = page.getByTestId("nav-library");
  const choose = async (value: string) => {
    await expect.poll(() => page.evaluate(async () => (await window.otto.core.status()).state), { timeout: 20000 }).toBe("ready");
    await page.evaluate(async (v) => {
      const req = window.otto.core.request;
      const list = (await req("settings.list")) as { r: Record<string, { version: number }> };
      await req("edits.apply", { batch: { ops: [{ entity: "setting", id: "general.ui_language", version: list.r["general.ui_language"]!.version, fields: { value: v } }] } });
    }, value);
  };
  await choose("zh-CN");
  await expect(nav).toHaveText(/采样库/, { timeout: 15000 });
  await choose("en");
  await expect(nav).toHaveText(/Library/, { timeout: 15000 });
  await app.close();

  const again = await launch(opts);
  await expect(again.page.getByTestId("nav-library")).toHaveText(/Library/);
  await again.app.close();
});
