import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

const ts = (x: number) => `00:00:${String(Math.floor(x)).padStart(2, "0")},${String(Math.round((x % 1) * 1000)).padStart(3, "0")}`;
const srt = (items: Array<[number, number, string]>) => items.map(([a, b, t], i) => `${i + 1}\n${ts(a)} --> ${ts(b)}\n${t}\n`).join("\n");

// OP/ED（规格 05 §5.6、16 R6）：识别直接登记、弹窗来源与删除（可撤销）、出错时逐对确认、导入预览里 OP/ED 一类与已登记的比较
test("OP/ED：识别、删除与撤销、逐对确认、导入预览", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-oped-"));
  const mkv = join(dir, "[Group] Oped Show [01].mkv");
  const sub = join(dir, "[Group] Oped Show [01].srt");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=20",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=20", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  writeFileSync(sub, srt([[1, 2, "♪〜"], [3, 4, "（京子）歌の中"], [8, 9, "〜♪"], [12, 13, "（京子）台詞"], [15, 16, "♪～"], [18, 19, "～♪"]]));
  const { app, page } = await launch();
  await page.keyboard.press("Meta+2");
  await page.evaluate(async (p) => window.otto.core.request("sources.add", { paths: [p] }), mkv);
  await page.keyboard.press("Escape");
  await page.getByTestId("source-group").first().click();
  const row = page.getByTestId("source-row").first();
  await row.click();

  // 右键 → 从字幕识别：两对 → OP、ED 直接登记
  await row.click({ button: "right" });
  await page.getByRole("menuitem", { name: "从字幕识别 OP/ED" }).click();
  await expect(page.getByText(/已从字幕识别并登记 2 个/)).toBeVisible();
  await row.click({ button: "right" });
  await page.getByRole("menuitem", { name: "OP/ED…" }).click();
  const dlg = page.getByTestId("oped-dialog");
  const rows = dlg.getByTestId("oped-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(0)).toContainText("OP");
  await expect(rows.nth(0)).toContainText("1.000–9.000 s");
  await expect(rows.nth(0)).toContainText("字幕规则");
  await expect(rows.nth(1)).toContainText("ED");
  // 手动标记与 ED 交叠 → 报错
  await dlg.getByTestId("oped-start").fill("0:17.000");
  await dlg.getByTestId("oped-start").press("Enter");
  await expect(dlg.getByTestId("oped-add")).toBeDisabled(); // 默认长度 90 秒超出原片
  await dlg.getByRole("textbox", { name: "长度（秒）" }).fill("2");
  await dlg.getByRole("textbox", { name: "长度（秒）" }).press("Tab");
  await dlg.getByTestId("oped-add").click();
  await expect(page.getByText(/与已有的 ED 区间/)).toBeVisible();
  await page.screenshot({ path: ".cache/playwright-results/oped.png" });
  // 删除 ED → 撤销（顶栏）
  await rows.nth(1).getByRole("button", { name: "删除" }).click();
  await expect(rows).toHaveCount(1);
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  const count = () => page.evaluate(async (id) => ((await window.otto.core.request<unknown[]>("oped.list", { sourceId: id })) as { r: unknown[] }).r.length, sid);
  const sid = await row.getAttribute("data-id");
  await expect.poll(count).toBe(2);

  // 导入预览（四类一起进）：OP/ED 一类与已登记的两对比较 → 无变化
  await page.getByTestId("transcript-import").click();
  const sheet = page.getByTestId("subtitle-import");
  await sheet.getByTestId("subimport-tab").getByRole("radio", { name: /OP\/ED/ }).click();
  const pairs = sheet.getByTestId("subimport-oped-table").getByTestId("table-row");
  await expect(pairs).toHaveCount(2);
  await expect(pairs.nth(0)).toContainText("无变化");
  await expect(pairs.nth(1)).toContainText("ED");
  await page.keyboard.press("Escape");

  // 出错：重复开始 → 不登记，弹窗列出配对，逐对确认（来源“人工确认”）
  await page.evaluate(async (id) => {
    const l = (await window.otto.core.request<Array<{ id: string }>>("oped.list", { sourceId: id })) as { r: Array<{ id: string }> };
    for (const o of l.r) await window.otto.core.request("oped.delete", { id: o.id });
  }, sid);
  writeFileSync(sub, srt([[1, 2, "♪～"], [3, 4, "♪～"], [8, 9, "～♪"]]));
  await row.click({ button: "right" });
  await page.getByRole("menuitem", { name: "从字幕识别 OP/ED" }).click();
  await expect(dlg.getByTestId("oped-errors")).toContainText("重复的开始标记");
  const pending = dlg.getByTestId("oped-pending");
  await expect(pending).toContainText("3.000–9.000 s");
  await pending.getByRole("button", { name: "确认此区间" }).click();
  await expect(dlg.getByTestId("oped-row")).toHaveCount(1);
  await expect(dlg.getByTestId("oped-row")).toContainText("人工确认");
  await page.screenshot({ path: ".cache/playwright-results/oped-errors.png" });
  await app.close();
});
