import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 导入到文本层（所有者 2026-10-09「原片上的四类对象」B 节）：同名字幕自动关联 → 四类预览（台词段 / 音效提示 / 说话人 / OP/ED）→
// 取消勾选一行 → 导入 → 再导入只剩“新增 1 / 无变化 2” → 改过的段受保护：再导入跳过，逐行强制替换要二次确认 → 撤销
test("导入到文本层：预览、部分导入、再导入、受保护跳过与强制替换、撤销", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-sub-"));
  const mkv = join(dir, "[Group] Sub Show [01].mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=8",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=8", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  writeFileSync(
    join(dir, "[Group] Sub Show [01].srt"),
    "\ufeff1\r\n00:00:01,000 --> 00:00:02,000\r\n（京子）こんにちは\r\n\r\n" +
      "2\r\n00:00:02,500 --> 00:00:03,000\r\n（足音）\r\n\r\n" +
      "3\r\n00:00:03,500 --> 00:00:04,500\r\n（京子）（結衣）ありがとう\r\n\r\n" +
      "4\r\n00:00:05,000 --> 00:00:05,000\r\nゼロ長\r\n\r\n" +
      "5\r\n00:00:06,000 --> 00:00:09,000\r\nはみ出し\r\n",
  );
  const { app, page } = await launch();
  type R<T> = { ok: boolean; r: T; e?: unknown };
  const req = async <T>(m: string, p: Record<string, unknown>) => {
    const res = (await page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const)) as R<T>;
    if (!res.ok) throw new Error(`${m}: ${JSON.stringify(res.e)}`);
    return res.r;
  };
  await page.keyboard.press("Meta+2");
  const sid = (await req<Array<{ sourceId: string }>>("sources.add", { paths: [mkv] }))[0]!.sourceId;
  await page.keyboard.press("Escape"); // 关掉首次登记弹出的「作品与输入设置」
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();

  // 关联了同名字幕、还没导入：台本里有一键「导入到文本层」
  await expect(page.getByTestId("transcript-quick-import")).toBeVisible();
  await page.getByTestId("transcript-import").click();
  const sheet = page.getByTestId("subtitle-import");
  await expect(sheet.getByTestId("stat-new")).toContainText("3"); // 两段台词 + 一条音效提示
  await expect(sheet.getByTestId("stat-unchanged")).toContainText("0");
  const rows = sheet.getByTestId("table-row");
  await expect(rows).toHaveCount(4); // 台词段页：两行可导入 + 两行无效
  await expect(rows.nth(0)).toContainText("こんにちは");
  await expect(rows.nth(0)).toContainText("京子");
  await expect(rows.nth(2)).toContainText("结束不晚于开始");
  await expect(rows.nth(3)).toContainText("超出原片时长");
  await expect(rows.nth(2).getByRole("checkbox")).toBeDisabled();
  await sheet.getByTestId("subimport-tab").getByRole("radio", { name: /音效提示/ }).click();
  await expect(rows).toHaveCount(1);
  await expect(rows.nth(0)).toContainText("足音");
  await sheet.getByTestId("subimport-tab").getByRole("radio", { name: /台词段/ }).click();
  // 取消勾选第二段 → 不导入（也不替换任何东西）
  await rows.nth(1).locator("label").first().click();
  await expect(rows.nth(1)).toContainText("不导入");
  await expect(sheet.getByTestId("subimport-run")).toHaveText("导入（2 项）");
  await page.screenshot({ path: ".cache/playwright-results/subtitle-import.png" });
  await sheet.getByTestId("subimport-run").click();
  await expect(page.getByText(/已导入：新增 1 段、1 条音效提示/)).toBeVisible();
  // 导入不建采样；台本里是文本层的段
  expect((await req<{ total: number }>("samples.list", { offset: 0, limit: 1 })).total).toBe(0);
  await expect(page.getByTestId("transcript-row")).toHaveCount(1);

  // 再导入（从 ⋯ 菜单进）：导入过的两行无变化，没导入的那段是新增
  await page.getByTestId("viewer-menu").click();
  await page.getByTestId("menu-subimport").click();
  await expect(sheet.getByTestId("stat-new")).toContainText("1");
  await expect(sheet.getByTestId("stat-unchanged")).toContainText("2");
  await expect(sheet.getByTestId("subimport-run")).toHaveText("导入（1 项）");
  await page.keyboard.press("Escape");

  // 改过的段受保护：再导入时与它交叠的行跳过；逐行强制替换要二次确认（写清会丢什么）
  type Seg = { id: string; version: number; text: string; edited: boolean };
  const seg = (await req<{ segments: Seg[] }>("textLayer.list", { sourceId: sid })).segments[0]!;
  await req("edits.apply", { batch: { ops: [{ entity: "segment", id: seg.id, version: seg.version, fields: { text: "こんにちは！" } }] } });
  await expect(page.getByTestId("seg-flags")).toContainText("✎");
  await page.getByTestId("viewer-menu").click();
  await page.getByTestId("menu-subimport").click();
  await expect(sheet.getByTestId("stat-skip")).toContainText("1");
  await expect(rows.nth(0)).toContainText("跳过：碰到受保护的段");
  await expect(rows.nth(0)).toContainText("こんにちは！ ✎");
  await rows.nth(0).getByTestId("subimport-force").click();
  const confirm = page.getByTestId("subimport-force-confirm");
  await expect(confirm).toContainText("改过");
  await confirm.getByTestId("confirm-ok").click();
  await expect(rows.nth(0)).toContainText("强制替换 1 个已有");
  await page.keyboard.press("Escape");

  // 撤销（撤销文本修改、再撤销导入）→ 全部回到新增
  await page.getByTestId("undo").click();
  await page.getByTestId("undo").click();
  await expect
    .poll(async () => {
      const pv = await req<{ counts: Record<string, { new: number }> }>("subtitles.preview", { sourceId: sid });
      return pv.counts.segments!.new + pv.counts.hints!.new;
    })
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
  await refreshLists(page); // 资料变化只提示，由用户刷新（P8）
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

