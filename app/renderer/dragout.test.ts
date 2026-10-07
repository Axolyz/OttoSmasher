import { describe, expect, it, vi } from "vitest";
import { DragOut } from "./dragout";

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}

const press = { button: 0, altKey: true, clientX: 100, clientY: 100 };

describe("拖出手势（R21.8）", () => {
  it("只有左键 + ⌥ 才接管", () => {
    const d = new DragOut();
    const deps = { generate: vi.fn(), startDrag: vi.fn() };
    expect(d.press({ ...press, altKey: false }, deps)).toBe(false);
    expect(d.press({ ...press, button: 2 }, deps)).toBe(false);
    expect(d.press(press, deps)).toBe(true);
  });

  it("越过 4 px 才生成，且只生成一次；生成完仍按住 → 系统拖拽", async () => {
    const d = new DragOut();
    const job = deferred<string[]>();
    const deps = { generate: vi.fn(() => job.promise), startDrag: vi.fn(), onPhase: vi.fn() };
    d.press(press, deps);
    d.move({ clientX: 103, clientY: 102 }); // √13 ≈ 3.6 px
    expect(deps.generate).not.toHaveBeenCalled();
    d.move({ clientX: 105, clientY: 100 });
    d.move({ clientX: 120, clientY: 100 });
    expect(deps.generate).toHaveBeenCalledTimes(1);
    expect(deps.onPhase).toHaveBeenCalledWith("generating", undefined);
    job.resolve(["/a.wav"]);
    await job.promise;
    await Promise.resolve();
    expect(deps.startDrag).toHaveBeenCalledWith(["/a.wav"]);
    expect(d.phase).toBe("idle");
  });

  it.each(["Esc", "松手", "失焦"])("生成期间%s → 放弃，之后完成也不发起拖拽", async () => {
    const d = new DragOut();
    const job = deferred<string[]>();
    const deps = { generate: vi.fn(() => job.promise), startDrag: vi.fn(), onPhase: vi.fn() };
    d.press(press, deps);
    d.move({ clientX: 120, clientY: 100 });
    d.cancel();
    expect(deps.onPhase).toHaveBeenLastCalledWith("cancelled", undefined);
    job.resolve(["/a.wav"]);
    await job.promise;
    await Promise.resolve();
    expect(deps.startDrag).not.toHaveBeenCalled();
  });

  it("没越过阈值就松手：什么都不生成", () => {
    const d = new DragOut();
    const deps = { generate: vi.fn(), startDrag: vi.fn() };
    d.press(press, deps);
    d.cancel();
    d.move({ clientX: 200, clientY: 200 });
    expect(deps.generate).not.toHaveBeenCalled();
  });

  it("生成失败要通知（不吞掉）", async () => {
    const d = new DragOut();
    const job = deferred<string[]>();
    const onPhase = vi.fn();
    d.press(press, { generate: () => job.promise, startDrag: vi.fn(), onPhase });
    d.move({ clientX: 120, clientY: 100 });
    job.reject(new Error("boom"));
    await job.promise.catch(() => {});
    await Promise.resolve();
    expect(onPhase).toHaveBeenLastCalledWith("failed", { error: expect.any(Error) });
  });

  it("旧的一次放弃后立刻开始新的一次：旧结果不影响新的", async () => {
    const d = new DragOut();
    const first = deferred<string[]>();
    const second = deferred<string[]>();
    const a = { generate: vi.fn(() => first.promise), startDrag: vi.fn() };
    const b = { generate: vi.fn(() => second.promise), startDrag: vi.fn() };
    d.press(press, a);
    d.move({ clientX: 120, clientY: 100 });
    d.cancel();
    d.press(press, b);
    d.move({ clientX: 120, clientY: 100 });
    first.resolve(["/old.wav"]);
    second.resolve(["/new.wav"]);
    await Promise.all([first.promise, second.promise]);
    await Promise.resolve();
    expect(a.startDrag).not.toHaveBeenCalled();
    expect(b.startDrag).toHaveBeenCalledWith(["/new.wav"]);
  });
});
