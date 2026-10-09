import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 查找栏与范围行（规格 07 §7.1–§7.3、16 R8.1–R8.2、R8.5；UI_PLAN §2.3）：「＋」分面块（带计数）、人物“只要单人”、主表达式报位置、
// 存为筛选器 → 选用 → 已修改 · 更新、排序菜单、重启恢复条件。
const SHOTS = ".cache/compare/shots/stage8";

test("范围行：分面、表达式、保存筛选器、排序", async () => {
  test.setTimeout(120_000);
  mkdirSync(SHOTS, { recursive: true });
  const base = mkdtempSync(join(tmpdir(), "otto-scope-"));
  const wav = join(base, "s.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=44100:duration=6", wav]);
  const workspace = join(base, "工作区 scope");
  let { app, page } = await launch({ workspace });
  await page.setViewportSize({ width: 1536, height: 864 });
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ sourceId: string; assets: Array<{ assetId: string }> }> };
    const aid = add.r[0]!.assets[0]!.assetId;
    const mk = async (name: string, a: number, tags: string[]) => {
      const c = (await req("samples.create", { assetId: aid, start: a, end: a + 0.5, name, nature: "speech" })) as { r: { id: string; version: number } };
      await req("edits.apply", { batch: { ops: [{ entity: "sample", id: c.r.id, version: c.r.version, fields: { local_tags: tags } }] } });
    };
    await mk("あ京子A4", 0, ["character:京子", "pitch:A4"]);
    await mk("い京子", 1, ["participants:京子", "participants:結衣", "speaker-status:多人未分段"]);
    await mk("う結衣A4", 2, ["character:結衣", "pitch:A4"]);
    await mk("え無", 3, ["好用"]);
  }, wav);
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await expect(page.getByTestId("library-total")).toHaveText("4 个采样");

  // 「＋」：聚焦即展开分面建议（带计数），输入过滤，选中 → 人物块
  await page.getByTestId("scope-add").click();
  await expect(page.getByTestId("scope-add-list")).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/02-scope-suggest.png` });
  await page.getByTestId("scope-add").fill("京");
  await page.getByTestId("scope-add-list").getByRole("option", { name: /京子/ }).click();
  await expect(page.getByTestId("scope-chips")).toContainText("人物京子");
  await expect(page.getByTestId("library-total")).toHaveText("2 个采样");
  // 单击人物块 = 只要单人
  await page.getByTestId("scope-chips").getByText("京子", { exact: true }).click();
  await expect(page.getByTestId("scope-chips")).toContainText("（单人）");
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await page.getByTestId("scope-chips").getByText("京子", { exact: true }).click();
  await expect(page.getByTestId("library-total")).toHaveText("2 个采样");

  // 主表达式：出错标红并写出位置，列表保持上一次有效的条件；改对了才生效（NOT 的补集只在范围里取）
  await page.getByTestId("library-expr").fill("a b");
  await expect(page.getByTestId("expr-error")).toHaveText("标签表达式第 3 个字符：需要 AND 或 OR");
  await expect(page.getByTestId("library-total")).toHaveText("2 个采样");
  await page.getByTestId("library-expr").fill('NOT "pitch:A4"');
  await expect(page.getByTestId("expr-error")).toHaveCount(0);
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await page.screenshot({ path: `${SHOTS}/01-library-scope.png` });

  // 存为筛选器（不含主表达式）→ ⚑ 显示名字；改范围 → 已修改 · 更新
  await page.getByTestId("scope-save").click();
  await page.getByTestId("filter-name").fill("京子的");
  await page.screenshot({ path: `${SHOTS}/04-save-filter.png` });
  await page.getByTestId("filter-save").getByTestId("confirm-ok").click();
  await expect(page.getByTestId("scope-preset")).toContainText("京子的");
  const saved = await page.evaluate(async () => ((await window.otto.core.request("filters.list", {})) as { r: Array<{ conditions: unknown }> }).r);
  expect(saved).toEqual([expect.objectContaining({ conditions: { facets: [{ facet: "person", values: ["京子"], single: false }], expr: "" } })]);
  await page.getByTestId("scope-add").click();
  await page.getByTestId("scope-add").fill("A4");
  await page.getByTestId("scope-add-list").getByRole("option", { name: /A4/ }).click();
  await expect(page.getByTestId("scope-modified")).toBeVisible();
  await page.getByTestId("scope-update").click();
  await expect(page.getByTestId("scope-modified")).toHaveCount(0);

  // 筛选器菜单：全部采样（清空范围）→ 选用“京子的”= 用它替换范围行
  await page.getByTestId("library-expr").fill("");
  await page.getByTestId("scope-preset").click();
  await page.screenshot({ path: `${SHOTS}/03-preset-menu.png` });
  await page.getByTestId("menu-preset-clear").click();
  await expect(page.getByTestId("library-total")).toHaveText("4 个采样");
  await page.getByTestId("scope-preset").click();
  await page.getByRole("menuitem", { name: /京子的/ }).click();
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");

  // 排序：按名称
  await page.getByTestId("menu-preset-clear").count();
  await page.getByTestId("scope-preset").click();
  await page.getByTestId("menu-preset-clear").click();
  await page.getByTestId("library-sort").click();
  await page.getByTestId("menu-sort-name").click();
  await expect(page.getByTestId("sample-row").first()).toContainText("あ京子A4");
  await page.getByTestId("library-sort").click();
  await page.getByTestId("menu-sort-created").click();
  await expect(page.getByTestId("sample-row").first()).toContainText("え無");

  // ⌘⇧F 聚焦范围行「＋」；重启恢复条件（筛选器、表达式、星标）
  await page.getByTestId("library-expr").fill("好用");
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await page.keyboard.press("Meta+Shift+f");
  await expect(page.getByTestId("scope-add")).toBeFocused();
  await page.waitForTimeout(500);
  await app.close();
  ({ app, page } = await launch({ workspace }));
  await page.getByTestId("nav-library").click();
  await expect(page.getByTestId("library-expr")).toHaveValue("好用");
  await expect(page.getByTestId("library-total")).toHaveText("1 个采样");
  await app.close();
});
