import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 原素材列表虚拟化（L15）：上千个短音频展开成一组时只渲染看得见的行；滚动、单击照常。
function wav(path: string): void {
  const n = 800;
  const b = Buffer.alloc(44 + n * 2);
  b.write("RIFF", 0);
  b.writeUInt32LE(36 + n * 2, 4);
  b.write("WAVEfmt ", 8);
  b.writeUInt32LE(16, 16);
  b.writeUInt16LE(1, 20);
  b.writeUInt16LE(1, 22);
  b.writeUInt32LE(8000, 24);
  b.writeUInt32LE(16000, 28);
  b.writeUInt16LE(2, 32);
  b.writeUInt16LE(16, 34);
  b.write("data", 36);
  b.writeUInt32LE(n * 2, 40);
  writeFileSync(path, b);
}

test("原素材列表：1500 个短音频的组只渲染看得见的行", async () => {
  test.setTimeout(300_000);
  const dir = mkdtempSync(join(tmpdir(), "otto-many-"));
  const folder = join(dir, "游戏 A");
  mkdirSync(folder);
  const files: string[] = [];
  for (let i = 0; i < 1500; i++) {
    const p = join(folder, `se_${String(i).padStart(4, "0")}.wav`);
    wav(p);
    files.push(p);
  }
  const { app, page } = await launch();
  await page.setViewportSize({ width: 1536, height: 864 });
  await page.evaluate(async (ps) => {
    for (let i = 0; i < ps.length; i += 300) await window.otto.core.request("sources.add", { paths: ps.slice(i, i + 300) });
  }, files);
  await page.keyboard.press("Meta+2");
  await refreshLists(page);
  const t0 = Date.now();
  await page.getByTestId("source-group").first().click();
  await expect(page.getByTestId("source-row").first()).toBeVisible();
  const ms = Date.now() - t0;
  const rendered = await page.getByTestId("source-row").count();
  console.log(`expand 1500: ${ms} ms, rendered rows ${rendered}`);
  expect(rendered).toBeLessThan(200);
  // 滚到底：最后一行可见、可以打开
  await page.getByTestId("source-row").first().hover();
  await page.mouse.wheel(0, 200000);
  await expect(page.getByTestId("source-row").filter({ hasText: "se_0000" })).toBeVisible({ timeout: 10000 });
  await app.close();
});
