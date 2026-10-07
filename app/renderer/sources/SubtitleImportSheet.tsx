// 导入字幕标记（全屏工作台，UI_PLAN §5、§8；规格 06 §6.1；原型 subImportSheet）。
// 单个原片：大数字（可导入 / OP/ED 区间 / 无效范围 / 已登记）→ 时间范围过滤与版本说明 → 逐行表格（默认勾选可导入与 OP/ED 区间内的行）
// → 「导入 N 条标记」。只保存标记，不建采样；预览后字幕、音轨、OP/ED 或规则变了 → Core 拒绝并要求重新预览（这里自动重新预览并提示）。
// 多个原片：每个原片一行摘要，没关联字幕的跳过并说明；各自按默认勾选导入，一个失败不影响其他。
import { FileText } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SourceRow, SubtitleBatchRow, SubtitleImportResult, SubtitlePreview, SubtitlePreviewLine } from "../api/types";
import { Button } from "../components/Button";
import { EmptyState, Stats } from "../components/Controls";
import { TimeField } from "../components/Fields";
import { Sheet } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { basename, seconds } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { displayTitle } from "./SourceList";
import s from "./Sources.module.css";

const DEFAULT_ON = new Set(["importable", "oped"]);
const keyOf = (n: number) => String(n);

function statusText(ln: SubtitlePreviewLine): string {
  if (ln.status === "invalid") return t(`subimport.reason.${ln.reason}`);
  if (ln.status === "oped") return t(ln.opedPartial ? "subimport.status.opedPartial" : "subimport.status.oped", { kind: ln.oped ?? "" });
  return t(`subimport.status.${ln.status}`);
}

function classText(ln: SubtitlePreviewLine): string {
  const kind = t(`subtitle.kind.${ln.kind}`);
  return ln.speakers.length ? t("subimport.classWithSpeakers", { kind, speakers: ln.speakers.join(t("settings.subtitle.speakerSep")) }) : kind;
}

