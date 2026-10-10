// 语音分析确认框（规格 08 §8.4、16 S1.7；原型 analysisModal）：M / N / K 三个大数字、无法处理的原因、
// 绑在原混音或无角色资产上的提示、默认不勾的「也重新分析已是最新的 N 条」。确认后排队一个任务（提交时冻结输入）。
// 分析属于“段 + 资产”（所有者 2026-10-09）：原片入口与段右键可选「默认人声轨（没有就是原混音）」或「当前查看的轨」。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { ModelsStatus, SpeechPreview } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, Segmented, Stats } from "../components/Controls";
import { DialogBox } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { errorText, hasKey, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Speech.module.css";

/** 无法处理的原因（缺对齐文本 / 截取范围与原台词不同 / 文件缺失等错误码） */
export function blockedReason(reason: string): string {
  return hasKey(`speech.blocked.${reason}`) ? t(`speech.blocked.${reason}`) : errorText({ code: reason, args: {} });
}

export function SpeechDialog() {
  const req = useApp((st) => st.speechRequest);
  const close = useApp((st) => st.requestSpeech);
  const toast = useApp((st) => st.toast);
  const setTasksOpen = useApp((st) => st.setTasksOpen);
  const [rerun, setRerun] = useState(false);
  const [track, setTrack] = useState<"default" | "current">("default");
  const [pv, setPv] = useState<SpeechPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [models, setModels] = useState<ModelsStatus | null>(null);
  useEffect(() => {
    if (req) void call("models.status").then(setModels, () => setModels(null));
  }, [req]);
  // 语音分析要用的模型：对齐、读音预测（缺了任务会失败）；音高 FCPE 缺了只是这次不测 F0，对齐照常（任务里提醒）
  const needed = ["pydomino", "tsqyomi"];
  const absent = (models?.files ?? []).filter((m) => m.state === "missing").map((m) => m.model);
  const missing = [...new Set(absent.filter((m) => needed.includes(m)))].map((m) => t(`models.name.${m}`));
  const noF0 = absent.includes("fcpe");

  useEffect(() => {
    if (!req) {
      setPv(null);
      setRerun(false);
      setTrack("default");
      setError(null);
      return;
    }
    let live = true;
    void call("speech.preview", { entry: req.entry, ids: req.ids, rerunFresh: rerun, assetId: assetId() }).then(
      (r) => live && (setPv(r), setError(null)),
      (e) => live && setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)),
    );
    return () => {
      live = false;
    };
  }, [req, rerun, track]); // eslint-disable-line react-hooks/exhaustive-deps

  // 分析在哪条轨上：默认 = Core 按入口决定（默认人声轨，没有就是原混音；采样入口 = 采样所在的轨）
  function assetId(): string | null {
    return track === "current" && req?.currentAsset && (req.entry === "source" || req.entry === "segments") ? req.currentAsset.id : null;
  }
  const submit = async () => {
    if (!req || !pv || busy) return;
    setBusy(true);
    try {
      await call("speech.submit", { entry: req.entry, ids: req.ids, rerunFresh: rerun, assetId: assetId() });
      toast({ text: t("speech.queued", { n: pv.run }), action: { label: t("speech.openTasks"), run: () => setTasksOpen(true) } });
      close(null);
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const src = req?.entry === "source" || req?.entry === "segments";
  const current = src ? req?.currentAsset : undefined;
  return (
    <DialogBox
      isOpen={req !== null}
      onClose={() => close(null)}
      title={t(`speech.title.${req?.entry ?? "samples"}`, { n: req?.ids.length ?? 0 })}
      sub={t(`speech.scope.${req?.entry ?? "samples"}`)}
      width={560}
      testId="speech-dialog"
      footer={
        <>
          <Button variant="flat" onPress={() => close(null)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={() => void submit()} isDisabled={!pv || pv.run === 0 || busy} data-testid="speech-submit">
            {t("speech.submit", { n: pv?.run ?? 0 })}
          </Button>
        </>
      }
    >
      {current ? (
        <div className={s.trackRow}>
          <span className={s.faint}>{t("speech.track")}</span>
          <Segmented<"default" | "current">
            size="sm"
            label={t("speech.track")}
            value={track}
            onChange={setTrack}
            options={[
              { id: "default", label: t("speech.trackDefault") },
              { id: "current", label: t("speech.trackCurrent", { track: current.label }) },
            ]}
            testId="speech-track"
          />
        </div>
      ) : null}
      {error ? <Callout tone="bad">{error}</Callout> : null}
      {pv ? (
        <div className={s.body}>
          <Stats
            items={[
              { n: pv.run, label: t("speech.stat.run"), testId: "speech-run" },
              { n: pv.fresh, label: t("speech.stat.fresh"), tone: "muted", testId: "speech-fresh" },
              { n: pv.blocked, label: t("speech.stat.blocked"), tone: pv.blocked ? "bad" : "muted", testId: "speech-blocked" },
            ]}
          />
          <div className={s.say}>{t("speech.say")}</div>
          {pv.blockedList.length ? (
            <PagedTable
              label={t("speech.col.blocked")}
              rows={pv.blockedList}
              pageSize={8}
              testId="speech-blocked-list"
              columns={[
                { id: "name", label: t("speech.col.blocked"), isRowHeader: true, render: (b) => <span lang="ja" data-user-data="">{b.name}</span> },
                { id: "reason", label: t("speech.col.reason"), width: "40%", render: (b) => blockedReason(b.reason) },
              ]}
            />
          ) : null}
          {pv.blocked > pv.blockedList.length ? <div className={s.faint}>{t("speech.blockedMore", { n: pv.blocked - pv.blockedList.length })}</div> : null}
          {src && pv.mixBound ? <Callout tone="warn">{t("speech.mixBound", { n: pv.mixBound })}</Callout> : null}
          {missing.length ? (
            <Callout tone="bad">{t("speech.envMissing", { models: missing.join(t("settings.subtitle.speakerSep")) })}</Callout>
          ) : null}
          {noF0 ? <Callout tone="warn" testId="speech-no-f0">{t("speech.envNoF0", { model: t("models.name.fcpe") })}</Callout> : null}
          {models && !missing.length && !noF0 ? <div className={s.faint}>{t("speech.envOk")}</div> : null}
          {pv.freshAll ? (
            <Checkbox isSelected={rerun} onChange={setRerun} label={t("speech.rerunFresh", { n: pv.freshAll })} testId="speech-rerun">
              {t("speech.rerunFresh", { n: pv.freshAll })}
            </Checkbox>
          ) : null}
        </div>
      ) : null}
    </DialogBox>
  );
}
