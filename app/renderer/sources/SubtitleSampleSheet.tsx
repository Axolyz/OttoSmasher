// 从字幕导入台词语音 / 音效采样（全屏工作台；规格 06 §6.4、03 §3.4 表格；原型 subSampleSheet）：
// 缺默认轨时就地选择（同一个工作台里，不开第二层、不回退混音；选没有该角色的整轨 = 同时赋予角色并设为默认，一次可撤销）
// → 大数字（待创建 / OP/ED 排除 / 无有效名称 / 轨道范围外）→ 起止秒 +「预览范围」→ 表格（默认一项都不勾，表头跨页全选）→「创建 N 项」。
import { useCallback, useEffect, useMemo, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SourceDetail, SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { Callout, EmptyState, Stats } from "../components/Controls";
import { Select, TimeField } from "../components/Fields";
import { Sheet } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { seconds } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { displayTitle } from "./SourceList";
import s from "./Sources.module.css";
import { type Tracks, trackName } from "./TracksDialog";

type Kind = "line" | "sfx";
const ROLE: Record<Kind, "vocal" | "sfx"> = { line: "vocal", sfx: "sfx" };
interface Line {
  annotationId: string;
  name: string;
  rawText: string;
  speakers: string[];
  start: number;
  end: number;
  sampleStart: number;
  sampleEnd: number;
  status: "pending" | "oped" | "out-of-track" | "no-name";
}
interface Preview {
  trackId: string | null;
  missingDefault: boolean;
  noSubtitles: boolean;
  pads: [number, number];
  token: string;
  lines: Line[];
  counts: Record<Line["status"], number>;
}

export function SubtitleSampleSheet(props: { source: SourceRow | null; kind: Kind; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const src = props.source;
  const [pv, setPv] = useState<Preview | null>(null);
  const [tracks, setTracks] = useState<Tracks | null>(null);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [range, setRange] = useState<{ a: number | null; b: number | null }>({ a: null, b: null });
  const [busy, setBusy] = useState(false);
  const role = ROLE[props.kind];

  const load = useCallback(
    async (r = range) => {
      if (!src) return;
      const [p, tr, d] = await Promise.all([
        call<Preview>("subtitleSamples.preview", { sourceId: src.id, kind: props.kind, start: r.a ?? undefined, end: r.b ?? undefined }),
        call<Tracks>("assets.tracks", { sourceId: src.id }),
        call<SourceDetail>("sources.get", { id: src.id }),
      ]);
      setPv(p);
      setTracks(tr);
      setDetail(d);
      setChecked(new Set()); // 默认一项都不勾（规格 06 §6.4）
    },
    [src, props.kind, range],
  );
  useEffect(() => {
    setFrom(null);
    setTo(null);
    setRange({ a: null, b: null });
    if (src) void load({ a: null, b: null });
    else setPv(null);
  }, [src?.id, props.kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const track = tracks?.tracks.find((x) => x.id === pv?.trackId) ?? null;
  const rows = useMemo(() => (pv?.lines ?? []).map((l) => ({ ...l, id: l.annotationId })), [pv]);
  const n = rows.filter((l) => checked.has(l.id) && l.status === "pending").length;

  // 就地指定默认轨：没有该角色的整轨 = 同时赋予角色并设为默认（一次编辑，可撤销）
  const pickTrack = async (assetId: string) => {
    if (!src || !tracks) return;
    const tr = tracks.tracks.find((x) => x.id === assetId);
    if (!tr) return;
    const ops: unknown[] = [];
    if (!tr.roles.includes(role)) ops.push({ entity: "asset", id: tr.id, version: tr.version, fields: { roles: [...tr.roles, role] } });
    ops.push({ entity: "source", id: src.id, version: tracks.sourceVersion, fields: { [`default_${role}`]: tr.id } });
    try {
      await call("edits.apply", { batch: { label: { code: "tracks", args: {} }, ops } });
      toast({ text: t("tracks.defaultSet", { role: t(`role.${role}`), track: trackName(tr, detail) }) });
      await load();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };

  const run = async () => {
    if (!src || !pv || busy) return;
    setBusy(true);
    try {
      const ids = rows.filter((l) => checked.has(l.id) && l.status === "pending").map((l) => l.id);
      const r = await call<{ created: number }>("subtitleSamples.create", {
        sourceId: src.id,
        kind: props.kind,
        token: pv.token,
        annotationIds: ids,
        start: range.a ?? undefined,
        end: range.b ?? undefined,
      });
      toast({ text: t("subsample.done", { n: r.created }) });
      props.onClose();
    } catch (e) {
      if (e instanceof CoreFailure && e.wire.code === "subtitle-sample-stale") {
        toast({ text: t("subsample.stale"), tone: "error" });
        await load();
      } else toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const title = t(props.kind === "line" ? "subsample.titleLine" : "subsample.titleSfx");
  return (
    <Sheet
      isOpen={src != null}
      onClose={props.onClose}
      title={title}
      sub={src ? displayTitle(src) : undefined}
      testId="subtitle-samples"
      footer={
        <>
          <span className={s.sheetNote}>
            {pv && track
              ? t(props.kind === "line" ? "subsample.noteLine" : "subsample.noteSfx", { a: pv.pads[0], b: pv.pads[1], track: trackName(track, detail) })
              : t("subsample.noteNoTrack")}
          </span>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!n || busy || !pv || pv.missingDefault} onPress={() => void run()} data-testid="subsample-run">
            {t("subsample.run", { n })}
          </Button>
        </>
      }
    >
      <div className={s.sheetMain}>
        {pv?.missingDefault && tracks ? (
          <Callout tone="warn" testId="subsample-missing">
            <div className={s.sheetBar}>
              <span>{t(`subsample.missing.${role}`)}</span>
              <Select
                value=""
                onChange={(v) => v && void pickTrack(v)}
                label={t(`tracks.default.${role}`)}
                options={[
                  { id: "", label: t("subsample.pickTrack") },
                  ...tracks.tracks.map((tr) => ({
                    id: tr.id,
                    label: tr.roles.includes(role) ? trackName(tr, detail) : t("subsample.withRole", { track: trackName(tr, detail), role: t(`role.${role}`) }),
                  })),
                ]}
              />
            </div>
          </Callout>
        ) : null}
        {pv?.noSubtitles ? (
          <EmptyState title={t("subsample.noSubtitles")} body={t("subsample.noSubtitlesBody")} />
        ) : pv ? (
          <>
            <Stats
              items={[
                { n: pv.counts.pending, label: t("subsample.stat.pending"), testId: "stat-pending" },
                { n: pv.counts.oped, label: t("subsample.stat.oped"), tone: "warn", testId: "stat-oped" },
                { n: pv.counts["no-name"] + pv.counts["out-of-track"], label: t("subsample.stat.other"), tone: "muted", testId: "stat-other" },
              ]}
            />
            <div className={s.sheetBar}>
              <span className={s.groupLabel}>{t("subimport.range")}</span>
              <TimeField value={from} onCommit={(v) => (setFrom(v), true)} label={t("subimport.rangeFrom")} />
              <span className={s.arrow}>→</span>
              <TimeField value={to} onCommit={(v) => (setTo(v), true)} label={t("subimport.rangeTo")} />
              <Button
                size="sm"
                variant="flat"
                isDisabled={from === range.a && to === range.b}
                onPress={() => {
                  const r = { a: from, b: to };
                  setRange(r);
                  void load(r);
                }}
              >
                {t("subsample.previewRange")}
              </Button>
            </div>
            <div className={s.sheetTable}>
              <PagedTable
                label={title}
                rows={rows}
                checked={checked}
                onChecked={setChecked}
                isSelectable={(l) => l.status === "pending"}
                checkLabel={(l) => t("subsample.check", { name: l.name })}
                pageSize={200}
                testId="subsample-table"
                columns={[
                  { id: "name", label: t("subsample.col.name"), isRowHeader: true, render: (l) => <span lang="ja">{l.name || t("subsample.noName")}</span> },
                  {
                    id: "range",
                    label: t("subsample.col.range", { a: pv.pads[0], b: pv.pads[1] }),
                    width: "150px",
                    render: (l) => <span className="num">{`${seconds(l.sampleStart)}–${seconds(l.sampleEnd)}`}</span>,
                  },
                  ...(props.kind === "line"
                    ? [{ id: "who", label: t("subsample.col.speakers"), render: (l: Line) => <span lang="ja">{l.speakers.join(t("settings.subtitle.speakerSep"))}</span> }]
                    : []),
                  { id: "status", label: t("subimport.col.status"), width: "130px", render: (l) => <span className={s.lineStatus} data-status={l.status === "pending" ? "importable" : l.status === "oped" ? "oped" : "registered"}>{t(`subsample.status.${l.status}`)}</span> },
                ]}
              />
            </div>
          </>
        ) : null}
      </div>
    </Sheet>
  );
}
