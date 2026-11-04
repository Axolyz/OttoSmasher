// 每个弹窗都走一遍打开、取消、Esc（所有者 2026-11-04）：批量导入字幕关闭时整个界面黑屏，就是因为没有测试走到它。
// 只查“开得了、关得掉、界面还在”；helpers 的 launch 会让任何页面报错都算失败。弹窗里面的功能在各自的测试里。
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { type Page, expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

const dialogs = (page: Page) => page.locator('[role="dialog"], [role="alertdialog"]');

/** 清掉多选：右键勾选的行出的是批量菜单 */
async function clearChecks(page: Page) {
  await page.getByTestId("batch-clear").click();
  await expect(page.getByTestId("batch-actions")).toHaveCount(0);
}

/** 打开之后先等数据回来（黑屏就是有数据之后才出现的），再分别用取消和 Esc 关掉 */
async function sweep(page: Page, items: string[], open: (item: string) => Promise<void>) {
  for (const item of items) {
    for (const how of ["cancel", "esc"] as const) {
      await test.step(`${item} · ${how}`, async () => {
        await open(item);
        const dlg = dialogs(page).last();
        await expect(dlg).toBeVisible();
        await page.waitForTimeout(400);
        if (how === "esc") await page.keyboard.press("Escape");
        else {
          const cancel = dlg.getByRole("button", { name: /^取消/ });
          await ((await cancel.count()) ? cancel.first() : dlg.getByRole("button", { name: /^关闭/ }).first()).click();
        }
        await expect(dialogs(page)).toHaveCount(0);
        await expect(page.getByTestId("nav-library")).toBeVisible();
      });
    }
  }
}

test("原片页和采样库的弹窗：打开、取消、Esc 之后界面都还在", async () => {
  test.setTimeout(240_000);
  const dir = mkdtempSync(join(tmpdir(), "otto-dialogs-"));
  const files = ["01", "02"].map((ep) => {
    const wav = join(dir, `[Group] Dialog Show [${ep}].wav`);
    execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=4", "-ac", "2", "-c:a", "pcm_s16le", wav]);
    writeFileSync(wav.replace(/\.wav$/, ".srt"), `1\n00:00:01,000 --> 00:00:02,000\n（京子）第${ep}話のせりふ\n`);
    return wav;
  });
  const { app, page } = await launch();
  await page.evaluate(async (paths) => {
    const req = window.otto.core.request;
    const added = (await req("sources.add", { paths })) as { r: Array<{ sourceId: string; assets: Array<{ assetId: string }> }> };
    for (const x of added.r) {
      await req("subtitles.importDefault", { sourceId: x.sourceId });
      await req("samples.create", { assetId: x.assets[0]!.assetId, start: 1, end: 2, name: "s", nature: "unclassified" });
    }
  }, files);

  // 原片页：多选（批量菜单）
  await page.keyboard.press("ControlOrMeta+2");
  await page.keyboard.press("Escape");
  const group = page.getByTestId("source-group").first();
  await sweep(page, ["separate", "separated-vocal", "subimport", "subclear", "newsamples-segments", "newsamples-hints", "whole", "speech", "work-type", "match-pictures", "delete"], async (item) => {
    await group.click({ button: "right" });
    await page.getByTestId("menu-check").click();
    await page.getByTestId("batch-actions").click();
    await page.getByTestId(`menu-${item}`).click();
  });
  await clearChecks(page);

  // 原片页：单选（右键菜单）
  await group.click(); // 分组默认折叠
  const row = page.getByTestId("source-row").first();
  await expect(row).toBeVisible();
  await sweep(page, ["separate", "tracks", "subimport", "subclear", "newsamples-segments", "newsamples-hints", "whole", "oped", "speech", "settings", "visual", "delete"], async (item) => {
    await row.click({ button: "right" });
    await page.getByTestId(`menu-${item}`).click();
  });

  // 采样库：多选（批量菜单）
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  const sample = page.getByTestId("sample-row").first();
  await sweep(page, ["tags-add", "tags-remove", "edit", "independ", "speech", "flatten", "separate", "delete"], async (item) => {
    await sample.focus();
    await page.keyboard.press("ControlOrMeta+a");
    await page.getByTestId("library-checked").getByRole("button", { name: /批量操作/ }).click();
    await page.getByTestId(`menu-${item}`).click();
  });

  // 采样库：单选（右键菜单）
  await clearChecks(page);
  await sweep(page, ["tags-add", "tags-remove", "edit", "visual", "independ", "speech", "flatten", "delete"], async (item) => {
    await sample.click({ button: "right" });
    await page.getByTestId(`menu-${item}`).click();
  });
  await app.close();
});
