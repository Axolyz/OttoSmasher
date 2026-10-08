// 分离结果 · 声音资产（规格 05 §5.5.2；任务抽屉「打开结果」）：每个声部可试听、保存为采样（名称“建议名 · 声部”，性质未分类）、⌥/Alt 拖出。
// 结果不会自动保存为采样，也不会自动设为默认轨。
import { GripVertical, Play, Save, Square } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { AssetRecord } from "../api/types";
import { Button } from "../components/Button";
import { beginDragOut } from "../dragout";
import { seconds } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./TaskDrawer.module.css";

type ResultAsset = AssetRecord;

export function SeparationResults({ jobId }: { jobId: string }) {
  const toast = useApp((st) => st.toast);
  const [rows, setRows] = useState<ResultAsset[] | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  useEffect(() => {
    void call("separation.results", { jobId }).then(setRows, () => setRows([]));
  }, [jobId]);
  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : errorText(e as { code: string; args: Record<string, unknown> }), tone: "error" });

  const audition = async (a: ResultAsset) => {
    if (playing === a.id) {
      window.otto.player.stopAudition();
      setPlaying(null);
      return;
    }
    try {
      setPlaying(a.id);
      await window.otto.player.audition(a.id, 0, a.duration);
    } catch (e) {
      setPlaying(null);
      fail(e);
    }
  };
  const save = async (a: ResultAsset) => {
    try {
      const sg = await call("samples.suggest", { assetId: a.id, start: 0, end: a.duration, localMarker: t("naming.local") });
      const smp = await call("samples.create", { assetId: a.id, start: 0, end: a.duration, name: `${sg.name} · ${a.stem_name}`, nature: "unclassified" });
      toast({ text: t("clip.saved", { name: smp.name }) });
    } catch (e) {
      fail(e);
    }
  };
  if (!rows) return null;
  if (!rows.length) return <div className={s.none}>{t("sep.resultsNone")}</div>;
  return (
    <div className={s.results} data-testid="sep-results">
      <div className={s.resultsHead}>{t("sep.resultsTitle")}</div>
      {rows.map((a) => (
        <div
          key={a.id}
          className={s.resultRow}
          title={t("sep.dragHint")}
          onPointerDown={(e) => {
            if ((e.target as Element).closest("button")) return;
            beginDragOut(e, async () => [
              (await call("exports.wav", { assetId: a.id, start: 0, end: a.duration, content: a.stem_name ?? "", track: a.stem_name ?? "" })).path,
            ]);
          }}
        >
          <GripVertical size={13} className={s.grip} />
          <b>{a.stem_name}</b>
          <span className="num">{t("format.sec", { v: seconds(a.duration) })}</span>
          {a.roles.length ? <span className={s.chip}>{a.roles.map((r) => t(`role.${r}`)).join(" + ")}</span> : null}
          <span className={s.grow} />
          <Button size="sm" variant="flat" icon={playing === a.id ? <Square /> : <Play />} onPress={() => void audition(a)} aria-label={t("library.audition")} />
          <Button size="sm" variant="flat" icon={<Save />} onPress={() => void save(a)}>
            {t("sep.saveAsSample")}
          </Button>
        </div>
      ))}
    </div>
  );
}
