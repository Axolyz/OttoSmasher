// OP/ED（规格 05 §5.6；UI_PLAN §4、§5 确认框；原型 opedModal）：
// 规则说明 → 「从字幕识别」→ 出错时的错误与待确认配对（逐对改用途并「确认此区间」）→ 已登记区间（来源、删除）→ 手动标记（开始、用途、长度、预览、标记）。
// 所有新建、删除都走统一编辑通道，可撤销；删除 / 撤销不删已有采样。
import { useCallback, useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { SettingEntry, SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Segmented } from "../components/Controls";
import { NumberField, TimeField } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { displayTitle } from "./SourceList";
import s from "./Sources.module.css";

type Kind = "OP" | "ED";
interface Oped {
  id: string;
  kind: Kind;
  start: number;
  end: number;
  via: "rule" | "confirm" | "mark";
}
interface Pair {
  start: number;
  end: number;
  suggest: Kind;
  refs: string[];
  overlaps: string | null;
}
export interface IdentifyResult {
  sourceId: string;
  pairs: Pair[];
  errors: Array<{ code: string; refs: string[]; count?: number }>;
  applied: number;
  skippedOverlap: number;
}

export function identifyText(r: IdentifyResult): string {
  if (r.errors.length) return t("oped.identifyErrors", { n: r.errors.length, pairs: r.pairs.length });
  if (!r.pairs.length) return t("oped.identifyNone");
  return t("oped.identifyApplied", { n: r.applied, skipped: r.skippedOverlap });
}

export function OpedDialog(props: { source: SourceRow | null; initial?: IdentifyResult | null; canPreview: boolean; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const src = props.source;
  const [rows, setRows] = useState<Oped[]>([]);
  const [result, setResult] = useState<IdentifyResult | null>(null);
  const [kinds, setKinds] = useState<Record<number, Kind>>({});
  const [markers, setMarkers] = useState<{ start: string[]; end: string[] }>({ start: [], end: [] });
  const [mStart, setMStart] = useState<number | null>(null);
  const [mKind, setMKind] = useState<Kind>("OP");
  const [mLen, setMLen] = useState(90);
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (src) setRows(await call<Oped[]>("oped.list", { sourceId: src.id }));
  }, [src]);
  useEffect(() => {
    if (!src) return;
    setResult(props.initial ?? null);
    setKinds({});
    void reload();
    void call<Record<string, SettingEntry>>("settings.list").then((st) =>
      setMarkers({ start: st["subtitle.oped_start"]!.value as string[], end: st["subtitle.oped_end"]!.value as string[] }),
    );
  }, [src?.id, props.initial]); // eslint-disable-line react-hooks/exhaustive-deps
  useCoreEvent("data.changed", (d) => {
    if ((d as Record<string, string[]>).oped) void reload();
  });

  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  const done = (text: string) => toast({ text, action: { label: t("common.undo"), run: () => void undo() } });

  const identify = async () => {
    if (!src) return;
    setBusy(true);
    try {
      const r = await call<IdentifyResult>("oped.identify", { sourceId: src.id });
      setResult(r);
      setKinds({});
      if (r.applied) done(identifyText(r));
      else toast({ text: identifyText(r), tone: r.errors.length ? "error" : "info" });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const add = async (kind: Kind, start: number, end: number, via: "confirm" | "mark", refs?: string[]) => {
    if (!src) return;
    try {
      await call("oped.add", { sourceId: src.id, kind, start, end, via, refs });
      done(t(via === "confirm" ? "oped.confirmed" : "oped.marked", { kind }));
      await reload();
    } catch (e) {
      fail(e);
    }
  };

  const remove = async (o: Oped) => {
    try {
      await call("oped.delete", { id: o.id });
      done(t("oped.deleted", { kind: o.kind }));
      await reload();
    } catch (e) {
      fail(e);
    }
  };

  const duration = src?.duration ?? 0;
  const pending = (result?.errors.length ? result.pairs : []).map((p, i) => ({ ...p, i, taken: rows.some((o) => o.start < p.end && o.end > p.start) }));
  const mEnd = mStart == null ? null : mStart + mLen;
  const mValid = mStart != null && mStart >= 0 && mLen > 0 && mEnd! <= duration + 1e-6;

  return (
    <DialogBox
      isOpen={src != null}
      onClose={props.onClose}
      title={t("oped.title")}
      sub={t("oped.rule", { start: markers.start.join(" / "), end: markers.end.join(" / ") })}
      width={620}
      testId="oped-dialog"
    >
      <Callout>{t("oped.note")}</Callout>
      <div className={s.opedBar}>
        <Button variant="secondary" onPress={() => void identify()} isDisabled={!src?.subtitle_path || busy} data-testid="oped-identify">
          {t("oped.identify")}
        </Button>
        <span className={s.muted}>{src?.subtitle_path ? t("oped.identifyHint") : t("oped.noSubtitle")}</span>
      </div>
      {result?.errors.length ? (
        <Callout tone="warn" testId="oped-errors">
          <div>{t("oped.errorsHead")}</div>
          <ul className={s.errList}>
            {result.errors.map((e, i) => (
              <li key={i}>{t(`oped.error.${e.code}`, { refs: e.refs.join(t("settings.subtitle.speakerSep")), count: e.count ?? 0 })}</li>
            ))}
          </ul>
        </Callout>
      ) : null}
      {pending.length ? (
        <div className={s.opedList} data-testid="oped-pending">
          {pending.map((p) => (
            <div key={p.i} className={s.opedRow}>
              <Segmented<Kind>
                size="sm"
                value={kinds[p.i] ?? p.suggest}
                onChange={(k) => setKinds((x) => ({ ...x, [p.i]: k }))}
                label={t("oped.kind")}
                options={[
                  { id: "OP", label: "OP" },
                  { id: "ED", label: "ED" },
                ]}
              />
              <span className="num">{`${seconds(p.start)}–${seconds(p.end)} s`}</span>
              <span className={s.muted}>{t("oped.refs", { refs: p.refs.join(" → ") })}</span>
              <span className={s.grow} />
              {p.taken ? (
                <span className={s.muted}>{t("oped.taken")}</span>
              ) : (
                <Button size="sm" variant="primary" onPress={() => void add(kinds[p.i] ?? p.suggest, p.start, p.end, "confirm", p.refs)}>
                  {t("oped.confirm")}
                </Button>
              )}
            </div>
          ))}
        </div>
      ) : null}
      <div className={s.opedList} data-testid="oped-list">
        {rows.length ? (
          rows.map((o) => (
            <div key={o.id} className={s.opedRow} data-testid="oped-row">
              <b>{o.kind}</b>
              <span className="num">{`${seconds(o.start)}–${seconds(o.end)} s`}</span>
              <span className={s.grow} />
              <span className={s.opedVia} data-via={o.via}>
                {t(`oped.via.${o.via}`)}
              </span>
              <Button size="sm" variant="flat" onPress={() => void remove(o)}>
                {t("oped.delete")}
              </Button>
            </div>
          ))
        ) : (
          <div className={s.muted}>{t("oped.empty")}</div>
        )}
      </div>
      <div className={s.opedBar} data-testid="oped-mark">
        <span className={s.groupLabel}>{t("oped.manual")}</span>
        <TimeField value={mStart} onCommit={(v) => (v >= 0 && v < duration ? (setMStart(v), true) : false)} label={t("oped.markStart")} testId="oped-start" />
        <Segmented<Kind>
          size="sm"
          value={mKind}
          onChange={setMKind}
          label={t("oped.kind")}
          options={[
            { id: "OP", label: "OP" },
            { id: "ED", label: "ED" },
          ]}
        />
        <NumberField value={mLen} onChange={setMLen} minValue={1} maxValue={600} step={1} label={t("oped.markLength")} />
        <span className={s.muted}>{mEnd != null ? t("oped.until", { end: clock(mEnd) }) : t("oped.seconds")}</span>
        <span className={s.grow} />
        <Button
          size="sm"
          variant="flat"
          isDisabled={mStart == null || !props.canPreview}
          onPress={() => {
            if (mStart == null) return;
            window.otto.player.seek(mStart);
            window.otto.player.play();
          }}
        >
          {t("oped.preview")}
        </Button>
        <Button size="sm" variant="primary" isDisabled={!mValid} onPress={() => void (mStart != null && add(mKind, mStart, mStart + mLen, "mark"))} data-testid="oped-add">
          {t("oped.mark")}
        </Button>
      </div>
      {src ? <div className={s.muted}>{t("oped.sourceIs", { name: displayTitle(src), duration: clock(duration) })}</div> : null}
    </DialogBox>
  );
}
