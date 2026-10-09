// 导入到文本层（全屏工作台；所有者 2026-10-09「原片上的四类对象」B 节，UI_PLAN §5、§8，原型 subImportSheet）。
// 一次显式操作，四类一起进：台词行 → 文本层的段；音效行 → 音效提示；说话人 → 段的属性；♪～ / ～♪ → OP/ED 区间。不建采样、不触发分析。
// 顶部：四类开关（默认全开）+ 全局选项（替换 / 保留原有，默认替换）+ 汇总（新增 / 无变化 / 替换（其中有分析、需重新分析的）/ 跳过）；
// 下面按类分页的逐行表格：勾选 = 导入这一行（不勾的行不替换任何东西）；跳过的行可以逐行「强制替换」（碰到受保护的段要二次确认，写清会丢掉什么）；
// OP/ED 规则有错时在页内逐对确认用途。任何改动都重新预览（匹配随勾选变化）；整次导入原子提交、可撤销（整批撤销）。
// 多个原片：每个原片一行摘要，按默认选项各自导入，一个失败不影响其他。
import { FileText } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SourceRow, SubtitleBatchRow, SubtitleConflict, SubtitleImportOptions, SubtitlePairRow, SubtitlePreview, SubtitleRow } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, EmptyState, Segmented, Stats } from "../components/Controls";
import { Select, TimeField } from "../components/Fields";
import { ConfirmDialog, Sheet } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { basename, clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { displayTitle } from "./SourceList";
import s from "./Sources.module.css";

type Tab = "segments" | "hints" | "oped";
type Kind = "OP" | "ED";
interface Opts {
  segments: boolean;
  hints: boolean;
  speakers: boolean;
  oped: boolean;
  replace: boolean;
  exclude: ReadonlySet<number>;
  force: ReadonlySet<number>;
  opedForce: ReadonlySet<number>;
  opedConfirm: ReadonlyMap<number, Kind>;
}
const DEFAULTS: Opts = { segments: true, hints: true, speakers: true, oped: true, replace: true, exclude: new Set(), force: new Set(), opedForce: new Set(), opedConfirm: new Map() };
const CATS = ["segments", "hints", "speakers", "oped"] as const;

const wire = (o: Opts): SubtitleImportOptions => ({
  segments: o.segments,
  hints: o.hints,
  speakers: o.speakers,
  oped: o.oped,
  replace: o.replace,
  exclude: [...o.exclude],
  force: [...o.force],
  opedForce: [...o.opedForce],
  opedConfirm: [...o.opedConfirm].map(([index, kind]) => ({ index, kind })),
});
const toggled = <T,>(x: ReadonlySet<T>, v: T, on: boolean) => {
  const n = new Set(x);
  if (on) n.add(v);
  else n.delete(v);
  return n;
};

type Line = SubtitleRow & { id: string };
type Pair = SubtitlePairRow & { id: string };

function statusText(r: SubtitleRow | SubtitlePairRow): string {
  const n = r.conflicts.length;
  if (r.status === "invalid") return t(`subimport.reason.${r.reason}`);
  if (r.status === "excluded") return t(`subimport.excluded.${r.reason}`);
  if (r.status === "skip") return t(`subimport.skip.${r.reason}`, { n });
  if (r.status === "replace") return t(r.forced ? "subimport.status.forced" : "subimport.status.replace", { n });
  return t(`subimport.status.${r.status}`);
}

/** 碰到的已有对象：时间、文字、受保护标记（✎ 改过 / ◆ 有人工音素版本）、使用数 */
function Conflicts(props: { list: SubtitleConflict[] }) {
  if (!props.list.length) return null;
  return (
    <ul className={s.conflictList}>
      {props.list.slice(0, 3).map((c) => (
        <li key={c.id}>
          <span className="num">{clock(c.start, 1)}</span> <span lang="ja" data-user-data="">{c.text.replace(/\n/g, " ")}</span>
          {c.edited ? " ✎" : ""}
          {c.manual ? " ◆" : ""}
          {c.usedBy ? ` · ${t("seg.usedByShort", { n: c.usedBy })}` : ""}
        </li>
      ))}
      {props.list.length > 3 ? <li className={s.muted}>{t("subimport.moreConflicts", { n: props.list.length - 3 })}</li> : null}
    </ul>
  );
}

export function SubtitleImportSheet(props: { source: SourceRow | null; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const [pv, setPv] = useState<SubtitlePreview | null>(null);
  const [path, setPath] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [opts, setOpts] = useState<Opts>(DEFAULTS);
  const [tab, setTab] = useState<Tab>("segments");
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{ kind: "line"; row: SubtitleRow } | { kind: "pair"; row: SubtitlePairRow } | null>(null);
  const seq = useRef(0);
  const open = props.source != null;

  const load = useCallback(
    async (p: string | undefined, o: Opts) => {
      if (!props.source) return null;
      const my = ++seq.current;
      setError(null);
      try {
        const r = await call("subtitles.preview", { sourceId: props.source.id, path: p ?? null, options: wire(o) });
        if (my === seq.current) setPv(r);
        return r;
      } catch (e) {
        if (my !== seq.current) return null;
        setPv(null);
        setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
        return null;
      }
    },
    [props.source],
  );
  const change = (o: Opts) => {
    setOpts(o);
    void load(path, o);
  };

  useEffect(() => {
    setPath(undefined);
    setFrom(null);
    setTo(null);
    setTab("segments");
    setOpts(DEFAULTS);
    setPv(null);
    if (open) void load(undefined, DEFAULTS);
  }, [open, props.source?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = async () => {
    const [p] = await window.otto.files.pick("subtitle");
    if (!p) return;
    setPath(p);
    // 换文件：逐行的勾选与强制按行号记，不能沿用
    const o = { ...opts, exclude: new Set<number>(), force: new Set<number>(), opedForce: new Set<number>(), opedConfirm: new Map<number, Kind>() };
    setOpts(o);
    void load(p, o);
  };

  const inRange = (r: { start: number; end: number }) => (from == null || r.end > from) && (to == null || r.start < to);
  const lines = useMemo<Line[]>(() => (tab === "oped" || !pv ? [] : pv[tab].filter(inRange).map((r) => ({ ...r, id: String(r.no) }))), [pv, tab, from, to]); // eslint-disable-line react-hooks/exhaustive-deps
  const pairs = useMemo<Pair[]>(() => (pv?.oped.pairs ?? []).map((r) => ({ ...r, id: String(r.index) })), [pv]);
  const selectable = (r: SubtitleRow) => r.status !== "invalid" && r.reason !== "category-off";
  const checked = useMemo(() => new Set(lines.filter((r) => selectable(r) && r.status !== "excluded").map((r) => r.id)), [lines]);
  const onChecked = (next: Set<string>) => {
    const ex = new Set(opts.exclude);
    for (const r of lines) {
      if (!selectable(r)) continue;
      if (next.has(r.id)) ex.delete(r.no);
      else ex.add(r.no);
    }
    change({ ...opts, exclude: ex });
  };
  const forceLine = (r: SubtitleRow, on: boolean) => {
    if (on && r.reason === "protected") return setConfirm({ kind: "line", row: r });
    change({ ...opts, force: toggled(opts.force, r.no, on) });
  };
  const forcePair = (r: SubtitlePairRow, on: boolean) => {
    if (on && r.reason === "protected") return setConfirm({ kind: "pair", row: r });
    change({ ...opts, opedForce: toggled(opts.opedForce, r.index, on) });
  };

  const c = pv?.counts;
  const sum = (k: "new" | "unchanged" | "replace" | "skip" | "excluded" | "invalid" | "removed" | "removedProtected") =>
    c ? c.segments[k] + c.hints[k] + c.oped[k] : 0;
  const n = sum("new") + sum("replace");
  const opedErrors = pv?.oped.errors ?? [];

  const run = async () => {
    if (!pv || !props.source || busy) return;
    setBusy(true);
    try {
      const r = await call("subtitles.import", { sourceId: props.source.id, token: pv.token, options: wire(opts), path: path ?? null });
      const removed = r.counts.segments.removed + r.counts.hints.removed + r.counts.oped.removed;
      const skipped = r.counts.segments.skip + r.counts.hints.skip + r.counts.oped.skip;
      toast({
        text: t("subimport.done", { segments: r.created.segments, hints: r.created.hints, oped: r.created.oped, removed, skipped }),
        action: r.editId ? { label: t("common.undo"), run: () => void undo() } : undefined,
      });
      props.onDone();
      props.onClose();
    } catch (e) {
      if (e instanceof CoreFailure && e.wire.code === "subtitle-preview-stale") {
        toast({ text: t("subimport.stale"), tone: "error" });
        await load(path, opts);
      } else toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const fileName = pv?.fileName ?? (path ? basename(path) : props.source?.subtitle_path ? basename(props.source.subtitle_path) : "");
  const statusCell = (r: Line | Pair, force: (on: boolean) => void) => (
    <div className={s.statusCell}>
      <span className={s.lineStatus} data-status={r.status} data-testid="subimport-status">
        {statusText(r)}
      </span>
      {r.status === "skip" ? (
        <Button size="sm" variant="flat" onPress={() => force(true)} data-testid="subimport-force">
          {t("subimport.force")}
        </Button>
      ) : r.status === "replace" && r.forced ? (
        <Button size="sm" variant="flat" onPress={() => force(false)} data-testid="subimport-unforce">
          {t("subimport.unforce")}
        </Button>
      ) : null}
      {r.status === "replace" || r.status === "skip" ? <Conflicts list={r.conflicts} /> : null}
    </div>
  );
  const lost = confirm ? confirm.row.conflicts.filter((x) => x.protected) : [];

  return (
    <Sheet
      isOpen={open}
      onClose={props.onClose}
      title={t("subimport.title")}
      sub={props.source ? `${displayTitle(props.source)} · ${fileName || t("subimport.noFile")}` : undefined}
      testId="subtitle-import"
      actions={
        <Button variant="flat" icon={<FileText />} onPress={() => void pick()} data-testid="subimport-pick">
          {t("subimport.pick")}
        </Button>
      }
      footer={
        <>
          <span className={s.sheetNote}>{t("subimport.note")}</span>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!pv || busy || (n === 0 && sum("removed") === 0)} onPress={() => void run()} data-testid="subimport-run">
            {t("subimport.run", { n })}
          </Button>
        </>
      }
    >
      <div className={s.sheetMain}>
        {error ? (
          <EmptyState
            icon={<FileText />}
            title={t("subimport.cannotRead")}
            body={error}
            actions={
              <Button variant="primary" onPress={() => void pick()}>
                {t("subimport.pick")}
              </Button>
            }
          />
        ) : pv && c ? (
          <>
            <div className={s.sheetBar} data-testid="subimport-options">
              <span className={s.groupLabel}>{t("subimport.cats")}</span>
              {CATS.map((k) => (
                <Checkbox key={k} isSelected={opts[k]} onChange={(on) => change({ ...opts, [k]: on })} label={t(`subimport.cat.${k}`)} testId={`subimport-cat-${k}`}>
                  {t(`subimport.cat.${k}`)}
                </Checkbox>
              ))}
              <span className={s.grow} />
              <span className={s.groupLabel}>{t("subimport.overlap")}</span>
              <Segmented<"replace" | "keep">
                size="sm"
                label={t("subimport.overlap")}
                value={opts.replace ? "replace" : "keep"}
                onChange={(v) => change({ ...opts, replace: v === "replace" })}
                options={[
                  { id: "replace", label: t("subimport.overlap.replace") },
                  { id: "keep", label: t("subimport.overlap.keep") },
                ]}
                testId="subimport-overlap"
              />
            </div>
            <Stats
              items={[
                { n: sum("new"), label: t("subimport.stat.new"), testId: "stat-new" },
                { n: sum("unchanged"), label: t("subimport.stat.unchanged"), tone: "muted", testId: "stat-unchanged" },
                {
                  n: sum("replace"),
                  label: t("subimport.stat.replace", { removed: sum("removed"), analyzed: c.segments.removedAnalyzed }),
                  tone: "warn",
                  testId: "stat-replace",
                },
                { n: sum("skip"), label: t("subimport.stat.skip"), tone: "bad", testId: "stat-skip" },
              ]}
            />
            {sum("removedProtected") ? <Callout tone="warn">{t("subimport.removedProtected", { n: sum("removedProtected") })}</Callout> : null}
            {sum("invalid") || pv.problems.length ? (
              <div className={s.warn}>
                {[
                  sum("invalid") ? t("subimport.invalidN", { n: sum("invalid") }) : "",
                  pv.problems.length ? t("subimport.problems", { n: pv.problems.length, lines: pv.problems.slice(0, 5).map((p) => p.line).join(", ") }) : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            ) : null}
            <div className={s.sheetBar}>
              <Segmented<Tab>
                size="sm"
                label={t("subimport.tabs")}
                value={tab}
                onChange={setTab}
                options={[
                  { id: "segments", label: t("subimport.tab.segments", { n: pv.segments.length }) },
                  { id: "hints", label: t("subimport.tab.hints", { n: pv.hints.length }) },
                  { id: "oped", label: t("subimport.tab.oped", { n: pairs.length }) },
                ]}
                testId="subimport-tab"
              />
              {tab !== "oped" ? (
                <>
                  <span className={s.groupLabel}>{t("subimport.range")}</span>
                  <TimeField value={from} onCommit={(v) => (setFrom(v), true)} label={t("subimport.rangeFrom")} />
                  <span className={s.arrow}>→</span>
                  <TimeField value={to} onCommit={(v) => (setTo(v), true)} label={t("subimport.rangeTo")} />
                  {from != null || to != null ? (
                    <Button size="sm" variant="flat" onPress={() => (setFrom(null), setTo(null))}>
                      {t("subimport.rangeClear")}
                    </Button>
                  ) : null}
                </>
              ) : null}
            </div>
            {tab === "segments" && pv.speakers.length ? (
              <div className={s.muted} data-testid="subimport-speakers">
                {opts.speakers
                  ? t("subimport.speakers", { list: pv.speakers.slice(0, 8).map((x) => `${x.name} ×${x.count}`).join(t("settings.subtitle.speakerSep")) })
                  : t("subimport.speakersOff")}
              </div>
            ) : null}
            {tab === "oped" && opedErrors.length ? (
              <Callout tone="warn" testId="subimport-oped-errors">
                <div>{t("subimport.opedErrorsHead")}</div>
                <ul>
                  {opedErrors.map((e, i) => {
                    const er = e as { code: string; refs?: string[]; count?: number };
                    return <li key={i}>{t(`oped.error.${er.code}`, { refs: (er.refs ?? []).join(t("settings.subtitle.speakerSep")), count: er.count ?? 0 })}</li>;
                  })}
                </ul>
              </Callout>
            ) : null}
            <div className={s.sheetTable}>
              {tab === "oped" ? (
                <PagedTable<Pair>
                  label={t("subimport.tab.oped", { n: pairs.length })}
                  rows={pairs}
                  pageSize={50}
                  testId="subimport-oped-table"
                  empty={<span className={s.muted}>{t("subimport.noPairs")}</span>}
                  columns={[
                    { id: "no", label: "#", width: "48px", render: (r) => <span className="num">{r.index + 1}</span> },
                    {
                      id: "kind",
                      label: t("subimport.col.kind"),
                      width: "150px",
                      isRowHeader: true,
                      render: (r) =>
                        opedErrors.length ? (
                          <Select
                            value={opts.opedConfirm.get(r.index) ?? ""}
                            onChange={(v) => {
                              const m = new Map(opts.opedConfirm);
                              if (v === "OP" || v === "ED") m.set(r.index, v);
                              else m.delete(r.index);
                              change({ ...opts, opedConfirm: m });
                            }}
                            label={t("subimport.col.kind")}
                            options={[
                              { id: "", label: t("subimport.opedSkip") },
                              { id: "OP", label: t("subimport.opedAs", { kind: "OP", suggest: r.suggest === "OP" ? t("subimport.suggested") : "" }) },
                              { id: "ED", label: t("subimport.opedAs", { kind: "ED", suggest: r.suggest === "ED" ? t("subimport.suggested") : "" }) },
                            ]}
                            testId="subimport-oped-kind"
                          />
                        ) : (
                          <span>{r.kind}</span>
                        ),
                    },
                    { id: "range", label: t("subimport.col.range"), width: "170px", render: (r) => <span className="num">{`${clock(r.start)}–${clock(r.end)}`}</span> },
                    { id: "refs", label: t("subimport.col.refs"), width: "110px", render: (r) => <span className="num">{r.refs.join("–")}</span> },
                    { id: "status", label: t("subimport.col.status"), render: (r) => statusCell(r, (on) => forcePair(r, on)) },
                  ]}
                />
              ) : (
                <PagedTable<Line>
                  label={t(`subimport.tab.${tab}`, { n: lines.length })}
                  rows={lines}
                  checked={checked}
                  onChecked={onChecked}
                  isSelectable={selectable}
                  checkLabel={(r) => t("subimport.checkLine", { n: r.ref || r.no })}
                  pageSize={200}
                  testId="subimport-table"
                  columns={[
                    { id: "no", label: "#", width: "52px", render: (r) => <span className="num">{r.ref || r.no}</span> },
                    {
                      id: "text",
                      label: t(tab === "segments" ? "subimport.col.segText" : "subimport.col.hintText"),
                      isRowHeader: true,
                      render: (r) => (
                        <span className={s.cueText} lang="ja" title={r.raw} data-user-data="">
                          {r.text}
                        </span>
                      ),
                    },
                    { id: "range", label: t("subimport.col.range"), width: "130px", render: (r) => <span className="num">{`${seconds(r.start)}–${seconds(r.end)}`}</span> },
                    ...(tab === "segments"
                      ? [
                          {
                            id: "who",
                            label: t("subimport.col.speakers"),
                            width: "120px",
                            render: (r: Line) => (
                              <span lang="ja" data-user-data="">
                                {opts.speakers ? r.speakers.join(t("settings.subtitle.speakerSep")) : ""}
                              </span>
                            ),
                          },
                        ]
                      : []),
                    { id: "status", label: t("subimport.col.status"), width: "300px", render: (r) => statusCell(r, (on) => forceLine(r, on)) },
                  ]}
                />
              )}
            </div>
          </>
        ) : null}
      </div>
      <ConfirmDialog
        isOpen={confirm != null}
        title={t("subimport.forceTitle")}
        confirmLabel={t("subimport.force")}
        danger
        onConfirm={() => {
          if (!confirm) return;
          if (confirm.kind === "line") change({ ...opts, force: toggled(opts.force, confirm.row.no, true) });
          else change({ ...opts, opedForce: toggled(opts.opedForce, confirm.row.index, true) });
          setConfirm(null);
        }}
        onClose={() => setConfirm(null)}
        testId="subimport-force-confirm"
      >
        <div>{t("subimport.forceBody", { n: lost.length })}</div>
        <ul className={s.impact}>
          {lost.map((x) => (
            <li key={x.id}>
              <span className="num">{`${clock(x.start, 1)}–${clock(x.end, 1)}`}</span> <span lang="ja" data-user-data="">{x.text.replace(/\n/g, " ")}</span>
              {" — "}
              {[x.edited ? t("seg.flag.edited") : "", x.manual ? t("seg.flag.manual") : "", x.usedBy ? t("seg.usedByShort", { n: x.usedBy }) : ""].filter(Boolean).join(" · ")}
            </li>
          ))}
        </ul>
        <div className={s.keep}>{t("subimport.forceKeeps")}</div>
      </ConfirmDialog>
    </Sheet>
  );
}

/** 批量预览里可导入的一行（其余是 skipped 或 error） */
type BatchOk = SubtitleBatchRow & Required<Pick<SubtitleBatchRow, "fileName" | "token" | "counts">>;

export function SubtitleBatchSheet(props: { sources: SourceRow[]; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const [rows, setRows] = useState<SubtitleBatchRow[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const open = props.sources.length > 0;
  const byId = useMemo(() => new Map(props.sources.map((r) => [r.id, r])), [props.sources]);
  const ok = (r: SubtitleBatchRow): r is BatchOk => "token" in r && r.counts != null;
  const total = (r: BatchOk, k: "new" | "unchanged" | "replace" | "skip" | "removed") => r.counts.segments[k] + r.counts.hints[k] + r.counts.oped[k];
  const usable = (r: SubtitleBatchRow) => ok(r) && (total(r, "new") + total(r, "replace") > 0 || total(r, "removed") > 0);

  useEffect(() => {
    if (!open) return setRows(null);
    void call("subtitles.previewMany", { sourceIds: props.sources.map((r) => r.id) }).then((r) => {
      setRows(r);
      setChecked(new Set(r.filter(usable).map((x) => x.sourceId)));
    });
  }, [open, props.sources]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    if (!rows || busy) return;
    setBusy(true);
    try {
      const items = rows.filter((r) => ok(r) && checked.has(r.sourceId)).map((r) => ({ sourceId: r.sourceId, token: r.token! }));
      const res = await call("subtitles.importMany", { items });
      const failed = res.filter((r) => r.error);
      const segs = res.reduce((a, r) => a + (r.created?.segments ?? 0), 0);
      const hints = res.reduce((a, r) => a + (r.created?.hints ?? 0), 0);
      toast({
        text: t("subimport.batchDone", { n: res.length - failed.length, segments: segs, hints, failed: failed.length }),
        tone: failed.length ? "error" : "info",
      });
      for (const f of failed) if (f.error) toast({ text: t("subimport.batchFailedOne", { name: displayTitle(byId.get(f.sourceId)!), error: errorText(f.error) }), tone: "error" });
      props.onDone();
      props.onClose();
    } finally {
      setBusy(false);
    }
  };

  const n = rows ? rows.filter((r) => checked.has(r.sourceId) && usable(r)).length : 0;
  const tableRows = (rows ?? []).map((r) => ({ ...r, id: r.sourceId }));
  const num = (r: SubtitleBatchRow, k: "new" | "unchanged" | "replace" | "skip") => (ok(r) ? <span className="num">{total(r, k)}</span> : "");
  return (
    <Sheet
      isOpen={open}
      onClose={props.onClose}
      title={t("subimport.batchTitle", { n: props.sources.length })}
      testId="subtitle-import-batch"
      footer={
        <>
          <span className={s.sheetNote}>{t("subimport.batchNote")}</span>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!n || busy} onPress={() => void run()} data-testid="subimport-batch-run">
            {t("subimport.batchRun", { n })}
          </Button>
        </>
      }
    >
      <div className={s.sheetMain}>
        <div className={s.sheetTable}>
          <PagedTable
            label={t("subimport.batchTitle", { n: props.sources.length })}
            rows={tableRows}
            checked={checked}
            onChecked={setChecked}
            isSelectable={usable}
            checkLabel={(r) => displayTitle(byId.get(r.sourceId)!)}
            columns={[
              { id: "source", label: t("subimport.col.source"), isRowHeader: true, render: (r) => <span data-user-data="">{displayTitle(byId.get(r.sourceId)!)}</span> },
              {
                id: "file",
                label: t("subimport.col.file"),
                render: (r) =>
                  ok(r) ? (
                    <span data-user-data="">
                      {r.fileName}
                      {r.opedErrors ? <span className={s.warn}>{` · ${t("subimport.batchOpedErrors")}`}</span> : null}
                    </span>
                  ) : r.skipped ? (
                    <span className={s.muted}>{t("subimport.skipped.noSubtitle")}</span>
                  ) : (
                    <span className={s.warn}>{r.error ? errorText(r.error) : ""}</span>
                  ),
              },
              { id: "new", label: t("subimport.stat.newShort"), align: "end", render: (r) => num(r, "new") },
              { id: "same", label: t("subimport.stat.unchangedShort"), align: "end", render: (r) => num(r, "unchanged") },
              { id: "rep", label: t("subimport.stat.replaceShort"), align: "end", render: (r) => num(r, "replace") },
              { id: "skip", label: t("subimport.stat.skipShort"), align: "end", render: (r) => num(r, "skip") },
            ]}
          />
        </div>
      </div>
    </Sheet>
  );
}
