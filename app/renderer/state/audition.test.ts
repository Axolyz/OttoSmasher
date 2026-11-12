import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { PlayerApi, PlayerState } from "../../shared/protocol";
import { lastSampleAuditionPosition, onAuditionState, startAudition, stopAudition, useAudition } from "./audition";
import { useApp } from "./store";

const audio = { assetId: "asset", start: 5, end: 5.12 };
const player = {
  audition: vi.fn<PlayerApi["audition"]>(),
  position: vi.fn<PlayerApi["position"]>(),
  stopAudition: vi.fn<PlayerApi["stopAudition"]>(),
};
let gen: number;

const start = (sampleId: string, prepare: () => typeof audio | Promise<typeof audio> = () => audio) =>
  startAudition({ target: { kind: "sample", sampleId }, name: sampleId }, prepare);

const state = (fields: Partial<PlayerState> = {}): PlayerState =>
  ({ player: "audition", gen, time: null, playing: false, loading: false, ended: false, ...fields });

beforeEach(() => {
  gen = 0;
  vi.stubGlobal("otto", { player });
  player.position.mockReturnValue(null);
  player.audition.mockImplementation(async (_asset, _start, _end, _loop, _sample, onBegin) => {
    onBegin?.(++gen);
    return gen;
  });
});

afterEach(() => {
  stopAudition();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

it("接住启动请求返回前的结束事件，光标贴到资产区间终点", async () => {
  player.audition.mockImplementationOnce(async (_asset, _start, _end, _loop, _sample, onBegin) => {
    onBegin?.(++gen);
    onAuditionState(state({ ended: true, time: audio.end - audio.start }));
    return gen;
  });
  await start("short");
  expect(useAudition.getState().current).toBeNull();
  expect(lastSampleAuditionPosition("short")).toBe(audio.end);
});

it.each(["停止", "替换"])("准备中的旧试听被%s后，迟到的结果不会开播", async (action) => {
  let ready!: (value: typeof audio) => void;
  const prepared = new Promise<typeof audio>((resolve) => { ready = resolve; });
  const first = start("first", () => prepared);
  if (action === "停止") stopAudition();
  else await start("second");
  ready(audio);
  await first;
  expect(player.audition.mock.calls.map((call) => call[4])).toEqual(action === "停止" ? [] : ["second"]);
});

it("旧代次的结束事件不会清掉新的试听，原片接管时保留最后位置", async () => {
  await start("first");
  const firstGen = gen;
  await start("second");
  onAuditionState(state({ gen: firstGen, ended: true }));
  expect(useAudition.getState().current?.request.name).toBe("second");
  player.position.mockReturnValue(0.06);
  onAuditionState(state({ playing: true, time: 0.06 }));
  onAuditionState(state({ gen: gen + 1 }));
  expect(useAudition.getState().current).toBeNull();
  expect(lastSampleAuditionPosition("second")).toBe(5.06);
});

it("当前试听失败只清理和提示一次", async () => {
  const toast = vi.spyOn(useApp.getState(), "toast").mockReturnValue(0);
  const error = { code: "playback-failed", args: { detail: "unreadable" } };
  try {
    player.audition.mockImplementationOnce(async (_asset, _start, _end, _loop, _sample, onBegin) => {
      onBegin?.(++gen);
      onAuditionState(state({ error }));
      throw error;
    });
    await start("broken");
    expect(useAudition.getState().current).toBeNull();
    expect(toast).toHaveBeenCalledExactlyOnceWith({ text: expect.stringContaining("unreadable"), tone: "error" });
  } finally {
    toast.mockRestore();
  }
});
