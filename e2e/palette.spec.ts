import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 命令面板（⌘K，所有者 2026-10-10 简单版）：作用于当前查看的采样 / 已勾选集（与右键同一份菜单）、本页动作、全局；
// 输入框里也能打开；子串过滤、回车执行；数字 = 设 BPM；设置分组直达；最近用过排最上面。
const SHOTS = ".cache/compare/shots/stage9";

test("命令面板：对象命令、过滤、BPM、设置分组、最近用过", async () => {
  test.setTimeout(90_000);
  mkdirSync(SHOTS, { recursive: true });
  const wav = join(mkdtempSync(join(tmpdir(), "otto-palette-")), "p.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=44100:duration=6", wav]);
  const { app, page } = await launch();
  await page.setViewportSize({ width: 1536, height: 864 });
  await page.evaluate(async (p) => {
    const req = window.otto.core.request;
    const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
    const aid = add.r[0]!.assets[0]!.assetId;
    for (const [n, a] of [["一番", 0], ["二番", 2]] as const) await req("samples.create", { assetId: aid, start: a, end: a + 0.5, name: n, nature: "unclassified" });
  }, wav);
  await page.getByTestId("nav-library").click();
  await refreshLists(page);
  await page.getByTestId("sample-row").filter({ hasText: "二番" }).click();

  // 顶栏按钮打开；空输入：最上面是“当前查看的采样”的命令（右键菜单那一份），然后本页、全局
  await page.getByTestId("palette-open").click();
  const pal = page.getByTestId("palette");
  await expect(pal).toBeVisible();
  await expect(pal).toContainText("当前查看的采样：二番");
  await expect(pal.getByTestId("palette-item").first()).toHaveAttribute("data-command", "library-target/audition");
  await page.waitForTimeout(300); // 升起动画
  await page.screenshot({ path: `${SHOTS}/10-palette.png` });

  // 子串过滤：“编辑资料” → 回车 → 只作用于当前采样的编辑资料对话框
  await page.getByTestId("palette-input").fill("编辑资料");
  await expect(pal.getByTestId("palette-item").first()).toHaveAttribute("data-command", "library-target/edit");
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${SHOTS}/11-palette-filter.png` });
  await page.keyboard.press("Enter");
  await expect(pal).toHaveCount(0);
  await expect(page.getByTestId("batch-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("batch-dialog")).toHaveCount(0);

  // 输入框里也能打开（⌘K）；子菜单展开成“父 › 子”：设性质 › 语音
  await page.getByTestId("library-search").click();
  await page.keyboard.press("ControlOrMeta+k");
  await expect(pal).toBeVisible();
  await page.getByTestId("palette-input").fill("性质 语音");
  await expect(pal.getByTestId("palette-item").first()).toContainText("性质 › 语音");
  await page.keyboard.press("Enter");
  await expect.poll(() => page.evaluate(async () => ((await window.otto.core.request("samples.list", { natures: ["speech"] })) as { r: { total: number } }).r.total)).toBe(1);

  // 数字 = 设 BPM
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByTestId("palette-input").fill("180");
  await expect(pal.getByTestId("palette-item").first()).toHaveText(/BPM 设为 180/);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("bpm")).toHaveValue("180");

  // 设置分组直达：存储与缓存
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByTestId("palette-input").fill("存储");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("storage-panel")).toBeVisible();
  await page.keyboard.press("Escape");

  // 已勾选集：命令写明“已勾选 N 项”；最近用过排在空输入的最上面；没有匹配时就地说明
  await page.getByTestId("sample-row").first().focus();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.press("ControlOrMeta+k");
  await expect(pal).toContainText("最近用过");
  await expect(pal).toContainText("作用于：已勾选 2 项");
  await page.getByTestId("palette-input").fill("没有这种命令");
  await expect(pal).toContainText("没有匹配的命令");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Escape");
  await expect(pal).toHaveCount(0);

  // 原素材页：作用于当前原素材 / 添加原素材；切页命令
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByTestId("palette-input").fill("前往原素材");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("page-sources")).toBeVisible();
  await page.keyboard.press("ControlOrMeta+k");
  await expect(pal).toContainText("添加原素材…");
  await page.keyboard.press("Escape");
  await app.close();
});
