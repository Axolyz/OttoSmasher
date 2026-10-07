import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 真实字幕（只读引用交接包 fixtures）：S1.1 自动关联、S1.4 导入后采样数 0、S11.3 版本切换、S11.4 机器转写全是台词
const FIX = process.env.OTTO_FIXTURES;
test.skip(!FIX, "需要 OTTO_FIXTURES 指向交接包的 fixtures 目录");

type R<T> = { ok: boolean; r: T };
test("真实字幕 YY1-01：导入、版本切换、机器转写", async () => {
  const dir = join(FIX!, "episodes", "YY1-01");
  const ep = join(dir, "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv");
  const { app, page } = await launch();
  const req = <T>(m: string, p: Record<string, unknown>) => page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const) as Promise<R<T>>;
  const add = await req<Array<{ sourceId: string }>>("sources.add", { paths: [ep] });
  const sid = add.r[0]!.sourceId;
  const src = await req<{ subtitle_path: string | null }>("sources.get", { id: sid });
  expect(src.r.subtitle_path).toMatch(/Yuru Yuri \[01\].*\.srt$/); // S1.1 自动关联同名 .srt

  type Pv = { token: string; versionState: string; counts: Record<string, number>; lines: Array<{ kind: string; speakers: string[] }> };
  const pv = await req<Pv>("subtitles.preview", { sourceId: sid });
  console.log("YY1-01 counts", JSON.stringify(pv.r.counts));
  const imp = await req<{ imported: number; versionId: string }>("subtitles.import", { sourceId: sid, token: pv.r.token });
  expect(imp.r.imported).toBe(pv.r.counts.importable + pv.r.counts.oped);
  const total = await req<{ total: number }>("samples.list", { offset: 0, limit: 1 });
  expect(total.r.total).toBe(0); // S1.4

  // S11.3：原版未校正（整体晚 0.404 秒）→ 新版本成为当前；重新导入校正版 → 切回
  const { readdirSync } = await import("node:fs");
  const others = readdirSync(join(dir, "其他字幕版本"));
  const orig = join(dir, "其他字幕版本", others.find((f) => f.startsWith("原版未校正"))!);
  const pv2 = await req<Pv>("subtitles.preview", { sourceId: sid, path: orig });
  expect(pv2.r.versionState).toBe("new");
  const imp2 = await req<{ versionId: string; newVersion: boolean }>("subtitles.import", { sourceId: sid, token: pv2.r.token, path: orig });
  expect(imp2.r.newVersion).toBe(true);
  const back = await req<Pv>("subtitles.preview", { sourceId: sid });
  expect(back.r.versionState).toBe("switch");
  const imp3 = await req<{ versionId: string; switched: boolean }>("subtitles.import", { sourceId: sid, token: back.r.token });
  expect([imp3.r.switched, imp3.r.versionId]).toEqual([true, imp.r.versionId]);

  // S11.4：机器转写（无 BOM、CRLF、没有说话人与音效标注）→ 全部是台词、没有说话人
  const mt = join(dir, "其他字幕版本", others.find((f) => f.startsWith("机器转写"))!);
  const pv4 = await req<Pv>("subtitles.preview", { sourceId: sid, path: mt });
  expect(pv4.r.lines.every((l) => l.kind === "line" && l.speakers.length === 0)).toBe(true);
  console.log("machine lines", pv4.r.lines.length);
  await app.close();
});
