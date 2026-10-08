import { Play, Square } from "lucide-react";
import { useEffect, useState } from "react";
import type { PlayerState } from "../../shared/protocol";
import { Button } from "../components/Button";
import { ProgressBar } from "../components/Controls";
import { seconds } from "../format";
import { t } from "../i18n";
import { type NowPlaying, useApp } from "../state/store";
import s from "./Shell.module.css";

/** 当前声音的版本说明（UI_PLAN §1：原声 / 卡拍及方案；所有者 2026-10-08 的三种声音） */
export function versionLabel(np: Pick<NowPlaying, "version" | "sound" | "plan" | "bpm" | "originalSpeed">): string {
  const base =
    np.version === "original"
      ? t("audition.original")
      : np.originalSpeed
        ? t("audition.stretchedOriginal", { plan: t(`rhythm.plan.${np.plan ?? "near_fast"}`) })
        : t("audition.stretchedBpm", { bpm: np.bpm ?? "", plan: t(`rhythm.plan.${np.plan ?? "near_fast"}`) });
  return np.sound === "voice" ? base : `${base} · ${t(`rhythm.sound.${np.sound}`)}`;
}

/** 全局播放条（UI_PLAN §1）：当前声音（名称、原声/卡拍及方案、进度、停止）；“资料已更新 · 刷新浏览列表”。 */
export function Dock() {
  const stale = useApp((st) => st.stale);
  const refreshLists = useApp((st) => st.refreshLists);
  const np = useApp((st) => st.nowPlaying);
  const setNowPlaying = useApp((st) => st.setNowPlaying);
  const [pos, setPos] = useState(0);
  useEffect(
    () =>
      window.otto.player.onState((st: PlayerState) => {
        if (st.player === "audition" && (st.ended || st.error)) setNowPlaying(null);
      }),
    [setNowPlaying],
  );
  useEffect(() => {
    if (!np) return;
    setPos(0);
    const id = setInterval(() => setPos(window.otto.player.position("audition") ?? 0), 100);
    return () => clearInterval(id);
  }, [np]);
  return (
    <footer className={s.dock}>
      <div className={s.np} data-testid="dock-now">
        {np ? (
          <>
            <Button
              variant="flat"
              size="sm"
              icon={<Square />}
              onPress={() => {
                window.otto.player.stopAudition();
                setNowPlaying(null);
              }}
              aria-label={t("library.stop")}
              data-testid="dock-stop"
            />
            <span className={s.npName} lang="ja" data-user-data="">
              {np.name}
            </span>
            <span className={s.npVer} data-ver={np.version} data-testid="dock-version">
              {versionLabel(np)}
            </span>
            <span className={s.npBar}>
              <ProgressBar value={np.duration > 0 ? Math.min(pos, np.duration) : null} max={np.duration || 1} label={t("dock.progress")} />
            </span>
            <span className={`${s.muted} num`}>
              {seconds(Math.min(pos, np.duration))} / {seconds(np.duration)}
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
