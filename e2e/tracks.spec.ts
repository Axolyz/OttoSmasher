import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 人声／音效与默认轨（规格 05 §5.4、16 R2.1–R2.4）
test("角色与默认轨：加角色、设默认、去角色同时取消默认、撤销", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-trk-"));
  const mkv = join(dir, "[Group] Track Show [01].mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=4",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=4", "-f", "lavfi", "-i", "sine=f=660:sample_rate=48000:duration=4",
    "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264", "-c:a", "flac", "-metadata:s:a:1", "language=jpn", mkv]);  // prettier-ignore
  const { app, page } = await launch();
  await page.keyboard.press("ControlOrMeta+2");
  await page.evaluate(async (p) => window.otto.core.request("sources.add", { paths: [p] }), mkv);
  await page.keyboard.press("Escape");
  await page.getByTestId("source-group").first().click();
  const row = page.getByTestId("source-row").first();
  await row.click({ button: "right" });
  await page.getByRole("menuitem", { name: "人声 / 音效与默认轨…" }).click();
  const dlg = page.getByTestId("tracks-dialog");
  const rows = dlg.getByTestId("track-row");
  await expect(rows).toHaveCount(2);
  await expect(rows.nth(1)).toContainText("原混音 · 第 2 条音轨 · jpn");

  // 没有角色时下拉里只有“未指定”
  await dlg.getByTestId("default-vocal").getByRole("button").click();
  await expect(page.getByRole("option")).toHaveCount(1);
  await page.keyboard.press("Escape");

  // 第 2 条加人声 → 设为默认人声轨
  await rows.nth(1).getByText("人声").click();
  await expect(page.getByText(/加上人声角色/)).toBeVisible();
  await dlg.getByTestId("default-vocal").getByRole("button").click();
  await page.getByRole("option", { name: "原混音 · 第 2 条音轨 · jpn" }).click();
  await expect(page.getByText(/默认人声轨改为/)).toBeVisible();
  await expect(rows.nth(1)).toContainText("默认");
  await page.screenshot({ path: ".cache/playwright-results/tracks.png" });

  // 去掉人声角色 → 同时取消默认（提示里写明）
  await rows.nth(1).getByText("人声").click();
  await expect(page.getByText(/并取消了它的默认人声轨/)).toBeVisible();
  await expect(dlg.getByTestId("default-vocal")).toContainText("未指定");
  // 撤销 → 角色和默认都回来
  await page.keyboard.press("Escape");
  await page.getByTestId("undo").click();
  const sid = await row.getAttribute("data-id");
  await expect
    .poll(() => page.evaluate(async (id) => ((await window.otto.core.request<{ defaults: Record<string, string> }>("assets.tracks", { sourceId: id })) as { r: { defaults: Record<string, string> } }).r.defaults.vocal ?? null, sid))
    .not.toBeNull();
  await app.close();
});
