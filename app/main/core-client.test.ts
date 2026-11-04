import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { CoreClient } from "./core-client";

class FakeProc extends EventEmitter {
  stdin = Object.assign(new EventEmitter(), { write: vi.fn(), end: vi.fn() });
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  kill = vi.fn();
}
const fake = vi.hoisted(() => ({ proc: null as unknown }));
vi.mock("node:child_process", () => {
  const spawn = () => fake.proc;
  return { spawn, default: { spawn } };
});

describe("CoreClient", () => {
  it("Core 退出瞬间写入失败（EPIPE）：不抛未捕获异常，等待中的请求收到 core-exited", async () => {
    const proc = new FakeProc();
    fake.proc = proc;
    const stderr = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const client = new CoreClient({ python: "python", workspace: "w", cwd: ".", dev: false });
    client.start();
    client.status = { state: "ready" };
    const pending = client.request("core.hello");
    expect(() => proc.stdin.emit("error", Object.assign(new Error("write EPIPE"), { code: "EPIPE" }))).not.toThrow();
    proc.emit("exit", null);
    await expect(pending).resolves.toEqual({ ok: false, e: { code: "core-exited", args: {} } });
    stderr.mockRestore();
  });
});
