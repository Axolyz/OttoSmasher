// 原生播放器在 preload 里加载（ARCHITECTURE §10.1）：画面由 mpv 渲染桥的渲染线程产出，
// 这里每个动画帧取最新一帧，用 WebGL 贴到页面的 <canvas>。页面世界拿不到 Node，也拿不到文件路径。
import { join } from "node:path";

interface NativePlayer {
  command(args: string[]): number;
  setProperty(name: string, value: string): number;
  getProperty(name: string): string | null;
  observe(name: string, format: "double" | "flag" | "string" | "int64"): number;
  setSize(w: number, h: number): void;
  copyFrame(target: Uint8Array, lastSeq: number): { seq: number; width: number; height: number } | null;
  stats(): { rendered: number; renderMsAvg: number; renderMsMax: number; renderCpuMsAvg: number; renderCpuMsMax: number };
  destroy(): void;
}

interface Binding {
  Player: new (opts: { video: boolean; options?: Record<string, string> }, onEvent: (ev: MpvEvent) => void) => NativePlayer;
}

export interface MpvEvent {
  type: string;
  name?: string;
  value?: number | boolean | string | null;
  reason?: number;
  error?: string;
}

let binding: Binding | null = null;
function load(): Binding {
  if (!binding) {
    const path = join(__dirname, "..", "..", "app", "native", "mpv-bridge", "build", "Release", "mpv_bridge.node");
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    binding = require(path) as Binding;
  }
  return binding;
}

const VS = `attribute vec2 p; varying vec2 uv; void main(){ uv = vec2((p.x+1.0)*0.5, (1.0-p.y)*0.5); gl_Position = vec4(p,0.0,1.0); }`;
const FS = `precision mediump float; varying vec2 uv; uniform sampler2D tex; void main(){ gl_FragColor = vec4(texture2D(tex, uv).rgb, 1.0); }`;

/** 一个带画面的播放器：绑定到一个 canvas。 */
export class CanvasPlayer {
  private native: NativePlayer;
  private gl: WebGLRenderingContext;
  private tex: WebGLTexture;
  private buf = new Uint8Array(0);
  private seq = 0;
  private texW = 0;
  private texH = 0;
  private raf = 0;
  private ro: ResizeObserver;
  framesShown = 0;
  private drawMsTotal = 0;
  private drawMsMax = 0;
  private listeners = new Set<(ev: MpvEvent) => void>();

  constructor(private canvas: HTMLCanvasElement, options: Record<string, string>, private maxPixels = Infinity) {
    this.native = new (load().Player)({ video: true, options }, (ev) => {
      for (const l of this.listeners) l(ev);
    });
    const gl = canvas.getContext("webgl", { alpha: false, antialias: false, preserveDrawingBuffer: false });
    if (!gl) throw new Error("webgl unavailable");
    this.gl = gl;
    const prog = gl.createProgram()!;
    for (const [type, src] of [
      [gl.VERTEX_SHADER, VS],
      [gl.FRAGMENT_SHADER, FS],
    ] as const) {
      const sh = gl.createShader(type)!;
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      gl.attachShader(prog, sh);
    }
    gl.linkProgram(prog);
    gl.useProgram(prog);
    const vb = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, vb);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    this.tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    for (const [k, v] of [
      [gl.TEXTURE_MIN_FILTER, gl.LINEAR],
      [gl.TEXTURE_MAG_FILTER, gl.LINEAR],
      [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE],
      [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE],
    ] as const)
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(canvas);
    this.resize();
    const tick = () => {
      this.draw();
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  on(cb: (ev: MpvEvent) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  private resize(): void {
    const dpr = window.devicePixelRatio || 1;
    let w = Math.max(2, Math.round(this.canvas.clientWidth * dpr));
    let h = Math.max(2, Math.round(this.canvas.clientHeight * dpr));
    // 软件渲染的像素上限：超过就按比例缩小，由 WebGL 放大到画布
    if (w * h > this.maxPixels) {
      const k = Math.sqrt(this.maxPixels / (w * h));
      w = Math.round(w * k);
      h = Math.round(h * k);
    }
    this.canvas.width = w;
    this.canvas.height = h;
    this.native.setSize(w, h);
  }

  private draw(): void {
    const need = this.canvas.width * this.canvas.height * 4;
    if (this.buf.length < need) this.buf = new Uint8Array(need);
    const t0 = performance.now();
    const f = this.native.copyFrame(this.buf, this.seq);
    if (!f) return;
    this.seq = f.seq;
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.tex);
    const view = this.buf.subarray(0, f.width * f.height * 4);
    if (f.width !== this.texW || f.height !== this.texH) {
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, f.width, f.height, 0, gl.RGBA, gl.UNSIGNED_BYTE, view);
      this.texW = f.width;
      this.texH = f.height;
    } else {
      gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, f.width, f.height, gl.RGBA, gl.UNSIGNED_BYTE, view);
    }
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    this.framesShown++;
    const dt = performance.now() - t0;
    this.drawMsTotal += dt;
    if (dt > this.drawMsMax) this.drawMsMax = dt;
  }

  command(args: string[]): number {
    return this.native.command(args);
  }
  set(name: string, value: string): number {
    return this.native.setProperty(name, value);
  }
  get(name: string): string | null {
    return this.native.getProperty(name);
  }
  observe(name: string, format: "double" | "flag" | "string" | "int64"): void {
    this.native.observe(name, format);
  }
  stats() {
    return {
      ...this.native.stats(),
      framesShown: this.framesShown,
      uiMsAvg: this.framesShown ? this.drawMsTotal / this.framesShown : 0,
      uiMsMax: this.drawMsMax,
    };
  }
  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    this.native.destroy();
  }
}
