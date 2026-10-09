import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 标签与资料的批量操作（规格 07 §7.4–§7.6、16 R8.5、R9）：添加 / 移除标签（预览 → 应用 → 撤销）、编辑资料（逐字段对比）、管理标签（全局改名覆盖段的说话人）。
const SHOTS = ".cache/compare/shots/stage8";

test("批量：添加 / 移除标签、编辑资料、管理标签", async () => {
  test.setTimeout(120_000);
  mkdirSync(SHOTS, { recursive: true });
  const base = mkdtempSync(join(tmpdir(), "otto-batch-"));
  const wav = join(base, "b.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=44100:duration=6", wav]);
  const { app, page } = await launch();
  await page.setViewportSize({ width: 1536, height: 864 });
  const sid = await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string; assets: Array<{ assetId: string; version: number }> }> };
    const aid = add.r[0]!.assets[0]!.assetId;
    await req("edits.apply", { batch: { ops: [{ entity: "asset", id: aid, version: 1, fields: { roles: ["vocal"] } }] } });
    await req("edits.apply", { batch: { ops: [{ entity: "segment", op: "create", fields: { source_id: add.r[0]!.sourceId, start: 0, end: 1, text: "あ", speakers: ["京子"], origin: "typed" } }] } });
    for (const [n, a] of [["一", 0], ["二", 2], ["三", 4]] as const) await req("samples.create", { assetId: aid, start: a, end: a + 0.5, name: n, nature: "unclassified" });
    return add.r[0]!.sourceId;
  }, wav);
  void sid;
  await page.getByTestId("nav-library").click();
  await page.getByTestId("refresh-lists").click();
  await expect(page.getByTestId("library-total")).toHaveText("3 个采样");

  // ⌘A → 批量操作 ▾ → 添加标签…：预览（不写库）→ 应用 → 撤销
  await page.getByTestId("sample-row").first().focus();
  await page.keyboard.press("Meta+a");
  await page.getByTestId("library-checked").getByRole("button", { name: /批量操作/ }).click();
  await page.getByTestId("menu-tags-add").click();
  await page.getByTestId("batch-tag").fill("好用");
  await page.getByTestId("batch-preview-btn").click();
  await expect(page.getByTestId("batch-preview")).toContainText("将修改 3 个采样");
  await page.screenshot({ path: `${SHOTS}/05-tag-add.png` });
  await page.getByTestId("batch-apply").click();
  await expect(page.getByTestId("batch-dialog")).toHaveCount(0);
  const local = () => page.evaluate(async () => ((await window.otto.core.request("tags.list", {})) as { r: Array<{ tag: string; local: number }> }).r.find((x) => x.tag === "好用")?.local ?? 0);
  await expect.poll(local).toBe(3);

  // 移除标签：只有本地数量的可勾；继承（人物 京子，来自段）给「去来源」
  await page.getByTestId("library-checked").getByRole("button", { name: /批量操作/ }).click();
  await page.getByTestId("menu-tags-remove").click();
  const dlg = page.getByTestId("batch-dialog");
  await expect(dlg).toContainText("character:京子");
  await page.screenshot({ path: `${SHOTS}/06-tag-remove.png` });
  await dlg.getByRole("row", { name: /好用/ }).locator("label").first().click();
  await page.getByTestId("batch-preview-btn").click();
  await page.getByTestId("batch-apply").click();
  await expect.poll(local).toBe(0);
  // 撤销最近资料修改 → 标签回来
  await page.keyboard.press("Meta+z");
  await expect.poll(local).toBe(3);

  // 编辑资料：性质 + 评分 → 预览是逐字段前后对比
  await page.getByTestId("library-checked").getByRole("button", { name: /批量操作/ }).click();
  await page.getByTestId("menu-edit").click();
  await page.getByTestId("batch-nature").getByRole("button").click();
  await page.getByRole("option", { name: "语音" }).click();
  await page.getByTestId("batch-tags").fill("+尖叫 −好用");
  await page.getByTestId("batch-preview-btn").click();
  await expect(page.getByTestId("batch-preview")).toContainText("未分类 → 语音");
  await page.screenshot({ path: `${SHOTS}/07-edit.png` });
  await page.getByTestId("batch-apply").click();
  await expect(page.getByTestId("sample-row").first()).toHaveAttribute("data-nature", "speech");

  // 管理标签（⋯）：全局改名人物 → 段的说话人跟着改（L33）
  await page.getByTestId("top-more").click();
  await page.getByTestId("menu-manage-tags").click();
  await page.getByTestId("manage-tags-search").fill("京子");
  await page.getByTestId("manage-tags").getByTestId("tag-rename").first().click();
  await page.getByTestId("tag-new-name").fill("character:歳納京子");
  await expect(page.getByTestId("tag-global-report")).toContainText("段的说话人 1 段");
  await page.screenshot({ path: `${SHOTS}/08-tag-rename.png` });
  await page.getByTestId("tag-global").getByTestId("confirm-ok").click();
  const speakers = await page.evaluate(async (s) => ((await window.otto.core.request("textLayer.list", { sourceId: s })) as { r: { segments: Array<{ speakers: string[] }> } }).r.segments[0]!.speakers, sid);
  expect(speakers).toEqual(["歳納京子"]);

  // 舞台：标签带来源小标记；单击标签 → 加入范围；资料与来源：备注失焦保存、评分
  await page.keyboard.press("Escape");
  await page.getByTestId("refresh-lists").click();
  await page.getByTestId("sample-row").filter({ hasText: "一" }).click();
  await expect(page.getByTestId("stage-tags")).toContainText("歳納京子区段");
  await page.getByTestId("stage-tags").getByText("歳納京子", { exact: true }).click();
  await page.getByTestId("menu-to-scope").click();
  await expect(page.getByTestId("scope-chips")).toContainText("人物歳納京子");
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await page.getByTestId("stage-note").fill("开头那句");
  await page.getByTestId("stage-title").click();
  const id = await page.getByTestId("sample-row").first().getAttribute("data-id");
  await expect.poll(() => page.evaluate(async (i) => ((await window.otto.core.request("samples.get", { id: i })) as { r: { detail: { note: string } } }).r.detail.note, id)).toBe("开头那句");
  await page.screenshot({ path: `${SHOTS}/09-stage-info.png` });

  // R8.10 用途视图：只看语音时一步归类（数字键 0）→ 该行就地写“已归类为未分类”、不立即消失；刷新后移出
  await page.getByTestId("scope-preset").click();
  await page.getByTestId("menu-preset-clear").click();
  await page.getByTestId("purpose-speech").click();
  await expect(page.getByTestId("library-total")).toHaveText("3 个采样");
  await page.getByTestId("sample-row").first().focus();
  await page.keyboard.press("0");
  await expect(page.getByTestId("sample-row").filter({ hasText: "一" }).getByTestId("row-reclassified")).toHaveText("已归类为未分类");
  await expect(page.getByTestId("sample-row")).toHaveCount(3);
  await page.getByTestId("refresh-lists").click();
  await expect(page.getByTestId("library-total")).toHaveText("2 个采样");
  await app.close();
});