export function SubtitleImportSheet(props: { source: SourceRow | null; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const [pv, setPv] = useState<SubtitlePreview | null>(null);
  const [path, setPath] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const open = props.source != null;

  const load = useCallback(
    async (p?: string) => {
      if (!props.source) return null;
      setError(null);
      try {
        const r = await call<SubtitlePreview>("subtitles.preview", { sourceId: props.source.id, path: p });
        setPv(r);
        setChecked(new Set(r.lines.filter((l) => DEFAULT_ON.has(l.status)).map((l) => keyOf(l.no))));
        return r;
      } catch (e) {
        setPv(null);
        setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
        return null;
      }
    },
    [props.source],
  );

  useEffect(() => {
    setPath(undefined);
    setFrom(null);
    setTo(null);
    if (open) void load();
  }, [open, props.source?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(
    () => (pv?.lines ?? []).filter((l) => (from == null || l.end > from) && (to == null || l.start < to)).map((l) => ({ ...l, id: keyOf(l.no) })),
    [pv, from, to],
  );
  const n = pv ? pv.lines.filter((l) => checked.has(keyOf(l.no)) && DEFAULT_ON.has(l.status)).length : 0;
  const switchOnly = pv != null && n === 0 && pv.versionState === "switch";

  const pick = async () => {
    const [p] = await window.otto.files.pick("subtitle");
    if (!p) return;
    setPath(p);
    void load(p);
  };

  const run = async () => {
    if (!pv || !props.source || busy) return;
    setBusy(true);
    try {
      const lines = pv.lines.filter((l) => checked.has(keyOf(l.no)) && DEFAULT_ON.has(l.status)).map((l) => l.no);
      const r = await call<SubtitleImportResult>("subtitles.import", { sourceId: props.source.id, token: pv.token, lines, path });
      toast({
        text: t(r.switched && !r.imported ? "subimport.doneSwitched" : r.newVersion ? "subimport.doneNewVersion" : "subimport.done", {
          n: r.imported,
          invalid: r.skipped.invalid,
        }),
        action: r.editId ? { label: t("common.undo"), run: () => void undo() } : undefined,
      });
      props.onDone();
      props.onClose();
    } catch (e) {
      if (e instanceof CoreFailure && e.wire.code === "subtitle-preview-stale") {
        toast({ text: t("subimport.stale"), tone: "error" });
        await load(path);
      } else toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const fileName = pv?.fileName ?? (path ? basename(path) : props.source?.subtitle_path ? basename(props.source.subtitle_path) : "");
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
          <Button variant="primary" isDisabled={!pv || busy || (n === 0 && !switchOnly)} onPress={() => void run()} data-testid="subimport-run">
            {switchOnly ? t("subimport.runSwitch") : t("subimport.run", { n })}
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
        ) : pv ? (
          <>
            <Stats
              items={[
                { n: pv.counts.importable, label: t("subimport.stat.importable"), testId: "stat-importable" },
                { n: pv.counts.oped, label: t("subimport.stat.oped"), tone: "warn", testId: "stat-oped" },
                { n: pv.counts.invalid, label: t("subimport.stat.invalid"), tone: "bad", testId: "stat-invalid" },
                ...(pv.counts.registered ? [{ n: pv.counts.registered, label: t("subimport.stat.registered"), tone: "muted" as const, testId: "stat-registered" }] : []),
              ]}
            />
            <div className={s.sheetBar}>
              <span className={s.groupLabel}>{t("subimport.range")}</span>
              <TimeField value={from} onCommit={(v) => (setFrom(v), true)} label={t("subimport.rangeFrom")} />
              <span className={s.arrow}>→</span>
              <TimeField value={to} onCommit={(v) => (setTo(v), true)} label={t("subimport.rangeTo")} />
              {from != null || to != null ? (
                <Button size="sm" variant="flat" onPress={() => (setFrom(null), setTo(null))}>
                  {t("subimport.rangeClear")}
                </Button>
              ) : null}
              <span className={s.grow} />
              <span className={s.versionNote} data-testid="subimport-version">
                {t(`subimport.version.${pv.versionState}`)}
              </span>
            </div>
            {pv.problems.length ? (
              <div className={s.warn}>{t("subimport.problems", { n: pv.problems.length, lines: pv.problems.slice(0, 5).map((p) => p.line).join(", ") })}</div>
            ) : null}
            <div className={s.sheetTable}>
              <PagedTable
                label={t("subimport.title")}
                rows={shown}
                checked={checked}
                onChecked={setChecked}
                isSelectable={(l) => DEFAULT_ON.has(l.status)}
                checkLabel={(l) => t("subimport.checkLine", { n: l.no })}
                pageSize={200}
                testId="subimport-table"
                columns={[
                  { id: "no", label: "#", width: "52px", render: (l) => <span className="num">{l.ref || l.no}</span> },
                  { id: "text", label: t("subimport.col.text"), isRowHeader: true, render: (l) => <span className={s.cueText} lang="ja">{l.text}</span> },
                  { id: "range", label: t("subimport.col.range"), width: "130px", render: (l) => <span className="num">{`${seconds(l.start)}–${seconds(l.end)}`}</span> },
                  { id: "class", label: t("subimport.col.class"), render: (l) => <span lang="ja">{classText(l)}</span> },
                  { id: "status", label: t("subimport.col.status"), width: "170px", render: (l) => <span className={s.lineStatus} data-status={l.status}>{statusText(l)}</span> },
                ]}
              />
            </div>
          </>
        ) : null}
      </div>
    </Sheet>
  );
}

export function SubtitleBatchSheet(props: { sources: SourceRow[]; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const [rows, setRows] = useState<SubtitleBatchRow[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const open = props.sources.length > 0;
  const byId = useMemo(() => new Map(props.sources.map((r) => [r.id, r])), [props.sources]);
  const ok = (r: SubtitleBatchRow): r is Extract<SubtitleBatchRow, { token: string }> => "token" in r;
  const usable = (r: SubtitleBatchRow) => ok(r) && (r.counts.importable + r.counts.oped > 0 || r.versionState === "switch");

  useEffect(() => {
    if (!open) return setRows(null);
    void call<SubtitleBatchRow[]>("subtitles.previewMany", { sourceIds: props.sources.map((r) => r.id) }).then((r) => {
      setRows(r);
      setChecked(new Set(r.filter(usable).map((x) => x.sourceId)));
    });
  }, [open, props.sources]); // eslint-disable-line react-hooks/exhaustive-deps

  const run = async () => {
    if (!rows || busy) return;
    setBusy(true);
    try {
      const items = rows.filter((r) => ok(r) && checked.has(r.sourceId)).map((r) => ({ sourceId: r.sourceId, token: (r as { token: string }).token }));
      const res = await call<Array<SubtitleImportResult | { sourceId: string; error: { code: string; args: Record<string, unknown> } }>>("subtitles.importMany", { items });
      const failed = res.filter((r) => "error" in r);
      const total = res.reduce((a, r) => a + ("imported" in r ? r.imported : 0), 0);
      toast({ text: t("subimport.batchDone", { n: res.length - failed.length, lines: total, failed: failed.length }), tone: failed.length ? "error" : "info" });
      for (const f of failed) if ("error" in f) toast({ text: t("subimport.batchFailedOne", { name: displayTitle(byId.get(f.sourceId)!), error: errorText(f.error) }), tone: "error" });
      props.onDone();
      props.onClose();
    } finally {
      setBusy(false);
    }
  };

  const n = rows ? rows.filter((r) => checked.has(r.sourceId) && usable(r)).length : 0;
  const tableRows = (rows ?? []).map((r) => ({ ...r, id: r.sourceId }));
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
                render: (r) => (ok(r) ? <span data-user-data="">{r.fileName}</span> : "skipped" in r ? <span className={s.muted}>{t("subimport.skipped.noSubtitle")}</span> : <span className={s.warn}>{errorText(r.error)}</span>),
              },
              { id: "imp", label: t("subimport.stat.importableShort"), align: "end", render: (r) => (ok(r) ? <span className="num">{r.counts.importable}</span> : "") },
              { id: "oped", label: t("subimport.stat.opedShort"), align: "end", render: (r) => (ok(r) ? <span className="num">{r.counts.oped}</span> : "") },
              { id: "inv", label: t("subimport.stat.invalidShort"), align: "end", render: (r) => (ok(r) ? <span className="num">{r.counts.invalid}</span> : "") },
              { id: "reg", label: t("subimport.stat.registeredShort"), align: "end", render: (r) => (ok(r) ? <span className="num">{r.counts.registered}</span> : "") },
              { id: "ver", label: t("subimport.col.version"), render: (r) => (ok(r) ? t(`subimport.versionShort.${r.versionState}`) : "") },
            ]}
          />
        </div>
      </div>
    </Sheet>
  );
}