// 批量建采样（所有者 2026-10-09：建采样一个动作，批量 = 整页表格）：缺默认轨就地选择（同时赋予角色）、默认不勾、表头全选、创建 N 项、名称与人物
test("从台词段批量建采样：就地指定默认轨、全选创建", async () => {
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
  await page.evaluate(async (p) => {
    const r = (await window.otto.core.request<Array<{ sourceId: string }>>("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string }> };
    await window.otto.core.request("subtitles.importDefault", { sourceId: r.r[0]!.sourceId });
  }, mkv);
  await page.keyboard.press("Escape");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click({ button: "right" });
  await page.getByTestId("menu-newsamples-segments").click();
  const sheet = page.getByTestId("new-samples");
  // 缺默认人声轨 → 就地选原混音（同时赋予人声角色）
  await expect(sheet.getByTestId("newsamples-missing")).toBeVisible();
  await sheet.getByTestId("newsamples-missing").getByRole("button").click();
  await page.getByRole("option", { name: /同时赋予人声角色/ }).click();
  await expect(sheet.getByTestId("newsamples-missing")).toHaveCount(0);
  await expect(sheet.getByTestId("stat-pending")).toContainText("3");
  // 默认一项都不勾
  await expect(sheet.getByTestId("newsamples-run")).toBeDisabled();
  await sheet.getByTestId("table-check-all").click();
  await expect(sheet.getByTestId("newsamples-run")).toHaveText("创建 3 项");
  await expect(sheet.getByTestId("table-row").first()).toContainText("0.900–2.100");
  await expect(sheet.getByTestId("table-row").first()).toContainText("京子(きょうこ)たち");
  await page.screenshot({ path: ".cache/playwright-results/new-samples.png" });
  await sheet.getByTestId("newsamples-run").click();
  await expect(page.getByText(/已建立 3 个采样/)).toBeVisible();

  await page.keyboard.press("Meta+1");
  await refreshLists(page);
  const row = page.getByTestId("sample-row").filter({ hasText: "アッカリ～ン" });
  await expect(row).toHaveAttribute("data-nature", "speech");
  await expect(row).toContainText("京子(きょうこ)たち"); // 判定区间 = 段：扩展部分碰到的結衣不继承
  await expect(row).not.toContainText("結衣");
  await app.close();
});
