import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { launch } from "./helpers";

// 真实外部音频的采样库导入（只读引用交接包 fixtures/external_audio，原地登记、不复制）：
// 封面图不能当画面；整段采样用确切时长；单独选的 MP4（视频从 0.125 秒开始）按原素材导入并有缩略图
const FIX = process.env.OTTO_FIXTURES;
test.skip(!FIX, "需要 OTTO_FIXTURES 指向交接包的 fixtures 目录");

type R<T> = { ok: boolean; r: T };
type Job = { id: string; status: string };
test("真实外部音频：文件夹导入与单个 MP4", async () => {
  test.setTimeout(120_000);
  const dir = join(FIX!, "external_audio");
  const { page } = await launch();
  const req = <T>(m: string, p: Record<string, unknown>) =>
    page.evaluate(async ([mm, pp]) => window.otto.core.request(mm as string, pp as Record<string, unknown>), [m, p] as const) as Promise<R<T>>;
  const scan = async (paths: string[]) => {
    const j = await req<Job>("imports.scan", { paths });
    await expect.poll(async () => (await req<Job[]>("jobs.list", {})).r.find((x) => x.id === j.r.id)?.status, { timeout: 60000 }).toBe("succeeded");
    return j.r.id;
  };

  const j1 = await scan([dir]);
  const pv = await req<{ importable: number; withPicture: number; unreadable: unknown[] }>("imports.preview", { jobId: j1 });
  // 文件夹里的音频和视频都导入：番凩 MP3 + reimport/ 里 3 个 WAV + 千鹤 MP4（没有同名音频 → 单独导入）
  expect([pv.r.importable, pv.r.withPicture, pv.r.unreadable.length]).toEqual([5, 0, 0]);
  const c1 = await req<{ created: number; sampleIds: string[] }>("imports.commit", { jobId: j1, work: "外部", sourceType: "", wholeSample: true, nature: "unclassified", bindPictures: true });
  expect(c1.r.created).toBe(5);
  const lens = await Promise.all(c1.r.sampleIds.map(async (id) => (await req<{ name: string; duration: number }>("samples.get", { id })).r));
  const byName = Object.fromEntries(lens.map((x) => [x.name, x.duration]));
  expect(byName["仕事してP MEIKO KAITO - 番凩-2019-"]).toBeCloseTo(222, 0);
  expect(byName["歳納京子！ · G♯5__8ca511050f35"]).toBeCloseTo(0.627, 3);
  expect(byName["千鹤吉他__cf6947c5be6a"]).toBeCloseTo(0.956, 3);
  // 封面图不是画面：MP3 原素材没有缩略图
  const srcs = await req<Array<{ id: string; path: string; has_video: boolean; has_picture: boolean }>>("sources.list", {});
  const mp3 = srcs.r.find((x) => x.path.endsWith(".mp3"))!;
  expect([mp3.has_video, mp3.has_picture]).toEqual([false, false]);
  expect((await req<Array<{ state: string }>>("thumbs.get", { items: [{ kind: "source", id: mp3.id }] })).r[0]!.state).toBe("none");

  // 再单独选这个 MP4：已登记过 → 不重复登记，再建一个整段采样（所有者 2026-10-07）
  const j2 = await scan([join(dir, "千鹤弹吉他_消音.30775247570.mp4")]);
  const c2 = await req<{ created: number; existing: number; sampleIds: string[] }>("imports.commit", { jobId: j2, work: "外部", sourceType: "", wholeSample: true, nature: "pitched", bindPictures: true });
  expect([c2.r.created, c2.r.existing, c2.r.sampleIds.length]).toEqual([0, 1, 1]);
  const mp4 = (await req<Array<{ id: string; path: string; has_video: boolean }>>("sources.list", {})).r.find((x) => x.path.endsWith(".mp4"))!;
  expect(mp4.has_video).toBe(true);
  await expect.poll(async () => (await req<Array<{ state: string }>>("thumbs.get", { items: [{ kind: "source", id: mp4.id }] })).r[0]!.state, { timeout: 20000 }).toBe("ready");
});
