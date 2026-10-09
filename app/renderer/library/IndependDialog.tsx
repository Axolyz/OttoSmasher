// 采样独立化（规格 04 §4.8；UI_PLAN §8「采样右键『独立化…』· 批量」；Q4：声音存 WAV、画面存视频片段）。
// 确认框写明会存什么（切片大小、几个画面片段）与之后的限制（删原片后不能再返回原片看前后文）；在任务里做。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { IndependItem } from "../api/types";
import { ConfirmDialog } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Library.module.css";

export function IndependDialog(props: { ids: string[] | null; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const [plan, setPlan] = useState<IndependItem[] | null>(null);
  useEffect(() => {
    setPlan(null);
    if (props.ids?.length) void call("samples.independPlan", { ids: props.ids }).then(setPlan, () => setPlan([]));
  }, [props.ids]);
  const todo = (plan ?? []).filter((x) => !x.independent);
  const mb = todo.reduce((n, x) => n + x.bytes, 0) / 1048576;
  const go = async () => {
    try {
      await call("samples.independ", { ids: todo.map((x) => x.id) });
      toast({ text: t("indep.queued", { n: todo.length }) });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
    props.onClose();
  };
  return (
    <ConfirmDialog
      isOpen={!!props.ids?.length}
      title={t("indep.title", { n: todo.length })}
      confirmLabel={t("indep.go")}
      confirmDisabled={!todo.length}
      onConfirm={() => void go()}
      onClose={props.onClose}
      testId="independ-dialog"
    >
      <div className={s.hintText}>{t("indep.say")}</div>
      {plan ? <div className={s.mutedText}>{t("indep.size", { n: todo.length, mb: mb.toFixed(1), v: todo.filter((x) => x.picture).length })}</div> : null}
      {plan && plan.length > todo.length ? <div className={s.mutedText}>{t("indep.already", { n: plan.length - todo.length })}</div> : null}
    </ConfirmDialog>
  );
}
