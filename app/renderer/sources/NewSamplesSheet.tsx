// 批量建采样（所有者 2026-10-09：建采样是一个动作——单条用动作条上的小面板，批量用这个整页表格；背后同一个 samples.plan，规则与产物完全相同）。
// 来源：文本层的段（默认人声轨，或当前查看的轨）/ 音效提示（默认音效轨，或当前查看的轨）/ 整段原片。
// 缺默认轨时就地指定（同一个工作台里，不开第二层、不回退混音；选没有该角色的整轨 = 同时赋予角色并设为默认，一次可撤销）
// → 大数字（待创建 / OP/ED 排除 / 其他）→ 起止秒 +「预览范围」→ 表格（段与提示默认一项都不勾，整段默认全勾；表头跨页全选）→「创建 N 项」。
import { useCallback, useEffect, useMemo, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { EditOp, Nature, SamplePlan, SamplePlanItem, SamplePlanSource, SourceDetail } from "../api/types";
import { Button } from "../components/Button";
import { Callout, EmptyState, Segmented, Stats } from "../components/Controls";
import { Select, TimeField } from "../components/Fields";
import { Sheet } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { type NewSamplesRequest, useApp } from "../state/store";
import s from "./Sources.module.css";
import { type Tracks, trackName } from "./TracksDialog";

type Row = SamplePlanItem & { id: string };
const NATURES: Array<Nature | "auto"> = ["auto", "speech", "pitched", "unpitched", "unclassified"];

export function NewSamplesSheet() {
  const req = useApp((st) => st.newSamplesRequest);
  const close = useApp((st) => st.requestNewSamples);
  const toast = useApp((st) => st.toast);
  const setPage = useApp((st) => st.setPage);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const [pv, setPv] = useState<SamplePlan | null>(null);
  const [tracks, setTracks] = useState<Tracks | null>(null);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [track, setTrack] = useState<"default" | "current">("default");
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [range, setRange] = useState<{ a: number | null; b: number | null }>({ a: null, b: null });
  const [nature, setNature] = useState<Nature | "auto">("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const kind = req?.kind ?? null;
  const role = kind === "hints" ? "sfx" : "vocal";

  const source = useCallback(
    (r = range, tr = track): SamplePlanSource | null => {
      if (!req) return null;
      if (req.kind === "whole") return { kind: "whole", sourceIds: req.sourceIds };
      return {
        kind: req.kind,
        sourceId: req.sourceId,
        track: tr,
        assetId: tr === "current" ? (req.currentAsset?.id ?? null) : null,
        start: r.a ?? null,
        end: r.b ?? null,
      };
    },
    [req, range, track],
  );

  const load = useCallback(
    async (r = range, tr = track) => {
      const src = source(r, tr);
      if (!req || !src) return;
      setError(null);
      try {
        const p = await call("samples.plan", { from: src });
        setPv(p);
        // 段与提示默认一项都不勾（规格 06 §6.4）；整段原片默认全勾
        setChecked(new Set(req.kind === "whole" ? p.items.filter((x) => x.status === "pending").map((x) => x.key) : []));
        if (req.kind !== "whole") {
          const [tk, d] = await Promise.all([call("assets.tracks", { sourceId: req.sourceId }), call("sources.get", { id: req.sourceId })]);
          setTracks(tk);
          setDetail(d);
        }
      } catch (e) {
        setPv(null);
        setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
      }
    },
    [req, range, track, source],
  );
  useEffect(() => {
    setFrom(null);
    setTo(null);
    setRange({ a: null, b: null });
    setTrack("default");
    setNature("auto");
    if (req) void load({ a: null, b: null }, "default");
    else setPv(null);
  }, [req]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = useMemo<Row[]>(() => (pv?.items ?? []).map((x) => ({ ...x, id: x.key })), [pv]);
  const n = rows.filter((x) => checked.has(x.id) && x.status === "pending").length;
  const counts = useMemo(() => {
    const c = { pending: 0, oped: 0, other: 0 };
    for (const x of rows) {
      if (x.status === "pending") c.pending += 1;
      else if (x.status === "oped") c.oped += 1;
      else c.other += 1;
    }
    return c;
  }, [rows]);

  // 就地指定默认轨：没有该角色的整轨 = 同时赋予角色并设为默认（一次编辑，可撤销）
  const pickTrack = async (assetId: string) => {
    if (!req || req.kind === "whole" || !tracks) return;
    const tr = tracks.tracks.find((x) => x.id === assetId);
    if (!tr) return;
    const ops: EditOp[] = [];
    if (!tr.roles.includes(role)) ops.push({ entity: "asset", id: tr.id, version: tr.version, fields: { roles: [...tr.roles, role] } });
    ops.push({ entity: "source", id: req.sourceId, version: tracks.sourceVersion, fields: { [`default_${role}`]: tr.id } });
    try {
      await call("edits.apply", { batch: { label: { code: "tracks", args: {} }, ops } });
      toast({ text: t("tracks.defaultSet", { role: t(`role.${role}`), track: trackName(tr, detail) }) });
      await load();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };

  const run = async () => {
    const src = source();
    if (!src || !pv || busy) return;
    setBusy(true);
    try {
      const keys = rows.filter((x) => checked.has(x.id) && x.status === "pending").map((x) => x.key);
      const r = await call("samples.createPlanned", { from: src, token: pv.token, keys, nature: nature === "auto" ? null : nature });
      const first = r.ids[0];
      toast({
        text: t("newsamples.done", { n: r.created }),
        action: first ? { label: t("sources.openInLibrary"), run: () => (setOpenSample(first), setPage("library")) } : undefined,
      });
      close(null);
    } catch (e) {
      if (e instanceof CoreFailure && e.wire.code === "sample-plan-stale") {
        toast({ text: t("newsamples.stale"), tone: "error" });
        await load();
      } else toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const trackRow = pv?.track ? tracks?.tracks.find((x) => x.id === pv.track!.assetId) : null;
  const current = req && req.kind !== "whole" ? req.currentAsset : undefined;
  const title = kind ? t(`newsamples.title.${kind}`) : "";
  const showRange = kind !== "whole";
  return (
    <Sheet
      isOpen={req != null}
      onClose={() => close(null)}
      title={title}
      sub={kind === "whole" ? t("newsamples.subWhole", { n: rows.length }) : undefined}
      testId="new-samples"
      footer={
        <>
          <span className={s.sheetNote}>
            {kind === "whole"
              ? t("newsamples.noteWhole")
              : pv && pv.track && pv.pads
                ? t(`newsamples.note.${kind}`, { a: pv.pads[0], b: pv.pads[1], track: trackRow ? trackName(trackRow, detail) : (current?.label ?? "") })
                : t("newsamples.noteNoTrack")}
          </span>
          <span className={s.grow} />
          <Button variant="flat" onPress={() => close(null)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!n || busy || !pv || !!pv.missingDefault} onPress={() => void run()} data-testid="newsamples-run">
            {t("newsamples.run", { n })}
          </Button>
        </>
      }
    >
      <div className={s.sheetMain}>
        {kind && kind !== "whole" ? (
          <div className={s.sheetBar}>
            <span className={s.groupLabel}>{t("newsamples.track")}</span>
            <Segmented<"default" | "current">
              size="sm"
              label={t("newsamples.track")}
              value={track}
              onChange={(v) => {
                setTrack(v);
                void load(range, v);
              }}
              options={[
                { id: "default", label: t(`newsamples.trackDefault.${role}`) },
                ...(current ? [{ id: "current" as const, label: t("newsamples.trackCurrent", { track: current.label }) }] : []),
              ]}
              testId="newsamples-track"
            />
          </div>
        ) : null}
        {pv?.missingDefault && tracks ? (
          <Callout tone="warn" testId="newsamples-missing">
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
        {error ? <Callout tone="bad">{error}</Callout> : null}
        {pv && !rows.length ? (
          <EmptyState title={t(`newsamples.empty.${kind}`)} body={t(`newsamples.emptyBody.${kind}`)} />
        ) : pv ? (
          <>
            <Stats
              items={[
                { n: counts.pending, label: t("subsample.stat.pending"), testId: "stat-pending" },
                ...(kind !== "whole" ? [{ n: counts.oped, label: t("subsample.stat.oped"), tone: "warn" as const, testId: "stat-oped" }] : []),
                ...(kind !== "whole" ? [{ n: counts.other, label: t("subsample.stat.other"), tone: "muted" as const, testId: "stat-other" }] : []),
              ]}
            />
            <div className={s.sheetBar}>
              {showRange ? (
                <>
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
                </>
              ) : null}
              <span className={s.grow} />
              <span className={s.groupLabel}>{t("nature.label")}</span>
              <Select
                value={nature}
                onChange={(v) => setNature(v as Nature | "auto")}
                label={t("nature.label")}
                options={NATURES.map((x) => ({ id: x, label: x === "auto" ? t(`newsamples.natureAuto.${kind}`) : t(`nature.${x}`) }))}
                testId="newsamples-nature"
              />
            </div>
            <div className={s.sheetTable}>
              <PagedTable
                label={title}
                rows={rows}
                checked={checked}
                onChecked={setChecked}
                isSelectable={(x) => x.status === "pending"}
                checkLabel={(x) => t("subsample.check", { name: x.name })}
                pageSize={200}
                testId="newsamples-table"
                columns={[
                  { id: "name", label: t("subsample.col.name"), isRowHeader: true, render: (x) => (x.name ? <span lang="ja" data-user-data="">{x.name}</span> : <span>{t("subsample.noName")}</span>) },
                  ...(kind !== "whole"
                    ? [
                        {
                          id: "src",
                          label: t(`newsamples.col.src.${kind}`),
                          width: "130px",
                          render: (x: Row) => <span className="num">{x.sourceStart != null ? `${clock(x.sourceStart, 1)}` : ""}</span>,
                        },
                        {
                          id: "range",
                          label: t("subsample.col.range", { a: pv.pads?.[0] ?? 0, b: pv.pads?.[1] ?? 0 }),
                          width: "150px",
                          render: (x: Row) => <span className="num">{`${seconds(x.start)}–${seconds(x.end)}`}</span>,
                        },
                      ]
                    : [{ id: "dur", label: t("newsamples.col.duration"), width: "120px", render: (x: Row) => <span className="num">{t("format.sec", { v: seconds(x.end - x.start) })}</span> }]),
                  ...(kind === "segments"
                    ? [{ id: "who", label: t("subsample.col.speakers"), render: (x: Row) => <span lang="ja" data-user-data="">{(x.speakers ?? []).join(t("settings.subtitle.speakerSep"))}</span> }]
                    : []),
                  {
                    id: "status",
                    label: t("subimport.col.status"),
                    width: "130px",
                    render: (x) => (
                      <span className={s.lineStatus} data-status={x.status === "pending" ? "importable" : x.status === "oped" ? "oped" : "registered"}>
                        {t(`subsample.status.${x.status}`)}
                      </span>
                    ),
                  },
                ]}
              />
            </div>
          </>
        ) : null}
      </div>
    </Sheet>
  );
}

export type { NewSamplesRequest };
