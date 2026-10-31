import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 台词搜索（所有者 2026-10-31）：搜文本层（原料），结果是原片上的位置，不是采样。
// 台本里搜这一集：命中高亮、回车 / Shift 回车跳（= 单击那一行）、Esc 清空；原素材列表的搜索框同时搜全部原素材的台词：单击一处打开那一集并选中那一段；
// 关联了字幕但没导入的原素材写明搜不到。
test("台词搜索：台本里跳转、全部原素材里搜、没导入的提示", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-lines-"));
  const mk = (name: string, srt: string | null) => {
    const mkv = join(dir, `[Group] Lines Show [${name}].mkv`);
    execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=24:duration=12",
      "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=12", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
    if (srt) writeFileSync(join(dir, `[Group] Lines Show [${name}].srt`), srt);
    return mkv;
  };
  const cue = (n: number, a: number, text: string) => `${n}\n00:00:0${a},000 --> 00:00:0${a},800\n${text}\n\n`;
  const e1 = mk("01", cue(1, 1, "（京子）今日はいい天気") + cue(2, 3, "（結衣）そうだね") + cue(3, 5, "（京子）明日もいい天気かな") + cue(4, 7, "（足音）"));
  const e2 = mk("02", cue(1, 2, "（綾乃）天気予報、見た？") + cue(2, 4, "（千歳）ううん"));
  const e3 = mk("03", cue(1, 1, "（京子）天気"));
  const { app, page } = await launch();
  type R<T> = { ok: boolean; r: T; e?: unknown };
  const req = async <T,>(m: string, p: Record<string, unknown>) => {
    const res = (await page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const)) as R<T>;
    if (!res.ok) throw new Error(`${m}: ${JSON.stringify(res.e)}`);
    return res.r;
  };
  await page.keyboard.press("Meta+2");
  const ids = (await req<Array<{ sourceId: string }>>("sources.add", { paths: [e1, e2, e3] })).map((x) => x.sourceId);
  await page.keyboard.press("Escape");
  for (const sid of ids.slice(0, 2)) {
    const pv = await req<{ token: string }>("subtitles.preview", { sourceId: sid });
    await req("subtitles.import", { sourceId: sid, token: pv.token });
  }

  // 1) 台本：打开第 1 集，搜「天気」→ 两处；回车跳到第一处（选区 = 那一段），再回车第二处，Shift+回车回到第一处；Esc 清空
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").filter({ hasText: "01" }).click();
  const search = page.getByTestId("transcript-search");
  await page.keyboard.press("Meta+Shift+f");
  await expect(search).toBeFocused();
  await search.fill("天気");
  const count = page.getByTestId("transcript-search-count");
  await expect(count).toHaveText("2 处");
  await expect(page.locator('[data-testid="transcript-row"] mark')).toHaveCount(2);
  await search.press("Enter");
  await expect(count).toHaveText("1 / 2");
  const rows = page.getByTestId("transcript-row");
  await expect(rows.nth(0)).toHaveAttribute("data-selected-row", "true");
  await search.press("Enter");
  await expect(count).toHaveText("2 / 2");
  await expect(rows.nth(2)).toHaveAttribute("data-selected-row", "true");
  await search.press("Shift+Enter");
  await expect(rows.nth(0)).toHaveAttribute("data-selected-row", "true");
  await expect(search).toBeFocused(); // 跳转不抢走搜索框的焦点
  await page.screenshot({ path: ".cache/playwright-results/transcript-search.png" });
  await search.press("Escape");
  await expect(count).toHaveCount(0);

  // 2) 全部原素材：⌘F → 列表的搜索框；「天気」→ 两个原素材三处（音效提示不算）；第 3 集关联了字幕没导入 → 提示
  await page.keyboard.press("Meta+f");
  const box = page.getByTestId("sources-search");
  await expect(box).toBeFocused();
  await box.fill("天気");
  await expect(page.getByTestId("line-search-count")).toHaveText("3 处（2 个原素材）");
  await expect(page.getByTestId("line-search-not-imported")).toContainText("1 个原素材");
  // 单击第 2 集的那一处 → 打开第 2 集、选中那一段
  await page.getByTestId("line-hit").filter({ hasText: "天気予報" }).click();
  await expect(page.getByTestId("transcript-row").nth(0)).toHaveAttribute("data-selected-row", "true");
  await expect(page.getByTestId("transcript-row").nth(0)).toContainText("天気予報");
  // 音效提示也搜（单独标“音效”）
  await box.fill("足音");
  await expect(page.getByTestId("line-hit").filter({ hasText: "足音" })).toContainText("音效");
  await box.fill("天気");
  await expect(page.getByTestId("line-search")).not.toHaveAttribute("data-stale");
  await page.screenshot({ path: ".cache/playwright-results/line-search.png" });
  await app.close();
});
