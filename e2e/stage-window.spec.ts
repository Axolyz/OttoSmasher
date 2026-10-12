import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 详情区波形窗口（所有者 2026-10-12）：只显示采样范围 + 两边各 max(1 秒, 采样长度的一半) 的余量；缩放、平移停在窗口边界；
// 余量里也能框选并截取；超出窗口的选区不接受（更远用「返回原素材」）。
test("详情区窗口：余量、缩放边界、在余量里截取", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-window-"));
  const wav = join(dir, "window.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=12", wav]);
  const { app, page } = await launch();
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    await req("samples.create", { assetId: add.r[0]!.assets[0]!.assetId, start: 5.0, end: 6.0, name: "まど", nature: "speech" });
  }, wav);
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await page.getByTestId("sample-row").filter({ hasText: "まど" }).click();
  const tl = page.getByTestId("stage-wave").getByTestId("timeline");
  await expect(tl).toBeVisible();
  const view = async () => (await tl.getAttribute("data-view"))!.split(",").map(Number);
  // 打开时放大到采样本身；往外缩放到头 = 整个窗口 [4, 7]（采样 1 秒 → 余量 1 秒），不会露出整条 12 秒的音轨
  await expect.poll(async () => (await view())[1] - (await view())[0]).toBeLessThan(1.5);
  const box = (await tl.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < 8; i++) await page.mouse.wheel(0, 400);
  await expect.poll(view).toEqual([4, 7]);
  // 选区起点伸进余量（4.5 秒）可以；超出窗口（3 秒）不接受
  const start = page.getByTestId("stage-sel-start");
  await start.fill("0:04.500");
  await start.press("Enter");
  await expect(page.getByTestId("stage-readout")).toHaveAttribute("data-a", "4.5");
  await start.fill("0:03.000");
  await start.press("Enter");
  await expect(page.getByTestId("stage-readout")).toHaveAttribute("data-a", "4.5");
  // 截取 4.5–6.0（伸进余量的选区照常截取）
  await page.getByTestId("stage-actions").getByTestId("clip").click();
  await page.getByTestId("clip-panel").getByTestId("clip-name").fill("よはく");
  await page.getByTestId("clip-panel").getByTestId("clip-save").click();
  await refreshLists(page);
  const made = await page.evaluate(async () => {
    const r = (await window.otto.core.request("samples.list", { offset: 0, limit: 10 })) as { r: { rows: Array<{ name: string; start: number; end: number }> } };
    return r.r.rows.find((x) => x.name === "よはく");
  });
  expect(made?.start).toBeCloseTo(4.5, 3);
  expect(made?.end).toBeCloseTo(6.0, 3);
  await page.screenshot({ path: ".cache/playwright-results/stage-window.png" });
  await app.close();
});
