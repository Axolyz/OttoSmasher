// 「画面绑定…」（规格 12 §12.4；UI_PLAN §3 资料与来源 / 舞台 ⋯、§4 查看器 ⋯；原型 epItems「原片画面绑定…」）。
// 采样或原片：看现在用的是哪个画面（采样自己的 > 原片的 > 原片自带的视频流），换一个文件（视频 = 同步〔可加偏移〕或循环，
// 动图 = 循环，图片 = 静态），或去掉（回到下一级）。改动走统一编辑通道、可撤销；绑定文件记下大小和修改时间，之后变了会报错。
// 另有原片批量「匹配同名画面」：同一文件夹里与原片同名的视频 / 动图 / 图片，预览后一次挂上。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import { useThumb } from "../api/thumbs";
import type { MatchItem, VisualBinding } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Segmented } from "../components/Controls";
import { NumberField } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { Thumb } from "../components/Thumb";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export interface VisualTarget {
  ownerType: "sample" | "source";
  id: string;
  name: string;
}

const base = (p: string) => p.split(/[\\/]/).pop() ?? p;

export function VisualDialog(props: { target: VisualTarget | null; onClose: () => void; onDone?: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const tg = props.target;
  const [cur, setCur] = useState<VisualBinding | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [mode, setMode] = useState<"sync" | "loop" | "image">("sync");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const thumb = useThumb(tg?.ownerType ?? "sample", tg?.id ?? "", "list");

  const load = async () => {
    if (!tg) return;
    try {
      const b = tg.ownerType === "sample" ? (await call("visuals.forSample", { id: tg.id })).binding : await call("visuals.forSource", { sourceId: tg.id });
      setCur(b);
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    }
  };
  useEffect(() => {
    setPick(null);
    setError(null);
    setOffset(0);
    void load();
  }, [tg?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const ext = (pick ?? "").split(".").pop()?.toLowerCase() ?? "";
  const kind = ["png", "jpg", "jpeg", "webp", "bmp"].includes(ext) ? "image" : ext === "gif" ? "anim" : "video";
  useEffect(() => setMode(kind === "image" ? "image" : kind === "anim" ? "loop" : "sync"), [kind, pick]);

  const version = async (): Promise<number> => {
    if (tg!.ownerType === "sample") return (await call("samples.get", { id: tg!.id })).version;
    return (await call("sources.get", { id: tg!.id })).version;
  };
  const attach = async (bindingId: string | null) => {
    if (!tg) return;
    setBusy(true);
    try {
      await call("edits.apply", {
        batch: {
          label: { code: "visual-bind", args: { name: tg.name } },
          ops: [{ entity: tg.ownerType, id: tg.id, version: await version(), fields: { visual_binding_id: bindingId } }],
        } as never,
      });
      toast({ text: t(bindingId ? "visual.bound" : "visual.unbound"), action: { label: t("common.undo"), run: () => void undo().then(() => props.onDone?.()) } });
      props.onDone?.();
      props.onClose();
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setBusy(false);
    }
  };
  const bind = async () => {
    if (!tg || !pick) return;
    try {
      const r = await call("visuals.prepare", { ownerType: tg.ownerType, ownerId: tg.id, path: pick, mode, offset: mode === "sync" ? offset : 0 });
      await attach(r.bindingId);
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    }
  };

  const own = cur && cur.origin === tg?.ownerType;
  return (
    <DialogBox
      isOpen={!!tg}
      onClose={props.onClose}
      title={t("visual.title")}
      sub={tg ? t(tg.ownerType === "sample" ? "visual.subSample" : "visual.subSource", { name: tg.name }) : undefined}
      width={560}
      testId="visual-dialog"
      footer={
        <>
          {own ? (
            <Button variant="flat" onPress={() => void attach(null)} isDisabled={busy} data-testid="visual-unbind">
              {t(tg?.ownerType === "sample" ? "visual.unbindSample" : "visual.unbindSource")}
            </Button>
          ) : null}
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={() => void bind()} isDisabled={busy || !pick} data-testid="visual-bind">
            {t("visual.bind")}
          </Button>
        </>
      }
    >
      <div className={s.visualNow}>
        <Thumb url={thumb} testId="visual-thumb" />
        <div className={s.visualNowText} data-testid="visual-current">
          {cur ? (
            <>
              <div>{t(`visual.origin.${cur.origin}`)} · {t(`visual.mode.${cur.mode}`)}</div>
              <div className={s.muted} data-user-data="">
                {base(cur.path)}
                {cur.mode === "sync" && cur.offset ? ` · ${t("visual.offsetN", { s: cur.offset })}` : ""}
              </div>
              {cur.state !== "ok" ? <div className={s.bad}>{t(`visual.state.${cur.state}`)}</div> : null}
            </>
          ) : (
            <div className={s.muted}>{t("visual.none")}</div>
          )}
        </div>
      </div>
      <div className={s.visualPick}>
        <Button
          variant="secondary"
          onPress={async () => {
            const [p] = await window.otto.files.pick("picture");
            if (p) setPick(p);
          }}
          data-testid="visual-pick"
        >
          {t("visual.pickFile")}
        </Button>
        <span className={s.muted} data-user-data="">
          {pick ? base(pick) : t("visual.pickHint")}
        </span>
      </div>
      {pick && kind === "video" ? (
        <div className={s.visualPick}>
          <Segmented<"sync" | "loop">
            value={mode === "loop" ? "loop" : "sync"}
            onChange={setMode}
            label={t("visual.modeLabel")}
            options={[
              { id: "sync", label: t("visual.mode.sync") },
              { id: "loop", label: t("visual.mode.loop") },
            ]}
          />
          {mode === "sync" ? (
            <>
              <span className={s.muted}>{t("visual.offset")}</span>
              <NumberField value={offset} onChange={setOffset} step={0.04} label={t("visual.offset")} />
            </>
          ) : null}
        </div>
      ) : null}
      <div className={s.muted}>{t("visual.rules")}</div>
      {error ? <Callout tone="bad">{error}</Callout> : null}
    </DialogBox>
  );
}

/** 原片批量「匹配同名画面」：预览每个原片找到的画面（视频 > 动图 > 图片；同名多个列出冲突）→ 一次挂上（可撤销） */
export function MatchPicturesDialog(props: { ids: string[] | null; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const [plan, setPlan] = useState<MatchItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setPlan(null);
    setError(null);
    if (props.ids?.length) void call("visuals.matchPlan", { ids: props.ids }).then(setPlan, (e) => setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)));
  }, [props.ids]);
  const found = (plan ?? []).filter((x) => x.picture);
  const apply = async () => {
    try {
      await call("visuals.matchApply", { items: found });
      toast({ text: t("visual.matched", { n: found.length }), action: { label: t("common.undo"), run: () => void undo().then(props.onDone) } });
      props.onDone();
      props.onClose();
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    }
  };
  return (
    <DialogBox
      isOpen={!!props.ids}
      onClose={props.onClose}
      title={t("visual.matchTitle", { n: props.ids?.length ?? 0 })}
      sub={t("visual.matchSub")}
      width={640}
      testId="match-pictures"
      footer={
        <>
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={() => void apply()} isDisabled={!found.length} data-testid="match-apply">
            {t("visual.matchApply", { n: found.length })}
          </Button>
        </>
      }
    >
      {plan ? (
        <PagedTable<MatchItem & { id: string }>
          label={t("visual.matchTitle", { n: plan.length })}
          rows={plan.map((x) => ({ ...x, id: x.sourceId }))}
          pageSize={10}
          columns={[
            { id: "pic", label: t("visual.col.picture"), isRowHeader: true, render: (r) => <span data-user-data="">{r.picture ? base(r.picture) : t("visual.notFound")}</span> },
            { id: "kind", label: t("visual.col.kind"), width: "90px", render: (r) => (r.kind ? t(`visual.kind.${r.kind}`) : "") },
            {
              id: "note",
              label: "",
              width: "180px",
              render: (r) => (
                <span className={s.muted}>
                  {r.conflicts.length ? t("visual.conflicts", { n: r.conflicts.length }) : ""}
                  {r.hasBinding ? ` ${t("visual.replaces")}` : ""}
                </span>
              ),
            },
          ]}
        />
      ) : null}
      {error ? <Callout tone="bad">{error}</Callout> : null}
    </DialogBox>
  );
}
