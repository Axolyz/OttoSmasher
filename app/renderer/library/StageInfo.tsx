// 详情区「资料与来源」（UI_PLAN §3；规格 07 §7.8、03 §3.3）：性质、评分、备注（失焦保存）；建立方式；加工链（声音怎么一步步做出来的，
// 每步可点：在原素材页打开那条整轨并跳到那段）；相关采样（同一原素材上原素材时间交叠的采样，跨所有音轨；单击打开）；
// 技术详情（绑定的声音、资产局部秒、判定区间、ID、时间）。采样之间没有父子关系（所有者 2026-10-12）。改动都走统一编辑通道（快捷编辑，可撤销）。
import { useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";
import type { ChainStep, Nature, RelatedSamples, SampleRow } from "../api/types";
import { Button } from "../components/Button";
import { Disclosure } from "../components/Controls";
import { Select, TextArea } from "../components/Fields";
import { NaturePicker } from "../components/NaturePicker";
import { clock, seconds } from "../format";
import { t } from "../i18n";
import s from "./Library.module.css";
import { assetLabel } from "./StageSpeech";

const RELATED_MAX = 12;

export function StageInfo(props: {
  sample: SampleRow;
  onEdit: (fields: Record<string, unknown>, label: string) => void;
  onOpen: (id: string) => void;
  /** 加工链的一步：在原素材页打开那条轨（局部成品 = 它往下第一条整轨）并跳到它覆盖的原素材范围 */
  onOpenStep: (step: ChainStep, fallbackAssetId: string | null) => void;
  extra?: React.ReactNode;
}) {
  const r = props.sample;
  const d = r.detail;
  const [related, setRelated] = useState<RelatedSamples | null>(null);
  const [relNonce, setRelNonce] = useState(0);
  useCoreEvent("data.changed", (x) => {
    if ((x as Record<string, string[]>).sample) setRelNonce((n) => n + 1);
  });
  useEffect(() => {
    let live = true;
    void call("samples.related", { id: r.id, limit: RELATED_MAX }).then(
      (v) => live && setRelated(v),
      () => live && setRelated(null),
    );
    return () => {
      live = false;
    };
  }, [r.id, relNonce]);
  const steps = d?.chain.steps ?? [];
  const [note, setNote] = useState(d?.note ?? "");
  useEffect(() => setNote(d?.note ?? ""), [r.id, d?.note]);
  const saveNote = () => {
    if (d && note !== d.note) props.onEdit({ note }, "sample-note");
  };
  return (
    <section className={s.card} data-testid="stage-info">
      <h3 className={s.cardTitle}>{t("library.info")}</h3>
      <div className={s.field}>
        <span className={s.fieldLabel}>{t("nature.label")}</span>
        <NaturePicker value={r.nature} onChange={(n: Nature) => props.onEdit({ nature: n }, "sample-nature")} testId="stage-nature" />
      </div>
      <div className={s.field}>
        <span className={s.fieldLabel}>{t("batch.field.rating")}</span>
        <Select
          value={String(r.rating ?? 0)}
          onChange={(v) => props.onEdit({ rating: Number(v) || null }, "sample-rating")}
          label={t("batch.field.rating")}
          options={[0, 1, 2, 3, 4, 5].map((v) => ({ id: String(v), label: v ? t("batch.ratingN", { n: v }) : t("batch.noRating") }))}
          testId="stage-rating"
        />
      </div>
      <div className={s.field}>
        <span className={s.fieldLabel}>{t("batch.field.note")}</span>
        <div className={s.grow}>
          <TextArea value={note} onChange={setNote} onBlur={saveNote} rows={2} label={t("batch.field.note")} placeholder={t("info.notePlaceholder")} testId="stage-note" />
        </div>
      </div>
      <div className={s.field}>
        <span className={s.fieldLabel}>{t("library.origin")}</span>
        <span className={s.originLine}>
          <span>{t(`library.via.${r.created_via}`)}</span>
          {d?.independent ? <span className={s.badge}>{t("info.independent")}</span> : null}
        </span>
      </div>
      {steps.length > 1 ? (
        <div className={s.field}>
          <span className={s.fieldLabel}>{t("info.chain")}</span>
          <span className={s.originLine} data-testid="stage-chain">
            {steps.map((st, i) => {
              // 局部成品：打开它往下第一条整轨（「返回原素材」同一规则，永远不把局部成品当音源）
              const below = steps.slice(i).find((x) => x.full)?.asset.id ?? r.back_asset_id;
              return (
                <span key={st.asset.id} className={s.originLine}>
                  {i > 0 ? <span className={s.mutedText}>←</span> : null}
                  <Button size="sm" variant="flat" onPress={() => props.onOpenStep(st, st.full ? st.asset.id : below)} data-testid="stage-chain-step">
                    <span data-user-data="">{assetLabel(st.asset)}</span>
                    {st.full ? null : <span className="num"> · {clock(st.sourceStart)}–{clock(st.sourceEnd)}</span>}
                  </Button>
                </span>
              );
            })}
            {d && !d.chain.complete ? <span className={s.mutedText}>{t("info.chainBroken")}</span> : null}
          </span>
        </div>
      ) : null}
      {related && related.total > 0 ? (
        <div className={s.field}>
          <span className={s.fieldLabel}>{t("info.related", { n: related.total })}</span>
          <span className={s.originLine} data-testid="stage-related">
            {related.rows.map((x) => (
              <Button key={x.sample.id} size="sm" variant="flat" onPress={() => props.onOpen(x.sample.id)} title={t("info.relatedTip", { s: seconds(x.overlap) })}>
                <span lang="ja" data-user-data="">
                  {x.sample.name}
                </span>
                <span className={s.mutedText}> · {x.stemName ?? t(`track.origin.${x.sample.asset_origin}`)}</span>
              </Button>
            ))}
            {related.total > related.rows.length ? <span className={s.mutedText}>{t("info.moreRelated", { n: related.total - related.rows.length })}</span> : null}
          </span>
        </div>
      ) : null}
      {props.extra}
      <Disclosure title={t("info.tech")} testId="stage-tech">
        <dl className={s.techList}>
          <dt>{t("info.sound")}</dt>
          <dd data-user-data="">
            {d?.stemName ?? t(`track.origin.${r.asset_origin}`)}
            {r.stream_ordinal != null ? ` · ${t("info.stream", { n: r.stream_ordinal + 1 })}` : ""}
          </dd>
          <dt>{t("info.range")}</dt>
          <dd className="num">
            {seconds(r.start)}–{seconds(r.end)} {t("info.localSec")}
          </dd>
          <dt>{t("info.sourceAt")}</dt>
          <dd className="num">{clock(r.source_start)}</dd>
          {d?.judge ? (
            <>
              <dt>{t("info.judge")}</dt>
              <dd className="num">
                {clock(d.judge[0]!)}–{clock(d.judge[1]!)}
              </dd>
            </>
          ) : null}
          <dt>{t("info.created")}</dt>
          <dd className="num">{r.created_at.replace("T", " ").slice(0, 19)}</dd>
          <dt>ID</dt>
          <dd className="mono">{r.id}</dd>
        </dl>
      </Disclosure>
    </section>
  );
}
