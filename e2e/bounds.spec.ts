import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { launch } from "./helpers";

// 编辑字幕/区段边界（UI_PLAN §3.1、03 §3.5.4、R4.11）、新增区段标签、改成歌词、本地标签提升为区段标签（R5.6）
type R<T> = { r: T };
type A = { id: string; kind: string; start: number; end: number; tags: string[]; scope: string };
const anns = async (page: Page, sid: string) =>
  ((await page.evaluate(async (s) => window.otto.core.request("annotations.list", { sourceId: s }), sid)) as R<{ annotations: A[] }>).r.annotations;

test("边界编辑、区段标签、歌词、提升本地标签", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-bounds-"));
  const mkv = join(dir, "Bounds Show 01.mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=8",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=8", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  writeFileSync(join(dir, "Bounds Show 01.srt"), "1\n00:00:01,000 --> 00:00:02,000\nあ\n\n2\n00:00:02,000 --> 00:00:03,000\nい\n");
  const { app, page } = await launch();
  await page.keyboard.press("Meta+2");
  const sid = await page.evaluate(async (p) => {
    const r = (await window.otto.core.request<Array<{ sourceId: string }>>("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string }> };
    const s = r.r[0]!.sourceId;
    const pv = (await window.otto.core.request<{ token: string }>("subtitles.preview", { sourceId: s })) as { r: { token: string } };
    await window.otto.core.request("subtitles.import", { sourceId: s, token: pv.r.token });
    return s;
  }, mkv);
  await page.keyboard.press("Escape");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await expect(page.getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });
  const tl = page.getByTestId("timeline");
  const box = (await tl.boundingBox())!;
  const xOf = async (t: number) => {
    const [v0, v1] = (await tl.getAttribute("data-view"))!.split(",").map(Number) as [number, number];
    return box.x + ((t - v0) / (v1 - v0)) * box.width;
  };
  const y = box.y + 50;

  // 1) 拖共用边界 2.0 → 2.5，保存（一次编辑，两条标注一起动），撤销
  await page.getByTestId("edit-bounds").click();
  await expect(page.getByTestId("edit-bar")).toBeVisible();
  await page.mouse.move(await xOf(2), y);
  await page.mouse.down();
  await page.mouse.move(await xOf(2.5), y, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByTestId("edit-start")).toBeVisible(); // 表单显示正在编辑的那条
  await page.getByTestId("edit-save").click();
  await expect.poll(async () => (await anns(page, sid)).map((a) => [a.start, a.end].map((v) => v.toFixed(1)).join("-"))).toEqual(["1.0-2.5", "2.5-3.0"]);
  await page.screenshot({ path: ".cache/playwright-results/bounds-saved.png" });
  await page.keyboard.press("Meta+z");
  await expect.poll(async () => (await anns(page, sid)).map((a) => a.end.toFixed(1))).toEqual(["2.0", "3.0"]);

  // 2) Esc 放弃
  await page.getByTestId("edit-bounds").click();
  await page.mouse.move(await xOf(3), y);
  await page.mouse.down();
  await page.mouse.move(await xOf(3.6), y, { steps: 4 });
  await page.mouse.up();
  await page.getByTestId("source-viewer").focus();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("edit-bar")).toHaveCount(0);
  expect((await anns(page, sid))[1]!.end).toBeCloseTo(3);

  // 3) 选区 4–5 秒 → 右键「新增区段标签…」→ effect:door，作用于整个原片
  await page.mouse.move(await xOf(4), y);
  await page.mouse.down();
  await page.mouse.move(await xOf(5), y, { steps: 6 });
  await page.mouse.up();
  await page.mouse.click(await xOf(4.5), y, { button: "right" });
  await page.getByTestId("timeline-menu").getByRole("menuitem", { name: /新增区段标签/ }).click();
  const dlg = page.getByTestId("annotation-dialog");
  await dlg.getByTestId("ann-tag-input").fill("effect:door");
  await dlg.getByTestId("ann-tag-input").press("Enter");
  await dlg.getByTestId("ann-save").click();
  await expect.poll(async () => (await anns(page, sid)).filter((a) => a.kind === "tag").map((a) => [a.tags.join(), a.scope])).toEqual([["effect:door", "source"]]);

  // 4) 右键覆盖层上的「あ」→ 编辑标注 → 改成歌词
  await page.mouse.click(await xOf(1.5), y, { button: "right" });
  await page.getByTestId("timeline-menu").getByRole("menuitem", { name: /編集|编辑标注「あ」/ }).click();
  await dlg.getByTestId("ann-kind").getByRole("radio", { name: "歌词" }).click();
  await dlg.getByTestId("ann-save").click();
  await expect.poll(async () => (await anns(page, sid))[0]!.kind).toBe("song");

  // 5) 采样上加本地标签 → 提升为区段标签：本地标签消失、有效标签仍在（来自区段）；撤销后恢复
  await page.evaluate(async (s) => {
    const a = (await window.otto.core.request<Array<{ id: string }>>("assets.listForSource", { sourceId: s })) as { r: Array<{ id: string }> };
    await window.otto.core.request("samples.create", { assetId: a.r[0]!.id, start: 6, end: 7, name: "ドア" });
  }, sid);
  await page.keyboard.press("Meta+1");
  await page.getByTestId("refresh-lists").click().catch(() => {});
  await page.getByTestId("sample-row").first().click();
  await page.getByTestId("add-tag").click();
  await page.getByTestId("add-tag-input").fill("好用");
  await page.getByTestId("add-tag-input").press("Enter");
  await expect(page.getByTestId("stage-tags")).toContainText("好用");
  await page.getByTestId("promote").click();
  await expect(page.getByTestId("promote-preview")).toContainText("只作用于这个资产");
  await page.getByTestId("promote-apply").click();
  const tagsOf = async () => {
    const id = await page.getByTestId("sample-row").first().getAttribute("data-id");
    return ((await page.evaluate(async (i) => window.otto.core.request("samples.get", { id: i }), id)) as R<{ tags: Array<{ tag: string; provenance: string }> }>).r.tags
      .filter((x) => x.tag === "好用")
      .map((x) => x.provenance);
  };
  await expect.poll(tagsOf).toEqual(["segment"]);
  await expect(page.getByTestId("promote")).toHaveCount(0); // 没有本地标签了
  await page.keyboard.press("Meta+z");
  await expect.poll(tagsOf).toEqual(["local"]);
  await expect(page.getByTestId("promote")).toBeVisible(); // 舞台跟着撤销刷新
  await page.screenshot({ path: ".cache/playwright-results/promote.png" });
  await app.close();
});
