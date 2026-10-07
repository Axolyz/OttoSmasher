// 阶段 1 探针（ARCHITECTURE §13）：mpv 渲染桥的软件渲染 + 页面画布，在 1080p HEVC 10bit 下是否流畅、跳转与逐帧是否及时。
import { useEffect, useRef, useState } from "react";
import type { ProbeMetric, ProbeStats } from "../../shared/protocol";
import { Button } from "../components/Button";
import { t } from "../i18n";
import s from "./Tools.module.css";

export function ProbePanel() {
  const [attached, setAttached] = useState(false);
  const [st, setSt] = useState<ProbeStats | null>(null);
  const [fps, setFps] = useState(0);
  const [cpu, setCpu] = useState<ProbeMetric[]>([]);
  const last = useRef({ shown: 0, at: performance.now() });

  useEffect(() => {
    const probe = window.ottoProbe;
    if (!probe) return;
    setAttached(probe.attach());
    const timer = setInterval(() => {
      const x = probe.stats();
      setSt(x);
      if (x) {
        const now = performance.now();
        setFps(((x.framesShown - last.current.shown) * 1000) / (now - last.current.at));
        last.current = { shown: x.framesShown, at: now };
      }
      void probe.metrics().then(setCpu);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const p = window.ottoProbe;
  if (!p) return null;
  const total = cpu.reduce((a, m) => a + m.cpu, 0);
  return (
    <section className={`${s.card} ${s.probeCard}`} data-testid="probe">
      <h3>{t("probe.title")}</h3>
      <p>{t("probe.body")}</p>
      <canvas data-mpv-canvas className={s.probeCanvas} />
      <div className={s.btns}>
        <Button size="sm" variant="primary" isDisabled={!attached} onPress={() => void p.open()} data-testid="probe-open">
          {t("probe.open")}
        </Button>
        <Button size="sm" onPress={() => p.control("toggle")} data-testid="probe-toggle">
          {t("probe.toggle")}
        </Button>
        <Button size="sm" onPress={() => p.control("seekRel", -5)}>
          {t("probe.back5")}
        </Button>
        <Button size="sm" onPress={() => p.control("seekRel", 5)}>
          {t("probe.fwd5")}
        </Button>
        <Button size="sm" onPress={() => p.control("step")}>
          {t("probe.step")}
        </Button>
        <Button size="sm" onPress={() => p.control("backStep")}>
          {t("probe.backStep")}
        </Button>
      </div>
      {st ? (
        <div className={`${s.stats} mono`} data-testid="probe-stats">
          {t("probe.stats", {
            pos: st.timePos?.toFixed(3) ?? "-",
            hw: st.hwdec ?? "-",
            fps: fps.toFixed(1),
            avg: st.renderMsAvg.toFixed(1),
            max: st.renderMsMax.toFixed(1),
            drops: st.frameDrops ?? "-",
            dec: st.decoderDrops ?? "-",
            cpu: total.toFixed(0),
          })}
        </div>
      ) : null}
    </section>
  );
}
