// 舞台「资料与来源」（UI_PLAN §3；规格 07 §7.8、03 §3.3）：性质、评分、备注（失焦保存）；来源（建立方式、父采样 + 试听父采样、已删除的父采样）；
// 派生采样（单击打开）；技术详情（绑定的声音、资产局部秒、判定区间、ID、时间）。改动都走统一编辑通道（快捷编辑，可撤销）。
import { useEffect, useState } from "react";
import type { Nature, SampleRow } from "../api/types";
import { Button } from "../components/Button";
import { Disclosure } from "../components/Controls";
import { Select, TextArea } from "../components/Fields";
import { NaturePicker } from "../components/NaturePicker";
import { clock, seconds } from "../format";
import { t } from "../i18n";
import s from "./Library.module.css";

export function StageInfo(props: {
  sample: SampleRow;
  onEdit: (fields: Record<string, unknown>, label: string) => void;
  onOpen: (id: string) => void;
  onAuditionParent: (id: string) => void;
  extra?: React.ReactNode;
}) {
  const r = props.sample;
  const d = r.detail;
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
          {d?.parent ? (
            <>
              <span className={s.mutedText}>{t("info.from")}</span>
              <Button size="sm" variant="flat" onPress={() => props.onOpen(d.parent!.id)} data-testid="stage-parent">
                <span lang="ja" data-user-data="">
                  {d.parent.name}
                </span>
              </Button>
              <Button size="sm" variant="flat" onPress={() => props.onAuditionParent(d.parent!.id)}>
                {t("info.auditionParent")}
              </Button>
            </>
          ) : r.parent_label ? (
            <span className={s.note}>{t("library.parentDeleted", { name: r.parent_label })}</span>
          ) : null}
          {d?.independent ? <span className={s.badge}>{t("info.independent")}</span> : null}
        </span>
      </div>
      {d?.children.length ? (
        <div className={s.field}>
          <span className={s.fieldLabel}>{t("info.children", { n: d.children.length })}</span>
          <span className={s.originLine} data-testid="stage-children">
            {d.children.slice(0, 12).map((c) => (
              <Button key={c.id} size="sm" variant="flat" onPress={() => props.onOpen(c.id)}>
                <span lang="ja" data-user-data="">
                  {c.name}
                </span>
              </Button>
            ))}
            {d.children.length > 12 ? <span className={s.mutedText}>{t("info.moreChildren", { n: d.children.length - 12 })}</span> : null}
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
