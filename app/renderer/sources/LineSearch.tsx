// 在全部原素材的台词里搜（所有者 2026-10-31）：原素材列表的搜索框同时搜作品 / 素材标识 / 文件名（上面）和文本层（这里）。
// 搜的是原料（段与音效提示），结果是原片上的位置，不是采样（采样库的筛选与三大搜索只对采样）；规则同采样的“原句”筛选（原文或读音）。
// 按原素材分组（顺序同列表）；单击一处 = 打开那一集、选区设为那一段、跳到开头（同台本单击）；单击组头 = 只打开那一集。
import { useEffect, useMemo, useRef, useState } from "react";
import { call } from "../api/core";
import type { SourceRow, TextLayerHit, TextLayerSearchResult } from "../api/types";
import { ActionList } from "../components/ActionList";
import { Button } from "../components/Button";
import { clock } from "../format";
import { t } from "../i18n";
import { displayName } from "./SourceList";
import { marked } from "./Transcript";
import s from "./Sources.module.css";

const LIMIT = 500;

type Row = { id: string; kind: "head"; row: SourceRow; n: number } | { id: string; kind: "hit"; hit: TextLayerHit };

export function LineSearch(props: {
  q: string;
  /** 列表的顺序（作品名排序、组内同列表） */
  rows: SourceRow[];
  onOpen: (sourceId: string) => void;
  onJump: (hit: TextLayerHit) => void;
  onImport: (rows: SourceRow[]) => void;
}) {
  const [res, setRes] = useState<TextLayerSearchResult | null>(null);
  const seq = useRef(0);
  useEffect(() => {
    const n = ++seq.current;
    if (!props.q.trim()) return setRes(null);
    const timer = setTimeout(() => {
      void call("textLayer.search", { query: props.q, limit: LIMIT }).then(
        (r) => n === seq.current && setRes(r),
        () => n === seq.current && setRes(null),
      );
    }, 200);
    return () => clearTimeout(timer);
  }, [props.q]);

  const byId = useMemo(() => new Map(props.rows.map((r) => [r.id, r])), [props.rows]);
  const items = useMemo(() => {
    if (!res) return [];
    const groups = new Map<string, TextLayerHit[]>();
    for (const h of res.hits) {
      const g = groups.get(h.sourceId) ?? [];
      g.push(h);
      groups.set(h.sourceId, g);
    }
    const counts = new Map(res.bySource.map((x) => [x.sourceId, x.count]));
    const out: Row[] = [];
    for (const r of props.rows) {
      const hs = groups.get(r.id);
      if (!hs) continue;
      out.push({ id: `src:${r.id}`, kind: "head", row: r, n: counts.get(r.id) ?? hs.length });
      for (const h of hs) out.push({ id: `${h.kind}:${h.id}`, kind: "hit", hit: h });
    }
    return out;
  }, [res, props.rows]);

  if (!res) return null;
  const pending = res.notImported.map((id) => byId.get(id)).filter((r): r is SourceRow => !!r);
  return (
    <section className={`${s.lineSearch} ${res.query !== props.q ? s.dim : ""}`} data-testid="line-search" data-stale={res.query !== props.q || undefined}>
      <div className={s.lineSearchHead}>
        <span>{t("lineSearch.title")}</span>
        <span className={`${s.transcriptSub} num`} data-testid="line-search-count">
          {res.total ? t("lineSearch.count", { n: res.total, m: res.bySource.length }) : t("lineSearch.none")}
        </span>
      </div>
      {res.total > LIMIT ? <div className={s.hint}>{t("lineSearch.more", { n: LIMIT })}</div> : null}
      {items.length ? (
        <ActionList<Row>
          label={t("lineSearch.title")}
          items={items}
          textValue={(r) => (r.kind === "head" ? displayName(r.row) : r.hit.text)}
          current={null}
          testId="line-search-list"
          rowTestId="line-hit"
          onPress={(id) => {
            const r = items.find((x) => x.id === id);
            if (r?.kind === "head") props.onOpen(r.row.id);
            else if (r) props.onJump(r.hit);
          }}
          render={(r) =>
            r.kind === "head" ? (
              <span className={s.lineHead}>
                <span className={s.groupName} data-user-data="">
                  {displayName(r.row)}
                </span>
                <span className={`${s.groupCount} num`}>{t("lineSearch.inSource", { n: r.n })}</span>
              </span>
            ) : (
              <>
                <span className={`${s.muted} num`}>{clock(r.hit.start, 1)}</span>
                <span className={s.who} lang="ja" data-user-data="">
                  {r.hit.kind === "hint" ? t("subtitle.kind.sfx") : r.hit.speakers.join(t("settings.subtitle.speakerSep"))}
                </span>
                <span className={s.segText}>
                  <span lang="ja" data-user-data="">
                    {marked(r.hit.text.replace(/\n/g, " "), r.hit.spans)}
                  </span>
                  {r.hit.match === "reading" ? <span className={s.segFlags}>{t("lineSearch.byReading")}</span> : null}
                </span>
              </>
            )
          }
        />
      ) : null}
      {pending.length ? (
        <div className={s.lineSearchFoot} data-testid="line-search-not-imported">
          <span className={s.hint}>{t("lineSearch.notImported", { n: pending.length })}</span>
          <Button size="sm" variant="flat" onPress={() => props.onImport(pending)}>
            {t("lineSearch.importAll")}
          </Button>
        </div>
      ) : null}
      {res.readingPending ? <div className={s.hint}>{t("lineSearch.readingPending", { n: res.readingPending })}</div> : null}
    </section>
  );
}
