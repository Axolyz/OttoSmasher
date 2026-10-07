import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 字幕标记导入（规格 06 §6.1、16 R4.1–R4.3）：同名字幕自动关联 → 工作台预览 → 取消勾选一行 → 导入 → 已登记 → 撤销
test("导入字幕标记：预览、部分导入、补登、撤销", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-sub-"));
  const mkv = join(dir, "[Group] Sub Show [01].mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=8",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=8", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  writeFileSync(
    join(dir, "[Group] Sub Show [01].srt"),
    "﻿1\r\n00:00:01,000 --> 00:00:02,000\r\n（京子）こんにちは\r\n\r\n" +
      "2\r\n00:00:02,500 --> 00:00:03,000\r\n（足音）\r\n\r\n" +
      "3\r\n00:00:03,500 --> 00:00:04,500\r\n（京子）（結衣）ありがとう\r\n\r\n" +
      "4\r\n00:00:05,000 --> 00:00:05,000\r\nゼロ長\r\n\r\n" +
      "5\r\n00:00:06,000 --> 00:00:09,000\r\nはみ出し\r\n",
  );
  const { app, page } = await launch();
  await page.keyboard.press("Meta+2");
  await page.evaluate(async (p) => window.otto.core.request("sources.add", { paths: [p] }), mkv);
  await page.keyboard.press("Escape"); // 关掉首次登记弹出的「作品与输入设置」
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();

  await page.getByTestId("transcript-import").click();
  const sheet = page.getByTestId("subtitle-import");
  await expect(sheet.getByTestId("stat-importable")).toContainText("3");
  await expect(sheet.getByTestId("stat-invalid")).toContainText("2");
  await expect(sheet.getByTestId("subimport-version")).toContainText("新的当前版本");
  const rows = sheet.getByTestId("table-row");
  await expect(rows).toHaveCount(5);
  await expect(rows.nth(0)).toContainText("台词 · 说话人 京子");
  await expect(rows.nth(1)).toContainText("音效");
  await expect(rows.nth(3)).toContainText("结束不晚于开始");
  await expect(rows.nth(4)).toContainText("超出原片时长");
  // 无效行不可勾选；取消勾选第 2 行
  await expect(rows.nth(3).getByRole("checkbox")).toBeDisabled();
  await rows.nth(1).locator("label").first().click();
  await expect(sheet.getByTestId("subimport-run")).toHaveText("导入 2 条标记");
  await page.screenshot({ path: ".cache/playwright-results/subtitle-import.png" });
  await sheet.getByTestId("subimport-run").click();
  await expect(page.getByText(/已导入 2 条字幕标记/)).toBeVisible();
  const sid = await page.getByTestId("source-row").first().getAttribute("data-id");
  // 导入不建采样
  const samples = await page.evaluate(async () => ((await window.otto.core.request<{ total: number }>("samples.list", { offset: 0, limit: 1 })) as { r: { total: number } }).r.total);
  expect(samples).toBe(0);

  // 再打开：同一内容 → 只补登；已登记的两行不可勾选
  await page.getByTestId("transcript-import").click();
  await expect(sheet.getByTestId("stat-registered")).toContainText("2");
  await expect(sheet.getByTestId("subimport-version")).toContainText("只补登");
  await expect(sheet.getByTestId("subimport-run")).toHaveText("导入 1 条标记");
  await page.keyboard.press("Escape");

  // 撤销导入 → 两行都回到可导入
  await page.getByTestId("undo").click();
  await expect
    .poll(() => page.evaluate(async (id) => ((await window.otto.core.request<{ counts: { importable: number } }>("subtitles.preview", { sourceId: id })) as { r: { counts: { importable: number } } }).r.counts.importable, sid))
    .toBe(3);
  await app.close();
});
