// 批量「作品与类型…」（所有者 2026-10-07）：把勾选的一批原片统一改作品 / 来源类型——已登记原片的“重新归组”走这里（不靠再导入一次）。
// 只改勾了“修改”的那一项；走统一编辑通道，一次可撤销；作品与类型实时传给这些原片的派生采样（work: / type:，规格 05 §5.1）。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox } from "../components/Controls";
import { TextField } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

const same = (xs: string[]) => (xs.every((x) => x === xs[0]) ? (xs[0] ?? "") : "");

export function WorkTypeDialog(props: { rows: SourceRow[] | null; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const rows = props.rows;
  const [setWorkOn, setSetWorkOn] = useState(true);
  const [setTypeOn, setSetTypeOn] = useState(false);
  const [work, setWork] = useState("");
  const [type, setType] = useState("");
  const [busy, setBusy] = useState(false);
  const inFolders = rows?.filter((r) => r.root_id).length ?? 0;
  useEffect(() => {
    if (!rows) return;
    setSetWorkOn(true);
    setSetTypeOn(false);
    setWork(same(rows.map((r) => r.work)));
    setType(same(rows.map((r) => r.source_type)));
  }, [rows]);

  const apply = async () => {
    if (!rows || busy) return;
    // 原片文件夹里的原片作品跟着文件夹走（阶段 3.13）：只改它们的类型
    const fieldsFor = (r: SourceRow) => {
      const f: Record<string, string> = {};
      if (setWorkOn && !r.root_id) f.work = work.trim();
      if (setTypeOn) f.source_type = type.trim();
      return f;
    };
    setBusy(true);
    try {
      await call("edits.apply", {
        batch: { label: { code: "sources-meta", args: { n: rows.length } }, ops: rows.filter((r) => Object.keys(fieldsFor(r)).length).map((r) => ({ entity: "source", id: r.id, version: r.version, fields: fieldsFor(r) })) },
      });
      toast({ text: t("workType.done", { n: rows.length }), action: { label: t("common.undo"), run: () => void undo().then(props.onDone) } });
      props.onDone();
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogBox
      isOpen={rows != null}
      onClose={props.onClose}
      title={t("workType.title")}
      sub={t("workType.sub", { n: rows?.length ?? 0 })}
      width={500}
      testId="work-type-dialog"
      footer={
        <>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={busy || (!setWorkOn && !setTypeOn)} onPress={() => void apply()} data-testid="work-type-ok">
            {t("common.save")}
          </Button>
        </>
      }
    >
      <Callout>{t("workType.note")}</Callout>
      {inFolders ? <Callout tone="warn">{t("workType.inFolders", { n: inFolders })}</Callout> : null}
      <div className={s.form}>
        <Checkbox isSelected={setWorkOn} onChange={setSetWorkOn} label={t("workType.setWork")} testId="work-type-work-on">
          {t("sources.field.work")}
        </Checkbox>
        <TextField value={work} onChange={setWork} isDisabled={!setWorkOn} label={t("sources.field.work")} placeholder={t("workType.workHint")} testId="work-type-work" />
        <Checkbox isSelected={setTypeOn} onChange={setSetTypeOn} label={t("workType.setType")} testId="work-type-type-on">
          {t("sources.field.type")}
        </Checkbox>
        <TextField value={type} onChange={setType} isDisabled={!setTypeOn} label={t("sources.field.type")} placeholder={t("sources.field.typeHint")} testId="work-type-type" />
      </div>
    </DialogBox>
  );
}
