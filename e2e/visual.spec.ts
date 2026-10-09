import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 画面绑定与舞台画面（规格 12 §12.4、16 S7.3；UI_PLAN §3）：原片自带视频 → 舞台同步视频；采样绑定图片 → 静态图片；撤销回到原片的画面。
const SHOTS = ".cache/compare/shots/stage9";

test("舞台画面：同步视频、绑定图片、撤销", async () => {
  test.setTimeout(120_000);
  mkdirSync(SHOTS, { recursive: true });
  const dir = mkdtempSync(join(tmpdir(), "otto-visual-"));
  const mkv = join(dir, "Show 01.mkv");
  const png = join(dir, "cover.png");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=6", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6",
    "-c:v", "libx264", "-c:a", "flac", mkv]); // prettier-ignore
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "color=c=orange:s=160x90:d=0.1", "-frames:v", "1", png]);
  const { app, page } = await launch();
  await page.setViewportSize({ width: 1536, height: 864 });
  const sid = await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    const c = (await req("samples.create", { assetId: add.r[0]!.assets[0]!.assetId, start: 1, end: 3, name: "画面テスト", nature: "speech" })) as { r: { id: string } };
    return c.r.id;
  }, mkv);
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await page.getByTestId("sample-row").first().click();
  await expect(page.getByTestId("stage-picture")).toHaveAttribute("data-mode", "sync");
  await expect(page.locator("canvas[data-otto-stage-video]")).toBeVisible();
  await page.getByTestId("stage-play").click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${SHOTS}/01-stage-sync.png` });
  await page.getByTestId("stage-pic-wide").click();
  await page.screenshot({ path: `${SHOTS}/02-stage-wide.png` });
  await page.getByTestId("stage-pic-wide").click();

  // 绑定图片（编辑通道）→ 舞台显示静态图片；撤销 → 回到原片的视频
  await page.evaluate(
    async ({ id, p }) => {
      const req = window.otto.core.request;
      const b = (await req("visuals.prepare", { ownerType: "sample", ownerId: id, path: p })) as { r: { bindingId: string } };
      const s = (await req("samples.get", { id })) as { r: { version: number } };
      await req("edits.apply", { batch: { label: { code: "visual-bind", args: { name: "x" } }, ops: [{ entity: "sample", id, version: s.r.version, fields: { visual_binding_id: b.r.bindingId } }] } });
    },
    { id: sid, p: png },
  );
  await expect(page.getByTestId("stage-picture")).toHaveAttribute("data-mode", "image");
  await expect(page.getByTestId("stage-picture").locator("img")).toBeVisible({ timeout: 15000 });
  // 「画面绑定…」对话框写明现在用的是采样自己的绑定
  await page.getByTestId("stage-visual").click();
  await expect(page.getByTestId("visual-current")).toContainText("采样自己的绑定 · 静态图片");
  await page.screenshot({ path: `${SHOTS}/03-visual-dialog.png` });
  await page.getByTestId("visual-unbind").click();
  await expect(page.getByTestId("stage-picture")).toHaveAttribute("data-mode", "sync");
  await page.keyboard.press("Meta+z");
  await expect(page.getByTestId("stage-picture")).toHaveAttribute("data-mode", "image");

  // 导出视频片段（S7.1）：交接 ▾ → 导出视频片段… → 任务 → 播放条出现 .mp4
  await page.keyboard.press("Meta+z"); // 再撤销一次：回到原片自带的视频
  await expect(page.getByTestId("stage-picture")).toHaveAttribute("data-mode", "sync");
  await page.getByTestId("stage-handoff").click();
  await page.getByTestId("menu-video").click();
  await expect(page.getByTestId("video-dialog")).toContainText("同步视频");
  await page.screenshot({ path: `${SHOTS}/04-video-dialog.png` });
  await page.getByTestId("video-go").click();
  await expect(page.getByTestId("dock-export")).toContainText(".mp4", { timeout: 60000 });

  // 回导（S8）：动作条「回导」→ 弹窗写明起点 = 选区起点（选文件是系统对话框，Core 的流程见 test_reimport）
  await page.getByTestId("stage-reimport").click();
  await expect(page.getByTestId("reimport-dialog")).toContainText("起点 = 当前选区起点 1.000 秒");
  await expect(page.getByTestId("reimport-save")).toBeDisabled();
  await page.screenshot({ path: `${SHOTS}/05-reimport.png` });
  await page.keyboard.press("Escape");
  await app.close();
});

test("设置 → 存储与缓存：按类别列出、手动清理", async () => {
  const { app, page } = await launch();
  await page.setViewportSize({ width: 1536, height: 864 });
  await page.keyboard.press("Meta+,");
  await page.getByTestId("settings-group-storage").click();
  await expect(page.getByTestId("storage-panel")).toContainText("可重建缓存");
  await expect(page.getByTestId("storage-panel")).toContainText("测量结果");
  await page.getByTestId("storage-clean").click();
  await expect(page.getByText(/已清理 \d+ 个文件/)).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/09-storage.png` });
  await app.close();
});
