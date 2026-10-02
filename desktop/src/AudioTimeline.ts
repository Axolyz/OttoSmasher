import { attachNativeMedia } from "./NativeMedia";
import React from "react";
import { snapIntervals } from "./TimelineSelection";
import { createRoot, Root } from "react-dom/client";
import { Button, ConfigProvider, theme } from "antd";
import WaveSurfer from "wavesurfer.js";
import Regions from "wavesurfer.js/dist/plugins/regions.esm.js";
import Timeline from "wavesurfer.js/dist/plugins/timeline.esm.js";
import Hover from "wavesurfer.js/dist/plugins/hover.esm.js";
import Zoom from "wavesurfer.js/dist/plugins/zoom.esm.js";
import Minimap from "wavesurfer.js/dist/plugins/minimap.esm.js";
import Spectrogram from "wavesurfer.js/dist/plugins/spectrogram.esm.js";

export const clockLabel = (t: number) =>
  `${Math.floor(t / 60)}:${(t % 60).toFixed(3).padStart(6, "0")}`;
export const isAnnotation = (id: string) => id.startsWith("annotation:");

export const noteName = (m: number) =>
  ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"][
    ((m % 12) + 12) % 12
  ] +
  (Math.floor(m / 12) - 1);
/** Shared source-clock waveform. F0 is drawn only where measured, never interpolated across gaps. */
export function audioTimeline(options: any) {
  const {
    origin = 0,
    visualizationKey,
    peakLevels,
    spectrumLabel = "查看采样频谱",
    onSelectionChange,
    ...base
  } = options;
  const height = base.height || 148;
  const container = base.container as HTMLElement;
  container.style.position = "relative";
  container.classList.add("audio-timeline");
  // WaveSurfer supplies visualization and editing; libmpv owns desktop decoding/clock.
  const ownsMedia = !!window.ottoDesktop?.player && !base.media;
  if (ownsMedia) base.media = document.createElement("audio");
  const nativeMedia = base.media ? attachNativeMedia(base.media) : undefined;
  const regions = Regions.create();
  const w = WaveSurfer.create({
    ...base,
    height,
    waveColor: "#416fac",
    progressColor: "#6e99d6",
    cursorColor: "#f7faff",
    cursorWidth: 2,
    barWidth: 2,
    barGap: 1,
    autoCenter: false,
    dragToSeek: false,
    interact: false,
    plugins: [
      regions,
      Hover.create({
        lineColor: "#d6e6fa",
        labelBackground: "#152233",
        labelColor: "#fff",
        formatTimeCallback: (t) => clockLabel(t + origin),
      }),
      Timeline.create({
        height: 22,
        style: { fontSize: "10px", color: "#b9c9dd" },
        formatTimeCallback: (t: number) => clockLabel(t + origin),
      }),
    ],
  });
  let peakLevel = -1;
  const updatePeaks = () => {
    if (!peakLevels?.length || !w.getDuration()) return;
    const needed =
      Math.max(
        container.clientWidth,
        w.getDuration() * (w.options.minPxPerSec || 0),
      ) / 3;
    let i = peakLevels.findIndex((level: number[]) => level.length >= needed);
    if (i < 0) i = peakLevels.length - 1;
    if (i !== peakLevel) {
      peakLevel = i;
      w.setOptions({ peaks: [peakLevels[i]], duration: w.getDuration() });
    }
  };
  w.on("ready", updatePeaks);
  w.on("zoom", updatePeaks);
  if (ownsMedia) w.on("destroy", () => nativeMedia?.destroy());
  const pauseHidden = () => {
    if (!container.getClientRects().length) w.pause();
  };
  const pauseAll = () => w.pause();
  window.addEventListener("otto:pause-media", pauseAll);
  w.on("play", pauseHidden);
  w.on("destroy", () =>
    window.removeEventListener("otto:pause-media", pauseAll),
  );
  (w as any).ottoRegions = regions;
  let frames: any = null;
  let pitchMidi: (number | null)[] = [],
    pitchBounds: [number, number] = [0, 0];
  const canvas = document.createElement("canvas");
  canvas.className = "pitch-overlay";
  Object.assign(canvas.style, {
    position: "absolute",
    top: "0px",
    left: "0",
    pointerEvents: "none",
    zIndex: "4",
  });
  container.appendChild(canvas);
  const pitchTip = document.createElement('span');
  Object.assign(pitchTip.style,{position:'absolute',pointerEvents:'none',zIndex:'8',background:'#141d2e',padding:'3px 6px',borderRadius:'4px',display:'none'});
  container.appendChild(pitchTip);
  const pitchHover=(event:MouseEvent)=>{
    if(!frames?.times?.length)return;
    const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,yy=event.clientY-rect.top;
    if(yy<0||yy>height){pitchTip.style.display='none';return;}
    const pps=Math.max(container.clientWidth/(w.getDuration()||base.duration),w.options.minPxPerSec||0);
    const time=(x+w.getScroll())/pps;
    let lo=0,hi=frames.times.length-1;
    while(lo<hi){const mid=(lo+hi)>>>1;if(frames.times[mid]<time)lo=mid+1;else hi=mid;}
    const m=pitchMidi[lo];if(m==null){pitchTip.style.display='none';return;}
    const cents=Math.round((m-Math.round(m))*100);
    pitchTip.textContent=`${noteName(Math.round(m))} ${cents>=0?'+':''}${cents} 音分 · ${frames.times[lo].toFixed(2)}s`;
    Object.assign(pitchTip.style,{display:'block',left:Math.min(Math.max(40,x+8),Math.max(40,container.clientWidth-190))+'px',top:'4px'});
  };
  const pitchLeave=()=>{pitchTip.style.display='none'};
  container.addEventListener('mousemove',pitchHover);container.addEventListener('mouseleave',pitchLeave);
  w.on('destroy',()=>{container.removeEventListener('mousemove',pitchHover);container.removeEventListener('mouseleave',pitchLeave);pitchTip.remove();canvas.remove()});
  const redraw = () => {
    const width = container.clientWidth,
      scale = devicePixelRatio || 1;
    canvas.width = width * scale;
    canvas.height = height * scale;
    canvas.style.top =
      w.getWrapper().getBoundingClientRect().top -
      container.getBoundingClientRect().top +
      "px";
    canvas.style.width = width + "px";
    canvas.style.height = height + "px";
    const c = canvas.getContext("2d")!;
    c.scale(scale, scale);
    if (!frames?.times || !frames?.f0_hz) return;
    const midi = pitchMidi;
    if (!midi.length || !Number.isFinite(pitchBounds[0])) return;
    let lo = Math.floor(pitchBounds[0]) - 2,
      hi = Math.ceil(pitchBounds[1]) + 2;
    if (hi - lo < 12) {
      lo -= Math.floor((12 - hi + lo) / 2);
      hi = lo + 12;
    }
    const y = (m: number) =>
      height - 8 - ((m - lo) / (hi - lo)) * (height - 16);
    c.font = "11px system-ui";
    let lastLabel = height + 20;
    for (let m = lo; m <= hi; m++) {
      c.strokeStyle = m % 12 === 0 ? "#bad6e066" : "#bad6e026";
      c.beginPath();
      c.moveTo(0, y(m));
      c.lineTo(width, y(m));
      c.stroke();
      c.fillStyle = "#dbedefb0";
      if (lastLabel - y(m) >= 14) {
        c.fillStyle = "#141d2eee";
        c.fillRect(0,y(m)-14,36,14);
        c.fillStyle = "#e7f1ff";
        c.fillText(noteName(m), 3, y(m) - 2);
        lastLabel = y(m);
      }
    }
    const duration = w.getDuration() || base.duration;
    const pps = Math.max(width / duration, w.options.minPxPerSec || 0);
    c.lineWidth = 1.8;
    c.strokeStyle = "#ffdb74";
    c.beginPath();
    let active = false;
    const left = w.getScroll() / pps,
      right = (w.getScroll() + width) / pps;
    let low = 0,
      high = frames.times.length;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (frames.times[mid] < left) low = mid + 1;
      else high = mid;
    }
    for (
      let i = Math.max(0, low - 1);
      i < midi.length && frames.times[i] <= right;
      i++
    ) {
      const m = midi[i],
        x = frames.times[i] * pps - w.getScroll();
      if (m === null) {
        active = false;
        continue;
      }
      if (active && frames.times[i] - frames.times[i - 1] < 0.08)
        c.lineTo(x, y(m));
      else c.moveTo(x, y(m));
      active = true;
    }
    c.stroke();
  };
  (w as any).ottoSetFrames = (f: any) => {
    if (frames !== f) {
      pitchBounds = [Infinity, -Infinity];
      pitchMidi = (f?.f0_hz || []).map((v: number, i: number) => {
        if (!(v > 0) || !(f.voiced?.[i] ?? true)) return null;
        const m = 69 + 12 * Math.log2(v / 440);
        pitchBounds[0] = Math.min(pitchBounds[0], m);
        pitchBounds[1] = Math.max(pitchBounds[1], m);
        return m;
      });
    }
    frames = f;
    redraw();
  };
  const controls = document.createElement("div");
  controls.className = "timeline-controls";
  container.appendChild(controls);
  const controlRoots: Root[] = [];
  const button = (text: string, action: () => void, fixedWidth?: number) => {
    const host = document.createElement("span");
    controls.appendChild(host);
    const root = createRoot(host);
    controlRoots.push(root);
    const render = (label: string) =>
      root.render(
        React.createElement(
          ConfigProvider,
          {
            theme: {
              algorithm: [theme.darkAlgorithm, theme.compactAlgorithm],
              token: { colorPrimary: "#79b8ff" },
            },
          },
          React.createElement(
            Button,
            { size: "small", onClick: action, style: fixedWidth ? {width:fixedWidth} : undefined },
            label,
          ),
        ),
      );
    render(text);
    return {
      click: action,
      get textContent() {
        return text;
      },
      set textContent(value: string) {
        text = value;
        render(text);
      },
    };
  };
  const status = document.createElement("span");
  status.className = "timeline-status";
  const play = button("播放 / 暂停", () => {
    stopAt = null;
    nativeMedia?.clearRange();
    void w.playPause().catch((e) => (status.textContent = String(e)));
  }, 100);
  const selection = () => regions.getRegions().find((r) => !isAnnotation(r.id));
  button("播放选区", () => {
    const r = selection();
    if (r) {
      if (nativeMedia) {
        stopAt = null;
        void nativeMedia
          .playRange(r.start, r.end, loop)
          .catch((e) => (status.textContent = String(e)));
      } else {
        w.setTime(r.start);
        stopAt = r.end;
        void w.play().catch((e) => (status.textContent = String(e)));
      }
    }
  });
  let stopAt: number | null = null,
    loop = false;
  const loopButton = button("循环：关", () => {
    loop = !loop;
    loopButton.textContent = `循环：${loop ? "开" : "关"}`;
    const r = selection();
    if (r && w.isPlaying() && nativeMedia)
      void nativeMedia.playRange(r.start, r.end, loop);
  });
  const fit = () => {
    const d = w.getDuration();
    if (d) w.zoom(container.clientWidth / d);
  };
  button("适合窗口", fit);
  button("放大选区", () => {
    const r = selection();
    if (r && r.end > r.start) {
      w.zoom(container.clientWidth / (r.end - r.start));
      w.setScrollTime(r.start);
    }
  });
  let zoomPlugin: Zoom | undefined;
  const configureZoom = () => {
    let saved: any = {};
    try {
      saved = JSON.parse(localStorage.getItem("otto.ui.settings") || "{}");
    } catch {}
    zoomPlugin?.destroy();
    zoomPlugin = w.registerPlugin(
      Zoom.create({
        exponentialZooming: saved.zoom_curve !== "linear",
        iterations: 30,
        maxZoom: 4000,
        deltaThreshold: saved.zoom_threshold ?? 5,
        scale: 0.5,
      }),
    );
  };
  window.addEventListener("otto:settings", configureZoom);
  w.on("destroy", () =>
    window.removeEventListener("otto:settings", configureZoom),
  );
  configureZoom();
  let minimap: Minimap | undefined;
  const overview = button("总览", () => {
    if (minimap) {
      minimap.destroy();
      minimap = undefined;
    } else {
      minimap = w.registerPlugin(
        Minimap.create({
          height: 30,
          waveColor: "#47658a",
          progressColor: "#7eade0",
          overlayColor: "#87b7ff35",
          insertPosition: "beforebegin",
        }),
      );
      minimap.on("ready", redraw);
    }
    redraw();
  });
  let detailWave: WaveSurfer | undefined,
    requestVersion = 0,
    dead = false,
    detailStart = 0;
  const detailHost = document.createElement("div");
  detailHost.className = "spectrum-detail";
  let spectrum: Spectrogram | undefined, spectrumOwner: WaveSurfer | undefined;
  const spectralScale = document.createElement("select");
  spectralScale.setAttribute("aria-label", "频谱频率刻度");
  spectralScale.innerHTML =
    '<option value="logarithmic">频谱：对数频率</option><option value="linear">频谱：线性频率</option><option value="mel">频谱：Mel</option>';
  let spectrumData: any;
  const mountSpectrum = () => {
    spectrum?.destroy();
    if (!spectrumOwner || !spectrumData) return;
    spectrum = spectrumOwner.registerPlugin(
      Spectrogram.create({
        height: 160,
        labels: true,
        colorMap: "roseus",
        sampleRate: spectrumData.sample_rate,
        fftSamples: spectrumData.fft_samples,
        frequenciesDataUrl: spectrumData.url,
        frequencyMin: spectralScale.value === "logarithmic" ? 30 : 0,
        frequencyMax: 20000,
        scale: spectralScale.value as "linear" | "logarithmic" | "mel",
      }),
    );
    spectrum.on("error", (e) => {
      status.textContent = String(e);
    });
    spectrum.on("click", (x) =>
      w.setTime(detailStart + x * (spectrumData.end - spectrumData.start)),
    );
  };
  spectralScale.onchange = mountSpectrum;
  if (visualizationKey) {
    const showSpectrum = async () => {
      const n = ++requestVersion,
        duration = w.getDuration();
      const pps = Math.max(
        container.clientWidth / duration,
        w.options.minPxPerSec || 0,
      );
      let start = Math.min(w.getScroll() / pps, Math.max(0, duration - 30));
      let end = Math.min(duration, start + 30);
      if (duration <= 30) {
        start = 0;
        end = duration;
      }
      if (!(end > start)) return;
      status.textContent = "加载频谱…";
      try {
        const response = await fetch(
          `/api/helper/visualizations/${visualizationKey}/detail?start=${start}&end=${end}`,
        );
        const data = await response.json();
        if (!response.ok) throw Error(data.detail || "频谱读取失败");
        if (dead || n !== requestVersion) return;
        spectrum?.destroy();
        spectrum = undefined;
        detailWave?.destroy();
        detailWave = undefined;
        detailHost.replaceChildren();
        spectrumData = data;
        detailStart = start;
        const label = document.createElement("div");
        label.className = "muted";
        label.textContent = `${duration <= 30 ? "频谱与主波形同步" : "频谱细看"} ${clockLabel(start + origin)}–${clockLabel(end + origin)} · 固定 −90–0 dB · 点击定位主播放器`;
        const close = document.createElement("button");
        close.textContent = "收起";
        close.onclick = () => {
          ++requestVersion;
          spectrum?.destroy();
          detailWave?.destroy();
          detailWave = undefined;
          spectrum = undefined;
          spectrumOwner = undefined;
          detailHost.replaceChildren();
        };
        label.appendChild(close);
        detailHost.append(label, spectralScale);
        const host = document.createElement("div");
        detailHost.appendChild(host);
        container.appendChild(detailHost);
        const buffer = w.getDecodedData(),
          total = w.getDuration();
        const source = buffer?.getChannelData(0) || new Float32Array([0, 0]);
        const peaks = source.slice(
          Math.floor((start / total) * source.length),
          Math.max(1, Math.ceil((end / total) * source.length)),
        );
        if (duration > 30) {
          detailWave = WaveSurfer.create({
            container: host,
            peaks: [peaks],
            duration: end - start,
            height: 35,
            waveColor: "#567db4",
            progressColor: "#8fbdff",
            cursorColor: "#ffb52e",
            plugins: [
              Timeline.create({
                height: 18,
                formatTimeCallback: (t) => clockLabel(t + start + origin),
              }),
              Hover.create({
                formatTimeCallback: (t) => clockLabel(t + start + origin),
              }),
            ],
          });
          detailWave.on("interaction", (t) => w.setTime(start + t));
          spectrumOwner = detailWave;
        } else spectrumOwner = w;
        mountSpectrum();
        status.textContent = "";
      } catch (e) {
        if (!dead && n === requestVersion) status.textContent = String(e);
      }
    };
    button(spectrumLabel, showSpectrum);
    let pending: ReturnType<typeof setTimeout>;
    w.on("scroll", () => {
      if (spectrum && w.getDuration() > 30) {
        clearTimeout(pending);
        pending = setTimeout(showSpectrum, 160);
      }
    });
    w.on("destroy", () => clearTimeout(pending));
  }
  const position = document.createElement("span");
  position.className = "timeline-position";
  position.textContent = clockLabel(origin);
  controls.append(position, status);

  controls.title = "滚轮缩放；横向滚动平移；拖动波形选择范围";
  w.on("play", () => {
    play.textContent = "暂停";
  });
  w.on("pause", () => {
    play.textContent = "播放";
  });
  w.on("timeupdate", (t) => {
    position.textContent = clockLabel(w.getMediaElement().currentTime + origin);
    const r = selection();
    if (!nativeMedia && loop && r && t >= r.end && w.isPlaying())
      w.setTime(r.start);
    else if (stopAt !== null && t >= stopAt) {
      w.pause();
      w.setTime(stopAt);
      stopAt = null;
    }
    if (detailWave)
      detailWave.setTime(
        Math.max(0, Math.min(detailWave.getDuration(), t - detailStart)),
      );
  });
  w.on("ready", () => {
    if (w.getDuration() > 30 && !minimap) overview.click();
  });
  type Annotation = {
    id: string;
    start: number;
    end?: number;
    effective_start?:number;
    effective_end?:number;
    label: string;
    color?: string;
    layer?: string;
  };
  let interiorChanged: ((a:number,b:number)=>void)|undefined;
  let interiorBounds=[0,0];
  (w as any).ottoSetInterior = (range:number[]|null,bounds?:number[],changed?:(a:number,b:number)=>void,transition?:number[]) => {
    if(dead)return;
    regions.getRegions().find(r=>r.id==='annotation:interior')?.remove();
    interiorChanged=changed;
    if(range&&bounds){interiorBounds=bounds;const region=regions.addRegion({id:'annotation:interior',start:range[0],end:range[1],color:'#f2b84b33',content:'内部拉平',resize:true,drag:false});if(region.element&&transition){const span=range[1]-range[0],a=Math.min(50,100*transition[0]/span),b=Math.max(50,100-100*transition[1]/span);region.element.style.background=`linear-gradient(to right,transparent,#f2b84b55 ${a}%,#f2b84b55 ${b}%,transparent)`;region.element.title='两侧渐变为过渡范围，中间为定高平台';}}
  };
  let editableAnnotationIds: Set<string>|undefined;
  let annotationEditor: ((id:string,start:number,end:number)=>void)|null = null;
  let annotations: Annotation[] = [];
  let extraAnnotations: Annotation[] = [];
  let descendants: any[] = [];
  let descendantSelect: (id:string)=>void = () => {};
  const descendantLane = document.createElement("div");
  descendantLane.className = "timeline-descendant-lane";
  Object.assign(descendantLane.style,{height:"16px",position:"relative",overflow:"hidden",display:"none"});
  container.prepend(descendantLane);
  const layerVisible: Record<string,boolean> = {phones:true,subtitles:true,tags:true};
  const markerLane = document.createElement("div");
  markerLane.className = "timeline-marker-lane";
  Object.assign(markerLane.style, {
    height: "22px",
    position: "relative",
    overflow: "hidden",
  });
  container.prepend(markerLane);
  let closeDescendantMenu = () => {};
  const drawAnnotations = () => {
    closeDescendantMenu();
    if (dead) return;
    const duration = w.getDuration();
    if (!duration) return;
    const pps = Math.max(
      container.clientWidth / duration,
      w.options.minPxPerSec || 0,
    );
    const left = w.getScroll() / pps,
      right = left + container.clientWidth / pps;
    regions
      .getRegions()
      .filter((r) => isAnnotation(r.id) && r.id !== "annotation:interior")
      .forEach((r) => r.remove());
    markerLane.replaceChildren();
    descendantLane.replaceChildren();
    descendantLane.style.display = descendants.length ? "block" : "none";
    // Draw wider ranges behind shorter ones so an entire-source sample cannot
    // cover every sentence; overlap choices are local to the clicked time.
    for (const item of [...descendants].sort((a,b)=>(b.end-b.start)-(a.end-a.start))) {
      if (item.end <= left || item.start >= right) continue;
      const bar = document.createElement("button");
      bar.title=item.title; bar.setAttribute("aria-label",item.title);
      Object.assign(bar.style,{position:"absolute",left:`${Math.max(0,item.start*pps-w.getScroll())}px`,
        width:`${Math.max(2,(Math.min(item.end,right)-Math.max(item.start,left))*pps)}px`,height:"10px",top:"3px",
        padding:"0",border:"1px solid #335f56",borderRadius:"2px",background:"#67bba6",cursor:"pointer"});
      bar.onclick=(event)=>{
        closeDescendantMenu();
        const at=event.detail===0 ? (item.start+item.end)/2 : (event.clientX-descendantLane.getBoundingClientRect().left+w.getScroll())/pps;
        const overlap=descendants.filter(x=>x.start<=at && x.end>at).sort((a,b)=>(a.end-a.start)-(b.end-b.start));
        if(!overlap.length)overlap.push(item);
        if(overlap.length===1){descendantSelect(overlap[0].id);return;}
        const menu=document.createElement("div");
        menu.className="otto-descendant-menu";
        menu.setAttribute("role","menu");
        menu.setAttribute("aria-label","选择重叠的派生采样");
        const rect=bar.getBoundingClientRect();
        Object.assign(menu.style,{position:"fixed",zIndex:"2000",left:`${Math.max(8,Math.min(event.detail?event.clientX:rect.left,window.innerWidth-328))}px`,top:`${Math.max(8,Math.min(rect.bottom+4,window.innerHeight-248))}px`,width:"320px",maxHeight:"240px",overflowY:"auto",padding:"4px",background:"#202c3c",border:"1px solid #52657e",borderRadius:"6px",boxShadow:"0 4px 16px #0008"});
        const outside=(e:PointerEvent)=>{if(!menu.contains(e.target as Node))closeDescendantMenu()};
        const key=(e:KeyboardEvent)=>{
          if(e.key==="Escape"){e.preventDefault();closeDescendantMenu();bar.focus();}
          if(e.key==="ArrowDown"||e.key==="ArrowUp"){
            e.preventDefault();const buttons=Array.from(menu.querySelectorAll("button"));
            const index=buttons.indexOf(document.activeElement as HTMLButtonElement);
            buttons[(index+(e.key==="ArrowDown"?1:buttons.length-1))%buttons.length]?.focus();
          }
        };
        closeDescendantMenu=()=>{menu.remove();document.removeEventListener("pointerdown",outside);document.removeEventListener("keydown",key);closeDescendantMenu=()=>{}};
        overlap.forEach(x=>{
          const choice=document.createElement("button");choice.textContent=x.title;choice.title=x.title;choice.setAttribute("role","menuitem");
          Object.assign(choice.style,{display:"block",width:"100%",padding:"8px",border:"0",borderRadius:"4px",background:"transparent",color:"#e1e8f0",textAlign:"left",cursor:"pointer"});
          choice.onfocus=()=>choice.style.background="#354760";choice.onblur=()=>choice.style.background="transparent";
          choice.onmouseenter=()=>choice.focus();
          choice.onclick=()=>{closeDescendantMenu();descendantSelect(x.id)};menu.append(choice);
        });
        document.body.append(menu);document.addEventListener("pointerdown",outside);document.addEventListener("keydown",key);
        menu.querySelector("button")?.focus();
      };
      descendantLane.append(bar);
    }
    for (const item of [...annotations,...extraAnnotations]) {
      const layer=item.layer || (item.id.startsWith("phone-")?"phones":item.id.startsWith("subtitle-")?"subtitles":"tags");
      if (layerVisible[layer]===false) continue;
      if (
        (item.end ?? item.start) < left ||
        item.start > right ||
        (item.end ?? item.start) < 0 ||
        item.start > duration
      )
        continue;
      const title = `${item.label} · ${clockLabel(item.start + origin)}${item.end == null ? "" : "–" + clockLabel(item.end + origin)}`;
      if (item.end == null) {
        const mark = document.createElement("span");
        mark.textContent =
          "◆ " + (annotations.filter((x) => x.end == null).indexOf(item) + 1);
        mark.title = title;
        Object.assign(mark.style, {
          position: "absolute",
          left: `${item.start * pps - w.getScroll()}px`,
          color: item.color || "#b6c9e4",
          fontSize: "10px",
          whiteSpace: "nowrap",
        });
        markerLane.append(mark);
      } else {
        const content = document.createElement("span");
        content.textContent = pps < 35 && layer === "phones" ? "" : item.label;
        content.title = title;
        Object.assign(content.style,{fontSize:"11px",lineHeight:"14px",whiteSpace:"nowrap",position:"absolute",top:layer==="phones"?"0":layer==="subtitles"?"14px":"28px"});
        const r = regions.addRegion({
          id: "annotation:" + item.id,
          start: Math.max(0,item.start),
          end: Math.min(item.end, duration),
          content,
          color: item.color || "#8ab9f514",
          drag: false,
          resize: !!annotationEditor && (!editableAnnotationIds || editableAnnotationIds.has(item.id)),
          resizeStart: item.start >= 0,
          resizeEnd: item.end <= duration,
        });
        if (r.element) r.element.style.pointerEvents = annotationEditor ? "auto" : "none";
      }
    }
  };
  (w as any).ottoSetAnnotationEditor = (handler: typeof annotationEditor, ids?:Set<string>) => {annotationEditor=handler;editableAnnotationIds=ids;drawAnnotations()};
  (w as any).ottoAnnotations = () => [...annotations,...extraAnnotations];
  (w as any).ottoPatchAnnotation = (id:string,start:number,end:number) => {
    for (const item of [...annotations,...extraAnnotations]) if(item.id===id) Object.assign(item,{start,end});
    drawAnnotations();
  };
  (w as any).ottoSetAnnotations = (items: Annotation[]) => {
    annotations = items;
    drawAnnotations();
  };
  (w as any).ottoSetLayers = (items: Annotation[], visible: Record<string,boolean>) => {
    extraAnnotations=items;Object.assign(layerVisible,visible);drawAnnotations();
  };
  (w as any).ottoSetDescendants = (items:any[], onSelect:(id:string)=>void) => {
    descendants=items;descendantSelect=onSelect;drawAnnotations();
  };
  (w as any).ottoViewport = () => {
    const pps=Math.max(container.clientWidth/(w.getDuration()||1),w.options.minPxPerSec||0);
    return [w.getScroll()/pps, Math.min(w.getDuration(),(w.getScroll()+container.clientWidth)/pps)];
  };
  const select = (start: number, end: number) => {
    if (!(end > start)) return;
    const current = selection();
    if (current) current.setOptions({ start, end, drag: false });
    else
      regions.addRegion({
        start,
        end,
        id: "selection",
        color: "#5f9dec30",
        drag: false,
        resize: true,
      });
    onSelectionChange?.([start, end]);
  };
  const selectable = () =>
    [...annotations,...extraAnnotations].filter(
      (r): r is Annotation & { end: number } =>
        r.end != null &&
        (r.id.startsWith("phone-") || r.id.startsWith("subtitle-")),
    ).map(r=>({...r,start:r.effective_start??r.start,end:r.effective_end??r.end}));
  const wrapper = w.getWrapper();
  let gesture: {
    x: number;
    time: number;
    shift: boolean;
    pointer: number;
    moved: boolean;
  } | null = null;
  const at = (e: PointerEvent) => {
    const rect = wrapper.getBoundingClientRect();
    return Math.max(
      0,
      Math.min(
        w.getDuration(),
        ((e.clientX - rect.left) / rect.width) * w.getDuration(),
      ),
    );
  };
  const down = (e: PointerEvent) => {
    if (
      e.button !== 0 ||
      e
        .composedPath()
        .some(
          (x) =>
            x instanceof HTMLElement &&
            x.getAttribute("part")?.includes("region-handle"),
        )
    )
      return;
    e.preventDefault();
    e.stopImmediatePropagation();
    gesture = {
      x: e.clientX,
      time: at(e),
      shift: e.shiftKey,
      pointer: e.pointerId,
      moved: false,
    };
    wrapper.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent) => {
    if (!gesture || gesture.pointer !== e.pointerId) return;
    if (Math.abs(e.clientX - gesture.x) > 3) gesture.moved = true;
    if (!gesture.moved) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const bounds = gesture.shift
      ? snapIntervals(gesture.time, at(e), selectable())
      : {
          start: Math.min(gesture.time, at(e)),
          end: Math.max(gesture.time, at(e)),
        };
    select(bounds.start, bounds.end);
  };
  const up = (e: PointerEvent) => {
    if (!gesture || gesture.pointer !== e.pointerId) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (!gesture.moved) {
      const t = at(e);
      const hit = gesture.shift
        ? selectable().find((r) => r.start <= t && t < r.end)
        : undefined;
      if (hit) select(hit.start, hit.end);
      else {
        stopAt = null;
        w.setTime(t);
      }
    }
    gesture = null;
    if (wrapper.hasPointerCapture(e.pointerId))
      wrapper.releasePointerCapture(e.pointerId);
  };
  wrapper.addEventListener("pointerdown", down, true);
  wrapper.addEventListener("pointermove", move, true);
  wrapper.addEventListener("pointerup", up, true);
  wrapper.addEventListener("pointercancel", up, true);
  regions.on("region-updated", (r) => {
    if(r.id === "annotation:interior"){interiorChanged?.(Math.max(interiorBounds[0],r.start),Math.min(interiorBounds[1],r.end));return;}
    if (isAnnotation(r.id)) {
      const id=r.id.slice("annotation:".length);
      const item=[...annotations,...extraAnnotations].find(a=>a.id===id);
      // A clipped range edge is not an editable annotation boundary.
      if(item){if(item.start>=0)item.start=r.start;if(item.end!<=w.getDuration())item.end=r.end;}
      annotationEditor?.(id,item?.start??r.start,item?.end??r.end);
    }
    else onSelectionChange?.([r.start, r.end]);
  });
  regions.on("region-created", (r) => {
    if (isAnnotation(r.id)) return;
    r.setOptions({ drag: false });
    regions
      .getRegions()
      .filter((x) => x !== r && !isAnnotation(x.id))
      .forEach((x) => x.remove());
    onSelectionChange?.([r.start, r.end]);
  });
  w.on("scroll", drawAnnotations);
  w.on("zoom", drawAnnotations);
  w.on("ready", drawAnnotations);
  w.on("scroll", redraw);
  w.on("zoom", redraw);
  w.on("ready", redraw);
  const ro = new ResizeObserver(()=>{redraw();drawAnnotations()});
  ro.observe(container);
  w.on("destroy", () => {
    markerLane.remove();
    closeDescendantMenu();
    descendantLane.remove();
    ro.disconnect();
    dead = true;
    ++requestVersion;
    wrapper.removeEventListener("pointerdown", down, true);
    wrapper.removeEventListener("pointermove", move, true);
    wrapper.removeEventListener("pointerup", up, true);
    wrapper.removeEventListener("pointercancel", up, true);
    detailWave?.destroy();
    detailHost.remove();
    queueMicrotask(() => controlRoots.forEach((root) => root.unmount()));
    controls.remove();
    canvas.remove();
  });
  return w;
}
