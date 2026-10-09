import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 真实字幕（只读引用交接包 fixtures）：S1.1 自动关联、S1.4 导入后采样数 0、导入到文本层（所有者 2026-10-09：四类一起进，不分版本）、
// 再导入同一文件全部无变化、改过的段受保护（再导入跳过）、原版未校正（整体晚 0.404 秒）替换未受保护的段、S11.4 机器转写全是台词
const FIX = process.env.OTTO_FIXTURES;
test.skip(!FIX, "需要 OTTO_FIXTURES 指向交接包的 fixtures 目录");

type R<T> = { ok: boolean; r: T };
type Cat = Record<"new" | "unchanged" | "replace" | "skip" | "excluded" | "invalid" | "removed" | "removedAnalyzed" | "removedProtected", number>;
type Pv = {
  token: string;
  counts: { segments: Cat; hints: Cat; oped: Cat };
  segments: Array<{ text: string; speakers: string[]; status: string; reason: string | null }>;
  hints: unknown[];
  oped: { pairs: unknown[]; errors: unknown[] };
};
test("真实字幕 YY1-01：导入到文本层、再导入、受保护的段、未校正版、机器转写", async () => {
  const dir = join(FIX!, "episodes", "YY1-01");
  const ep = join(dir, "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv");
  const { app, page } = await launch();
  const req = <T>(m: string, p: Record<string, unknown>) => page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const) as Promise<R<T>>;
  const add = await req<Array<{ sourceId: string }>>("sources.add", { paths: [ep] });
  const sid = add.r[0]!.sourceId;
  const src = await req<{ subtitle_path: string | null }>("sources.get", { id: sid });
  expect(src.r.subtitle_path).toMatch(/Yuru Yuri \[01\].*\.srt$/); // S1.1 自动关联同名 .srt

  const pv = await req<Pv>("subtitles.preview", { sourceId: sid });
  console.log("YY1-01 counts", JSON.stringify(pv.r.counts));
  const imp = await req<{ created: { segments: number; hints: number; oped: number }; opedErrors: number }>("subtitles.import", { sourceId: sid, token: pv.r.token });
  expect(imp.r.created.segments).toBe(pv.r.counts.segments.new);
  expect(imp.r.created.hints).toBe(pv.r.counts.hints.new);
  const total = await req<{ total: number }>("samples.list", { offset: 0, limit: 1 });
  expect(total.r.total).toBe(0); // S1.4

  // S1.5：OP/ED 规则无错 → 随导入登记：OP ≈ 84.247–172.768、ED ≈ 1330.558–1419.114（来源“字幕规则”）
  expect([imp.r.created.oped, imp.r.opedErrors]).toEqual([2, 0]);
  const list = await req<Array<{ kind: string; start: number; end: number; via: string }>>("oped.list", { sourceId: sid });
  expect(list.r.map((o) => [o.kind, o.start, o.end, o.via])).toEqual([["OP", 84.247, 172.768, "rule"], ["ED", 1330.558, 1419.114, "rule"]]);

  // 再导入同一文件：全部无变化
  const again = await req<Pv>("subtitles.preview", { sourceId: sid });
  expect([again.r.counts.segments.new, again.r.counts.segments.replace, again.r.counts.segments.unchanged]).toEqual([0, 0, imp.r.created.segments]);
  expect([again.r.counts.hints.unchanged, again.r.counts.oped.unchanged]).toEqual([imp.r.created.hints, 2]);

  // 改过一段 → 受保护：再导入时与它交叠的行跳过
  type Seg = { id: string; version: number; text: string };
  const segs = (await req<{ segments: Seg[] }>("textLayer.list", { sourceId: sid })).r.segments;
  const edited = segs[10]!;
  await req("edits.apply", { batch: { ops: [{ entity: "segment", id: edited.id, version: edited.version, fields: { text: `${edited.text}！` } }] } });
  const pv1 = await req<Pv>("subtitles.preview", { sourceId: sid });
  expect([pv1.r.counts.segments.skip, pv1.r.counts.segments.unchanged]).toEqual([1, imp.r.created.segments - 1]);
  expect(pv1.r.segments.find((x) => x.status === "skip")!.reason).toBe("protected");

  // S11.3（改为文本层语义）：原版未校正（整体晚 0.404 秒）→ 与未受保护的段交叠的替换，碰到改过那段的跳过
  const { readdirSync } = await import("node:fs");
  const others = readdirSync(join(dir, "其他字幕版本"));
  const orig = join(dir, "其他字幕版本", others.find((f) => f.startsWith("原版未校正"))!);
  const pv2 = await req<Pv>("subtitles.preview", { sourceId: sid, path: orig });
  console.log("YY1-01 原版未校正 counts", JSON.stringify(pv2.r.counts));
  expect(pv2.r.counts.segments.replace).toBeGreaterThan(300);
  expect(pv2.r.counts.segments.skip).toBeGreaterThanOrEqual(1);
  expect(pv2.r.counts.segments.removedProtected).toBe(0);

  // S11.4：机器转写（无 BOM、CRLF、没有说话人与音效标注）→ 全部是台词段、没有说话人、没有音效提示
  const mt = join(dir, "其他字幕版本", others.find((f) => f.startsWith("机器转写"))!);
  const pv4 = await req<Pv>("subtitles.preview", { sourceId: sid, path: mt });
  expect(pv4.r.hints.length).toBe(0);
  expect(pv4.r.segments.every((l) => l.speakers.length === 0)).toBe(true);
  console.log("machine lines", pv4.r.segments.length);
  await app.close();
});
