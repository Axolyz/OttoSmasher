import { execFileSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch, refreshLists } from "./helpers";

// 所有者 2026-10-30：有时播完按钮停在“停止”，要点别的行才复位。很短的片段、同一个文件接连试听最容易出现
// （上一段停在结尾留下 eof-reached，下一段的结束变化可能被引擎合并掉）。每一段都要自己复位。
test("采样列表：播完、改 BPM、切换试听和手动停止都复位", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-playend-"));
  const wav = join(dir, "playend.wav");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6", wav]);
  const { app, page } = await launch();
  try {
    await page.evaluate(async (p) => {
      const req = window.otto.core.request;
      const add = (await req("sources.add", { paths: [p] })) as { r: Array<{ assets: Array<{ assetId: string }> }> };
      const aid = add.r[0]!.assets[0]!.assetId;
      for (const [s, n] of [[1.0, "短A"], [2.0, "短B"], [3.0, "短C"]] as const) {
        await req("samples.create", { assetId: aid, start: s, end: s + 0.12, name: n, nature: "speech" });
      }
      await req("samples.create", { assetId: aid, start: 0, end: 5, name: "长A", nature: "speech" });
      await req("samples.create", { assetId: aid, start: 1, end: 6, name: "长B", nature: "speech" });
    }, wav);
    await page.getByTestId("nav-library").click();
    await refreshLists(page);
    const button = (name: string) => page.getByTestId("sample-row").filter({ hasText: name }).getByTestId("sample-play");
    for (const name of ["短A", "短B", "短A", "短C", "短C"]) {
      await button(name).click();
      await expect(button(name)).toHaveAttribute("data-playing", "true", { timeout: 3000 }).catch(() => {}); // 太短可能来不及看到
      await expect(button(name)).not.toHaveAttribute("data-playing", "true", { timeout: 4000 });
    }

    const dock = page.getByTestId("dock-now");
    await button("长A").click();
    await expect(dock).toContainText("长A");
    await expect(button("长A")).toHaveAttribute("data-playing", "true");
    const bpm = page.getByTestId("bpm");
    await bpm.fill("180");
    await bpm.press("Enter");
    await expect(page.getByText(/BPM 180 · 已停止试听/)).toBeVisible();
    await expect(button("长A")).not.toHaveAttribute("data-playing", "true");
    await expect(dock).toContainText("没有在播放");

    await button("长A").click();
    await expect(dock).toContainText("长A");
    await button("长B").click();
    await expect(dock).toContainText("长B");
    await expect(button("长A")).not.toHaveAttribute("data-playing", "true");
    await expect(button("长B")).toHaveAttribute("data-playing", "true");
    await page.getByTestId("dock-stop").click();
    await expect(button("长B")).not.toHaveAttribute("data-playing", "true");
    await expect(dock).toContainText("没有在播放");
  } finally {
    await app.close();
  }
});
