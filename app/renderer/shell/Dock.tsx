import { FileAudio, Play, Square, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { RhythmSound } from "../api/types";
import { Button } from "../components/Button";
import { ProgressBar } from "../components/Controls";
import { seconds } from "../format";
import { t } from "../i18n";
import { type AuditionDetails, type AuditionVersion, auditionPosition, stopAudition, useAudition } from "../state/audition";
import { useApp } from "../state/store";
import s from "./Shell.module.css";

/** 当前声音的版本说明（UI_PLAN §1：原声 / 卡拍及方案；所有者 2026-10-08 的三种声音） */
function versionLabel(version: AuditionVersion, sound: RhythmSound, { plan, bpm, originalSpeed }: AuditionDetails): string {
  const base =
    version === "original"
      ? t("audition.original")
      : originalSpeed
        ? t("audition.stretchedOriginal", { plan: t(`rhythm.plan.${plan ?? "near_fast"}`) })
        : t("audition.stretchedBpm", { bpm: bpm ?? "", plan: t(`rhythm.plan.${plan ?? "near_fast"}`) });
  return sound === "voice" ? base : `${base} · ${t(`rhythm.sound.${sound}`)}`;
}

/** 全局播放条（UI_PLAN §1）：当前声音（名称、原声/卡拍及方案、进度、停止）；导出交接（最近导出的文件：普通拖动即可拖进 DAW / Finder、定位）；
 *  “资料已更新 · 刷新浏览列表”。 */
export function Dock() {
  const stale = useApp((st) => st.stale);
  const refreshLists = useApp((st) => st.refreshLists);
  const preview = useAudition((st) => st.current);
  const details = preview?.details;
  const lastExport = useApp((st) => st.lastExport);
  const setLastExport = useApp((st) => st.setLastExport);
  const [pos, setPos] = useState(0);
  useEffect(() => {
    if (!details) return;
    setPos(0);
    const id = setInterval(() => setPos(auditionPosition() ?? 0), 100);
    return () => clearInterval(id);
  }, [details]);
  return (
    <footer className={s.dock}>
      <div className={s.np} data-testid="dock-now">
        {preview && details ? (
          <>
            <Button
              variant="flat"
              size="sm"
              icon={<Square />}
              onPress={stopAudition}
              aria-label={t("library.stop")}
              data-testid="dock-stop"
            />
            <span className={s.npName} lang="ja" data-user-data="">
              {preview.request.name}
            </span>
            <span className={s.npVer} data-ver={preview.request.version} data-testid="dock-version">
              {versionLabel(preview.request.version, preview.request.sound, details)}
            </span>
            <span className={s.npBar}>
              <ProgressBar value={details.duration > 0 ? Math.min(pos, details.duration) : null} max={details.duration || 1} label={t("dock.progress")} />
            </span>
            <span className={`${s.muted} num`}>
              {seconds(Math.min(pos, details.duration))} / {seconds(details.duration)}
            </span>
          </>
        ) : (
          <>
            <span className={s.pp} aria-hidden>
              <Play size={14} />
            </span>
            <span className={s.muted}>{t("dock.idle")}</span>
          </>
        )}
      </div>
      <div className={s.grow} />
      {lastExport ? (
        <div className={s.note} data-testid="dock-export">
          <span
            className={s.exportFile}
            draggable
            onDragStart={(e) => {
              // 已经是导出好的真实文件：普通拖动交给系统拖拽（不需要 ⌥，也不重新生成）
              e.preventDefault();
              window.otto.files.startDrag(lastExport);
            }}
            title={t("dock.exportDrag")}
          >
            <FileAudio size={13} />
            <span data-user-data="">{lastExport.length > 1 ? t("dock.exportedN", { n: lastExport.length }) : (lastExport[0]!.split(/[\\/]/).pop() ?? "")}</span>
          </span>
          <button type="button" className={s.noteBtn} onClick={() => void window.otto.files.reveal(lastExport[0]!)} data-testid="dock-reveal">
            {t("sources.reveal")}
          </button>
          <button type="button" className={s.noteX} onClick={() => setLastExport(null)} aria-label={t("common.close")}>
            <X size={12} />
          </button>
        </div>
      ) : null}
      {stale ? (
        <div className={s.note}>
          {t("dock.stale")}
          <button type="button" className={s.noteBtn} onClick={refreshLists} data-testid="refresh-lists">
            {t("dock.refresh")}
          </button>
        </div>
      ) : null}
    </footer>
  );
}
