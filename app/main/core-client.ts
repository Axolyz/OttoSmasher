// 主进程里的 Core 客户端：启动 Python Core，按帧收发 msgpack，转发事件；Core 退出时通知界面（ARCHITECTURE §2.3）。
import { type ChildProcess, spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { decode, encode } from "@msgpack/msgpack";
import type { CoreErrorWire, CoreEvent, CoreResult, CoreStatus } from "../shared/protocol";

interface Pending {
  resolve: (r: CoreResult<unknown>) => void;
  /** 发请求的窗口（webContents.id） */
  origin?: number;
}

export interface CoreOptions {
  python: string;
  workspace: string;
  supportDir?: string;
  dev: boolean;
  cwd?: string;
}

export class CoreClient extends EventEmitter {
  private proc: ChildProcess | null = null;
  private buf = Buffer.alloc(0);
  private nextId = 1;
  private pending = new Map<number, Pending>();
  status: CoreStatus = { state: "starting" };
  private readyWaiters: Array<() => void> = [];
  private stopping = false;

  constructor(private opts: CoreOptions) {
    super();
  }

  start(): void {
    this.stopping = false;
    this.setStatus({ state: "starting" });
    const args = ["-m", "ottosmasher", "--workspace", this.opts.workspace];
    if (this.opts.supportDir) args.push("--support-dir", this.opts.supportDir);
    if (this.opts.dev) args.push("--dev");
    const proc = spawn(this.opts.python, args, { cwd: this.opts.cwd, env: { ...process.env, PYTHONUTF8: "1" }, stdio: ["pipe", "pipe", "pipe"] });
    this.proc = proc;
    this.buf = Buffer.alloc(0);
    // Core 退出的瞬间写入会 EPIPE。没有这个监听，主进程就是未捕获异常（弹错误框）；等待中的请求由下面的 exit 统一结束
    proc.stdin!.on("error", (err) => process.stderr.write(`[core] stdin: ${String(err)}\n`));
    proc.stdout!.on("data", (chunk: Buffer) => this.onData(chunk));
    proc.stderr!.on("data", (chunk: Buffer) => process.stderr.write(`[core] ${chunk.toString()}`));
    proc.on("exit", (code) => {
      this.proc = null;
      for (const p of this.pending.values()) p.resolve({ ok: false, e: { code: "core-exited", args: {} } });
      this.pending.clear();
      if (this.status.state !== "fatal") this.setStatus({ state: "exited", exitCode: code });
      if (!this.stopping) this.emit("unexpected-exit", code);
    });
  }

  private setStatus(st: CoreStatus): void {
    this.status = st;
    this.emit("status", st);
    if (st.state === "ready") {
      for (const w of this.readyWaiters.splice(0)) w();
    }
  }

  whenReady(): Promise<void> {
    if (this.status.state === "ready") return Promise.resolve();
    return new Promise((res) => this.readyWaiters.push(res));
  }

  private onData(chunk: Buffer): void {
    this.buf = Buffer.concat([this.buf, chunk]);
    while (this.buf.length >= 4) {
      const len = this.buf.readUInt32BE(0);
      if (this.buf.length < 4 + len) break;
      const body = this.buf.subarray(4, 4 + len);
      this.buf = this.buf.subarray(4 + len);
      this.onMessage(decode(body) as Record<string, unknown>);
    }
  }

  private onMessage(msg: Record<string, unknown>): void {
    if (msg.t === "res") {
      const p = this.pending.get(msg.id as number);
      if (!p) return;
      this.pending.delete(msg.id as number);
      p.resolve(msg.ok ? { ok: true, r: msg.r } : { ok: false, e: msg.e as CoreErrorWire });
      return;
    }
    if (msg.t === "evt") {
      const ev: CoreEvent = { e: msg.e as string, d: msg.d };
      // 由某个请求引起的资料变化：记下发请求的窗口（只有那个窗口算“自己的操作”，P8）
      if (typeof msg.req === "number") ev.origin = this.pending.get(msg.req)?.origin;
      if (ev.e === "core.ready") this.setStatus({ state: "ready" });
      if (ev.e === "core.fatal") this.setStatus({ state: "fatal", error: ev.d as CoreErrorWire });
      this.emit("event", ev);
    }
  }

  request<T = unknown>(method: string, params: Record<string, unknown> = {}, origin?: number): Promise<CoreResult<T>> {
    const proc = this.proc;
    if (!proc || this.status.state !== "ready") {
      return Promise.resolve({ ok: false, e: { code: "core-not-ready", args: { state: this.status.state } } });
    }
    const id = this.nextId++;
    const body = Buffer.from(encode({ t: "req", id, m: method, p: params }));
    const head = Buffer.alloc(4);
    head.writeUInt32BE(body.length, 0);
    return new Promise((resolve) => {
      this.pending.set(id, { resolve: resolve as Pending["resolve"], origin });
      proc.stdin!.write(Buffer.concat([head, body]));
    });
  }

  /** 正常退出：先让 Core 取消任务并退出；超时则结束进程。 */
  async stop(cancelJobs: boolean, timeoutMs = 8000): Promise<void> {
    this.stopping = true;
    const proc = this.proc;
    if (!proc) return;
    const exited = new Promise<void>((res) => proc.once("exit", () => res()));
    if (this.status.state === "ready") void this.request("app.quit", { cancel_jobs: cancelJobs });
    else proc.stdin?.end();
    const timer = setTimeout(() => proc.kill("SIGKILL"), timeoutMs);
    await exited;
    clearTimeout(timer);
  }
}
