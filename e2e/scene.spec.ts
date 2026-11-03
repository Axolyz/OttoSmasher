import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 场景 F（所有者 2026-10-09）：开着原素材、挂上字幕，看到哪句好就直接从这句建采样（台本行、画内字幕、波形上的段右键都可以），
// 音效提示对应的位置也能直接建；逐句建与批量建是同一个动作，产物完全相同。建完留在原素材页。
test("看片逐句建采样：台本行、画内字幕、音效提示；逐句与批量产物相同", async () => {
  const dir = mkdtempSync(join(tmpdir(), "otto-scene-"));
  const mkv = join(dir, "[Group] Scene Show [01].mkv");
  execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=8",
    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=8", "-c:v", "libx264", "-c:a", "flac", mkv]);  // prettier-ignore
  writeFileSync(join(dir, "[Group] Scene Show [01].srt"), "1\n00:00:01,000 --> 00:00:02,000\n（京子）こんにちは\n\n2\n00:00:04,000 --> 00:00:05,000\n（足音）\n");
  const { app, page } = await launch();
  type R<T> = { ok: boolean; r: T; e?: unknown };
  const req = async <T>(m: string, p: Record<string, unknown>) => {
    const res = (await page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const)) as R<T>;
    if (!res.ok) throw new Error(`${m}: ${JSON.stringify(res.e)}`);
    return res.r;
  };
  await page.keyboard.press("ControlOrMeta+2");
  const sid = (await req<Array<{ sourceId: string }>>("sources.add", { paths: [mkv] }))[0]!.sourceId;
  await req("subtitles.importDefault", { sourceId: sid });
  // 原混音设为默认人声轨（同时赋予人声角色）
  const tk = await req<{ sourceVersion: number; tracks: Array<{ id: string; version: number }> }>("assets.tracks", { sourceId: sid });
  const aid = tk.tracks[0]!.id;
  await req("edits.apply", {
    batch: {
      ops: [
        { entity: "asset", id: aid, version: tk.tracks[0]!.version, fields: { roles: ["vocal"] } },
        { entity: "source", id: sid, version: tk.sourceVersion, fields: { default_vocal: aid } },
      ],
    },
  });
  await page.keyboard.press("Escape");
  await page.getByTestId("source-group").first().click();
  await page.getByTestId("source-row").first().click();
  await expect(page.getByTestId("source-viewer").getByTestId("timeline-status")).toHaveCount(0, { timeout: 15000 });

  // 1) 台本行右键 → 这段的菜单 →「从这段建采样…」：小面板贴着右键位置；名称 = 段文本，判定区间 = 段；默认建在默认人声轨上
  const row = page.getByTestId("transcript-row").first();
  await row.click({ button: "right" });
  const menu = page.getByTestId("segment-menu");
  await expect(menu).toContainText("台词段「こんにちは」");
  await menu.getByTestId(/^menu-seg-clip:/).click();
  const panel = page.getByTestId("clip-panel");
  await expect(panel.getByTestId("clip-name")).toHaveValue("こんにちは");
  await expect(panel.getByTestId("clip-track").getByRole("radio", { name: "默认人声轨" })).toHaveAttribute("data-selected", "true");
  await expect(panel).toContainText("判定区间 0:01.000–0:02.000");
  await page.screenshot({ path: ".cache/playwright-results/scene-clip.png" });
  await panel.getByTestId("clip-save").click();
  await expect(page.getByText("已建立采样「こんにちは」")).toBeVisible();
  await expect(page.getByTestId("source-viewer")).toBeVisible(); // 留在原素材页

  // 2) 画内字幕右键：同一个菜单（单击台本行 = 跳到这段开头，画面里显示这段文字）
  await row.click();
  const sub = page.getByTestId("video-subtitle");
  await expect(sub).toHaveText("こんにちは");
  await sub.click({ button: "right" });
  await expect(menu).toContainText("台词段「こんにちは」");
  await page.keyboard.press("Escape");

  // 3) 音效提示：覆盖层换成「音效提示」→ 波形上右键这条提示 →「从这条提示建采样…」：在当前查看的轨上，名称 = 括号内容，性质 = 非调谐单音
  await page.getByTestId("layer-bar").getByRole("radio", { name: "音效提示" }).click();
  const tl = page.getByTestId("source-viewer").getByTestId("timeline");
  const box = (await tl.boundingBox())!;
  const [v0, v1] = (await tl.getAttribute("data-view"))!.split(",").map(Number) as [number, number];
  await page.mouse.click(box.x + ((4.5 - v0) / (v1 - v0)) * box.width, box.y + 50, { button: "right" });
  const tlMenu = page.getByTestId("timeline-menu");
  await expect(tlMenu).toContainText("音效提示「足音」");
  await tlMenu.getByTestId(/^menu-hint-clip:/).click();
  await expect(panel.getByTestId("clip-name")).toHaveValue("足音");
  await expect(panel.getByTestId("clip-nature").getByRole("radio", { name: "非调谐单音" })).toHaveAttribute("data-selected", "true");
  await panel.getByTestId("clip-save").click();
  await expect(page.getByText("已建立采样「足音」")).toBeVisible();

  // 4) 同一段批量建一次：产物与逐句建的完全相同（资产、范围、名称、性质、判定区间、来源）
  await page.getByTestId("viewer-menu").click();
  await page.getByTestId("menu-newsamples-segments").click();
  const sheet = page.getByTestId("new-samples");
  await sheet.getByTestId("table-row").first().locator("label").first().click();
  await sheet.getByTestId("newsamples-run").click();
  await expect(page.getByText(/已建立 1 个采样/)).toBeVisible();
  type Row = { id: string; name: string; asset_id: string; start: number; end: number; nature: string; created_via: string };
  const rows = (await req<{ rows: Row[] }>("samples.list", { offset: 0, limit: 10 })).rows.filter((r) => r.name === "こんにちは");
  expect(rows).toHaveLength(2);
  const shape = async (r: Row) => ({ ...r, id: undefined, created_at: undefined, judge: (await req<{ judge: number[] }>("speech.sample", { id: r.id })).judge });
  expect(await shape(rows[0]!)).toEqual(await shape(rows[1]!));
  expect(rows[0]!.created_via).toBe("segment");
  expect(rows[0]!.nature).toBe("speech");
  await app.close();
});
