import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 删除原素材（含独立化）（规格 04 §4.5、§4.8、16 S12；原型 delSrcModal）：勾一个采样独立化 → 任务 → 原素材“媒体已释放”留在组里；
// 留下的采样仍可试听、有画面片段、不能返回原素材；另一个采样删掉；磁盘上的原素材文件不动。
const SHOTS = ".cache/compare/shots/stage9";

test("删除原素材：先独立化要保留的采样", async () => {
  test.setTimeout(120_000);
  mkdirSync(SHOTS, { recursive: true });
  const dir = mkdtempSync(join(tmpdir(), "otto-indep-"));
  const mkv = join(dir, "Show 02.mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=6", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6",
    "-c:v", "libx264", "-c:a", "flac", mkv]); // prettier-ignore
  const { app, page } = await launch();
  await page.setViewportSize({ width: 1536, height: 864 });
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    const aid = add.r[0]!.assets[0]!.assetId;
    await req("samples.create", { assetId: aid, start: 1, end: 2, name: "残す", nature: "speech" });
    await req("samples.create", { assetId: aid, start: 3, end: 4, name: "消す", nature: "speech" });
  }, mkv);
  await page.keyboard.press("Meta+2");
  await refreshLists(page);
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click({ button: "right" });
  await page.getByTestId("menu-delete").click();
  const dlg = page.getByTestId("source-delete");
  await expect(dlg.getByTestId("delete-independ")).toBeVisible();
  await dlg.getByRole("row", { name: /残す/ }).locator("label").first().click();
  await expect(dlg.getByTestId("indep-size")).toContainText("已选 1 个 · 约 0.1 MB · 1 个要生成画面片段");
  await expect(dlg.getByTestId("delete-release")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/06-delete-independ.png` });
  await dlg.getByTestId("confirm-ok").click();
  await expect.poll(async () => page.evaluate(async () => ((await window.otto.core.request("sources.list", {})) as { r: Array<{ media_state: string }> }).r[0]?.media_state), { timeout: 60000 }).toBe("released");
  await refreshLists(page);
  await expect(page.getByTestId("source-released")).toContainText("媒体已释放 · 1 个独立化采样");
  await page.getByTestId("source-row").first().click();
  await expect(page.getByTestId("released-viewer")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/07-released-viewer.png` });
  expect(existsSync(mkv)).toBe(true);

  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await page.getByTestId("sample-row").first().click();
  await expect(page.getByTestId("stage-independent")).toBeVisible();
  await expect(page.getByTestId("back-to-source")).toBeDisabled();
  await expect(page.getByTestId("stage-picture")).toHaveAttribute("data-mode", "materialized_clip");
  await page.getByTestId("stage-play").click();
  await expect(page.getByTestId("dock-version")).toContainText("原声");
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/08-independent-stage.png` });
  await app.close();
});
