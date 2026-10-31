// 删除导入的字幕标记（所有者 2026-10-31）：原素材上从字幕来的段、音效提示、字幕规则标的 OP/ED 一次删掉（一个编辑批次，能撤销），
// 之后可以从头重新导入。手输的段不删；改过的 / 有人工音素的默认留下（勾选才删）。采样不删，只是不再读到这些段。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SubtitleClearPlan } from "../api/types";
import { Checkbox } from "../components/Controls";
import { ConfirmDialog } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export function SubtitleClearDialog(props: { sourceIds: string[] | null; onClose: () => void }) {
  const [plan, setPlan] = useState<SubtitleClearPlan | null>(null);
  const [withProtected, setWithProtected] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useApp((st) => st.toast);
  useEffect(() => {
    setPlan(null);
    setWithProtected(false);
    if (props.sourceIds?.length) void call("subtitles.clearPlan", { sourceIds: props.sourceIds }).then(setPlan, (e) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" }));
  }, [props.sourceIds, toast]);
  const protectedN = plan ? plan.segmentsProtected + plan.hintsProtected + plan.opedProtected : 0;
  const total = plan ? plan.segments + plan.hints + plan.oped - (withProtected ? 0 : protectedN) : 0;
  const run = async () => {
    if (!props.sourceIds) return;
    setBusy(true);
    try {
      const r = await call("subtitles.clear", { sourceIds: props.sourceIds, protected: withProtected });
      toast({ text: t("subclear.done", { segments: r.segments, hints: r.hints, oped: r.oped }) });
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };
  return (
    <ConfirmDialog
      isOpen={!!props.sourceIds}
      title={t("subclear.title", { n: props.sourceIds?.length ?? 0 })}
      confirmLabel={t("subclear.confirm", { n: total })}
      danger
      busy={busy || !plan}
      confirmDisabled={!total}
      onConfirm={() => void run()}
      onClose={props.onClose}
      testId="subtitle-clear"
    >
      {plan ? (
        <div className={s.clearBody}>
          <p data-testid="subclear-plan">
            {t("subclear.plan", { segments: plan.segments, hints: plan.hints, oped: plan.oped })}
            {plan.segmentsAnalyzed ? ` ${t("subclear.analyzed", { n: plan.segmentsAnalyzed })}` : ""}
            {plan.usedBy ? ` ${t("subclear.usedBy", { n: plan.usedBy })}` : ""}
          </p>
          {protectedN ? (
            <Checkbox isSelected={withProtected} onChange={setWithProtected} label={t("subclear.protected", { n: protectedN })} testId="subclear-protected">
              {t("subclear.protected", { n: protectedN })}
            </Checkbox>
          ) : null}
          <p className={s.hint}>{t("subclear.note", { typed: plan.typedKept })}</p>
        </div>
      ) : null}
    </ConfirmDialog>
  );
}
