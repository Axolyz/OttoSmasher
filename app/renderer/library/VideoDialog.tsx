// 导出视频片段（规格 12 §12.5、16 R21.9；原型 videoModal；Q8：没有画面报错并给「画面绑定…」，不生成黑屏）。
// 原声版画面原速；卡拍版两种画面：按同一映射变速（音画同步）/ 原速画面（带原声，另存卡拍 WAV 与映射清单）。可选不带声音。
// 编码在任务里做；完成后播放条显示导出的文件（exports.videoDone）。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { RhythmPlan, SampleRow } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, Segmented } from "../components/Controls";
import { DialogBox } from "../components/Overlay";
import { exportWords } from "../exportWords";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Library.module.css";

export interface VideoRequest {
  sample: SampleRow;
  /** 舞台上的临时方案（卡拍版用） */
  plan?: RhythmPlan;
  mora?: boolean;
  longVowel?: boolean;
}

const isSingle = (n: string) => n === "pitched" || n === "unpitched";

export function VideoDialog(props: { req: VideoRequest | null; onClose: () => void; onBind: (r: SampleRow) => void }) {
  const toast = useApp((st) => st.toast);
  const r = props.req?.sample ?? null;
  const [version, setVersion] = useState<"original" | "stretched">("original");
  const [picture, setPicture] = useState<"synced" | "original">("synced");
  const [audio, setAudio] = useState(true);
  const [mode, setMode] = useState<string | null>(null);
  const [error, setError] = useState<{ text: string; none: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!r) return;
    setVersion("original");
    setPicture("synced");
    setAudio(true);
    setError(null);
    setMode(null);
    void call("visuals.forSample", { id: r.id }).then(
      (p) => {
        setMode(p.binding ? p.binding.mode : null);
        if (!p.binding) setError({ text: t("error.visual-none"), none: true });
      },
      () => {},
    );
  }, [r?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = async () => {
    if (!r) return;
    setBusy(true);
    try {
      const res = await call("exports.video", {
        id: r.id,
        version,
        picture,
        audio,
        words: exportWords(),
        plan: props.req?.plan,
        mora: props.req?.mora,
        longVowel: props.req?.longVowel,
      });
      if (res.reused && res.path) {
        useApp.getState().setLastExport([res.path]);
        toast({ text: t("video.reused"), action: { label: t("sources.reveal"), run: () => void window.otto.files.reveal(res.path!) } });
      } else toast({ text: t("video.queued", { name: r.name }) });
      props.onClose();
    } catch (e) {
      const wire = e instanceof CoreFailure ? e.wire : null;
      setError({ text: wire ? errorText(wire) : String(e), none: wire?.code === "visual-none" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogBox
      isOpen={!!r}
      onClose={props.onClose}
      title={t("video.title")}
      sub={r ? `${r.name} · ${mode ? t(`visual.mode.${mode}`) : t("stagePic.none")}` : undefined}
      width={520}
      testId="video-dialog"
      footer={
        <>
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={() => void go()} isDisabled={busy || !mode} data-testid="video-go">
            {t("video.go")}
          </Button>
        </>
      }
    >
      <div className={s.hintText}>{t("video.say")}</div>
      {r && !isSingle(r.nature) ? (
        <div className={s.editGrid}>
          <span>{t("video.version")}</span>
          <Segmented<"original" | "stretched">
            value={version}
            onChange={setVersion}
            label={t("video.version")}
            options={[
              { id: "original", label: t("video.original") },
              { id: "stretched", label: t("video.stretched") },
            ]}
          />
          {version === "stretched" ? (
            <>
              <span>{t("video.picture")}</span>
              <Segmented<"synced" | "original">
                value={picture}
                onChange={setPicture}
                label={t("video.picture")}
                options={[
                  { id: "synced", label: t("video.synced") },
                  { id: "original", label: t("video.originalSpeed") },
                ]}
              />
            </>
          ) : null}
        </div>
      ) : null}
      <Checkbox isSelected={audio} onChange={setAudio} label={t("video.audio")}>
        {t("video.audio")}
      </Checkbox>
      {error ? (
        <Callout tone="bad" testId="video-error">
          {error.text}
          {error.none && r ? (
            <Button size="sm" variant="flat" onPress={() => props.onBind(r)} data-testid="video-bind">
              {t("visual.menu")}
            </Button>
          ) : null}
        </Callout>
      ) : null}
    </DialogBox>
  );
}
