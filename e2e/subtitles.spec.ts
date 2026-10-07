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

  // 台本里出现导入的两句
  await expect(page.getByTestId("transcript-row")).toHaveCount(2);
  // 再打开（导入后台本有内容，从 ⋯ 菜单进）：同一内容 → 只补登；已登记的两行不可勾选
  await page.getByTestId("viewer-menu").click();
  await page.getByRole("menuitem", { name: "导入字幕标记…" }).click();
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

// 有效标签（04 §4.2.9、R5.2–R5.4）：字幕说话人 → 人声角色的资产上截取的采样继承“人物”；原片作品实时继承
test("有效标签：说话人只给人声资产、列表显示人物、舞台显示分面", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-tag-"));
  const mkv = join(dir, "[Group] Tag Show [01].mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=6",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  writeFileSync(join(dir, "[Group] Tag Show [01].srt"), "1\n00:00:01,000 --> 00:00:03,000\n（京子）こんにちは\n");
  const { app, page } = await launch();
  type R<T> = { ok: boolean; r: T; e?: unknown };
  const req = async <T>(m: string, p: Record<string, unknown>) => {
    const res = (await page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const)) as R<T>;
    if (!res.ok) throw new Error(`${m}: ${JSON.stringify(res.e)}`);
    return res.r;
  };
  const sid = (await req<Array<{ sourceId: string }>>("sources.add", { paths: [mkv] }))[0]!.sourceId;
  const pv = await req<{ token: string }>("subtitles.preview", { sourceId: sid });
  await req("subtitles.import", { sourceId: sid, token: pv.token });
  const aid = (await req<Array<{ id: string }>>("assets.listForSource", { sourceId: sid }))[0]!.id;
  // 原混音还没有人声角色 → 截取的采样不继承说话人
  const s1 = await req<{ id: string }>("samples.create", { assetId: aid, start: 1.5, end: 2.0, name: "前" });
  // 给原混音人声角色 → 已有采样实时继承
  await req("edits.apply", { batch: { ops: [{ entity: "asset", id: aid, version: 1, fields: { roles: ["vocal"] } }] } });
  await page.getByTestId("refresh-lists").click(); // 资料变化只提示，由用户刷新（P8）
  const row = page.getByTestId("sample-row").filter({ hasText: "前" });
  await expect(row).toContainText("京子");
  await row.click();
  const tags = page.getByTestId("stage-tags");
  await expect(tags).toContainText("人物京子");
  await expect(tags).toContainText("作品Tag Show");
  await page.screenshot({ path: ".cache/playwright-results/stage-tags.png" });
  void s1;
  await app.close();
});

// 字幕采样（06 §6.4、R4.8–R4.9、S1.6）：缺默认轨就地选择（同时赋予角色）、默认不勾、表头全选、创建 N 项、名称与人物
test("从字幕导入台词语音：就地指定默认轨、全选创建", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-ss-"));
  const mkv = join(dir, "[Group] Line Show [01].mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=8",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=8", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  writeFileSync(
    join(dir, "[Group] Line Show [01].srt"),
    "1\n00:00:01,000 --> 00:00:02,000\n（京子(きょうこ)たち）アッカリ～ン\n\n2\n00:00:02,050 --> 00:00:03,000\n（結衣）なに？\n\n3\n00:00:04,000 --> 00:00:05,000\n（足音）\n\n4\n00:00:05,500 --> 00:00:06,500\n普通の台詞\n",
  );
  const { app, page } = await launch();
  await page.keyboard.press("Meta+2");
  const sid = await page.evaluate(async (p) => {
    const r = (await window.otto.core.request<Array<{ sourceId: string }>>("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string }> };
    const id = r.r[0]!.sourceId;
    const pv = (await window.otto.core.request<{ token: string }>("subtitles.preview", { sourceId: id })) as { r: { token: string } };
    await window.otto.core.request("subtitles.import", { sourceId: id, token: pv.r.token });
    return id;
  }, mkv);
  await page.keyboard.press("Escape");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click({ button: "right" });
  await page.getByRole("menuitem", { name: "从字幕导入台词语音…" }).click();
  const sheet = page.getByTestId("subtitle-samples");
  // 缺默认人声轨 → 就地选原混音（同时赋予人声角色）
  await expect(sheet.getByTestId("subsample-missing")).toBeVisible();
  await sheet.getByTestId("subsample-missing").getByRole("button").click();
  await page.getByRole("option", { name: /同时赋予人声角色/ }).click();
  await expect(sheet.getByTestId("subsample-missing")).toHaveCount(0);
  await expect(sheet.getByTestId("stat-pending")).toContainText("3");
  // 默认一项都不勾
  await expect(sheet.getByTestId("subsample-run")).toBeDisabled();
  await sheet.getByTestId("table-check-all").click();
  await expect(sheet.getByTestId("subsample-run")).toHaveText("创建 3 项");
  await expect(sheet.getByTestId("table-row").first()).toContainText("0.900–2.100");
  await expect(sheet.getByTestId("table-row").first()).toContainText("京子(きょうこ)たち");
  await page.screenshot({ path: ".cache/playwright-results/subtitle-samples.png" });
  await sheet.getByTestId("subsample-run").click();
  await expect(page.getByText(/已创建 3 个采样/)).toBeVisible();

  await page.keyboard.press("Meta+1");
  await page.getByTestId("refresh-lists").click();
  const row = page.getByTestId("sample-row").filter({ hasText: "アッカリ～ン" });
  await expect(row).toHaveAttribute("data-nature", "speech");
  await expect(row).toContainText("京子(きょうこ)たち"); // 扩展部分碰到的結衣不继承
  await expect(row).not.toContainText("結衣");
  void sid;
  await app.close();
});
