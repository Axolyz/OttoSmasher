// 「作品设置…」（阶段 3.13，所有者 2026-10-07）：原片文件夹里的一个作品文件夹。
// - 作品名：改名 = 改磁盘上的文件夹名（同时改这些原片的路径与作品名）；改名不进撤销记录，改回去再改一次即可；已有同名作品 → 拒绝。
// - 来源类型：整组一起设（新放进来的文件沿用）；同名画面自动绑定：新文件用。这两项走编辑通道，可撤销。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { WorkFolder } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox } from "../components/Controls";
import { TextField } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export function WorkSettingsDialog(props: { folder: WorkFolder | null; onClose: () => void; onDone: () => void; onRenamed?: (from: string, to: string) => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const f = props.folder;
  const [name, setName] = useState("");
  const [type, setType] = useState("");
  const [bind, setBind] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!f) return;
    setName(f.name);
    setType(f.sourceType);
    setBind(f.bindPictures);
  }, [f]);

  const renaming = !!f && name.trim() !== "" && name.trim() !== f.name;
  const settingsChanged = !!f && (type.trim() !== f.sourceType || bind !== f.bindPictures);
  const save = async () => {
    if (!f || busy) return;
    setBusy(true);
    try {
      if (renaming) {
        await call("works.rename", { id: f.id, name: name.trim() });
        props.onRenamed?.(f.name, name.trim());
      }
      if (settingsChanged) {
        const batch = await call("works.settingsBatch", { id: f.id, sourceType: type.trim(), bindPictures: bind });
        await call("edits.apply", { batch });
      }
      if (renaming || settingsChanged)
        toast({
          text: renaming ? t("workSettings.renamed", { from: f.name, to: name.trim() }) : t("workSettings.saved"),
          // 撤销只撤类型 / 画面开关；改名是文件操作，不进撤销记录
          action: settingsChanged ? { label: t("workSettings.undoSettings"), run: () => void undo().then(props.onDone) } : undefined,
        });
      props.onDone();
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
      props.onDone();
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogBox
      isOpen={f != null}
      onClose={props.onClose}
      title={t("workSettings.title")}
      sub={f ? <span className="mono" data-user-data="">{f.path}</span> : undefined}
      width={560}
      testId="work-settings"
      footer={
        <>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={busy || !name.trim() || (!renaming && !settingsChanged)} onPress={() => void save()} data-testid="work-settings-save">
            {t("common.save")}
          </Button>
        </>
      }
    >
      <Callout>{t("workSettings.note", { n: f?.sources ?? 0 })}</Callout>
      <div className={s.form}>
        <span className={s.formLabel}>{t("sources.field.work")}</span>
        <TextField value={name} onChange={setName} label={t("sources.field.work")} testId="work-settings-name" />
        <span className={s.formLabel}>{t("sources.field.type")}</span>
        <TextField value={type} onChange={setType} label={t("sources.field.type")} placeholder={t("sources.field.typeHint")} testId="work-settings-type" />
      </div>
      <Checkbox isSelected={bind} onChange={setBind} label={t("workSettings.bind")} testId="work-settings-bind">
        {t("workSettings.bind")}
      </Checkbox>
      {renaming ? (
        <Callout tone="warn" testId="work-settings-rename-note">
          {t("workSettings.renameNote", { from: f!.name, to: name.trim() })}
        </Callout>
      ) : null}
    </DialogBox>
  );
}
