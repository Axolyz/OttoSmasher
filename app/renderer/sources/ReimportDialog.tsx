// 回导（规格 06 §6.7、16 S8；UI_PLAN §8 动作条「回导」；原型 reimportModal）：起点 = 当前选区起点，终点按文件时长（手选终点被忽略），
// 超出资产边界不保存；文件复制进素材库、保持原格式；不补静音、不裁切、不变速；新采样性质默认未分类，名称预填它落到的那段的建议名（可改）。
// 采样之间没有父子关系（所有者 2026-10-12）：回导成品与原选区上的采样互为相关采样（原素材时间交叠）。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { Nature, ReimportPreview } from "../api/types";
import { Button } from "../components/Button";
import { Callout } from "../components/Controls";
import { TextField } from "../components/Fields";
import { NaturePicker } from "../components/NaturePicker";
import { DialogBox } from "../components/Overlay";
import { clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { autoProjectTags } from "../state/project";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export interface ReimportRequest {
  assetId: string;
  /** 选区起点（资产局部秒） */
  start: number;
}

const base = (p: string) => p.split(/[\\/]/).pop() ?? p;

export function ReimportDialog(props: { req: ReimportRequest | null; onClose: () => void; onSaved?: (sampleId: string) => void }) {
  const toast = useApp((st) => st.toast);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const setPage = useApp((st) => st.setPage);
  const req = props.req;
  const [path, setPath] = useState<string | null>(null);
  const [pv, setPv] = useState<ReimportPreview | null>(null);
  const [name, setName] = useState("");
  const [nature, setNature] = useState<Nature>("unclassified");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setPath(null);
    setPv(null);
    setError(null);
    setNature("unclassified");
    setName("");
  }, [req?.assetId, req?.start]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!req || !path) return;
    void call("reimport.preview", { assetId: req.assetId, start: req.start, path }).then(
      (p) => {
        setPv(p);
        setError(null);
        if (p.suggestedName) setName((n) => n || p.suggestedName!);
      },
      (e) => setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)),
    );
  }, [req, path]);
  const save = async () => {
    if (!req || !path || !pv?.ok) return;
    setBusy(true);
    try {
      const r = await call("reimport.commit", { assetId: req.assetId, start: req.start, path, name: name.trim() || null, nature, localTags: autoProjectTags() });
      toast({ text: t("reimport.saved", { name: r.name }) });
      props.onClose();
      if (props.onSaved) props.onSaved(r.id);
      else {
        setOpenSample(r.id);
        setPage("library");
      }
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <DialogBox
      isOpen={!!req}
      onClose={props.onClose}
      title={t("reimport.title")}
      sub={req ? t("reimport.sub", { start: seconds(req.start) }) : undefined}
      width={540}
      testId="reimport-dialog"
      footer={
        <>
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={() => void save()} isDisabled={busy || !pv?.ok} data-testid="reimport-save">
            {t("reimport.save")}
          </Button>
        </>
      }
    >
      <div className={s.muted}>{t("reimport.say")}</div>
      <div className={s.visualPick}>
        <Button
          variant="secondary"
          onPress={async () => {
            const [p] = await window.otto.files.pick("reimport");
            if (p) setPath(p);
          }}
          data-testid="reimport-pick"
        >
          {t("visual.pickFile")}
        </Button>
        <span className={s.muted} data-user-data="">
          {path ? base(path) : t("reimport.pickHint")}
        </span>
      </div>
      {pv ? (
        <Callout tone={pv.ok ? "info" : "bad"} testId="reimport-preview">
          {pv.ok
            ? t("reimport.preview", { d: seconds(pv.duration), rate: (pv.sampleRate / 1000).toFixed(1), end: seconds(pv.end), src: clock(pv.sourceEnd) })
            : t("reimport.outOfBounds", { d: seconds(pv.duration), end: seconds(pv.end), max: seconds(pv.assetDuration) })}
        </Callout>
      ) : null}
      <TextField value={name} onChange={setName} label={t("reimport.name")} placeholder={t("reimport.namePlaceholder")} testId="reimport-name" />
      <div className={s.visualPick}>
        <span className={s.muted}>{t("nature.label")}</span>
        <NaturePicker value={nature} onChange={setNature} testId="reimport-nature" />
      </div>
      {error ? <Callout tone="bad">{error}</Callout> : null}
    </DialogBox>
  );
}
