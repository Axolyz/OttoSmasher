// 标签与资料的批量操作（规格 07 §7.4–§7.6、16 R8.5、R9；原型 tagModal / editModal）。两步：预览影响（不写库）→ 应用（原子、可撤销）。
// - 添加标签：给所选 N 项加本地标签；继承标签去来源改。
// - 移除标签：只列有本地数量的标签（“本地 n / 继承 m”，按采样计）；继承的给「去来源」。
// - 编辑资料：名称、性质、星标、评分、本地标签 + / −；留空 = 保持不变；预览是逐字段前后对比。
import { useEffect, useMemo, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { BatchEditFields, BatchEditPlan, Nature, SampleTagCount } from "../api/types";
import { Button } from "../components/Button";
import { Callout } from "../components/Controls";
import { Select, TextField } from "../components/Fields";
import { NATURES } from "../components/NaturePicker";
import { DialogBox } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Library.module.css";

export type BatchKind = "tags-add" | "tags-remove" | "edit";

/** 一次预览的结果（逐字段前后对比，最多列 200 行）与“应用” */
function PlanPreview(props: { plan: BatchEditPlan }) {
  const rows = props.plan.preview.changes.flatMap((c) =>
    c.diffs.map((d, k) => ({ id: `${c.id}:${k}`, name: props.plan.names[c.id] ?? c.id, field: d.field, before: d.before, after: d.after })),
  );
  const show = (v: unknown) => (v == null ? t("batch.empty") : Array.isArray(v) ? v.join(t("scope.or")) || t("batch.empty") : typeof v === "boolean" ? t(v ? "batch.yes" : "batch.no") : typeof v === "string" && (NATURES as readonly string[]).includes(v) ? t(`nature.${v}`) : String(v));
  return (
    <div className={s.batchPreview} data-testid="batch-preview">
      <div className={s.hintText}>{t("batch.previewSay", { n: props.plan.preview.changes.length, k: props.plan.unchanged })}</div>
      <PagedTable
        label={t("batch.previewSay", { n: props.plan.preview.changes.length, k: props.plan.unchanged })}
        rows={rows.slice(0, 200)}
        pageSize={8}
        columns={[
          { id: "name", label: t("batch.col.sample"), width: "34%", isRowHeader: true, render: (r) => <span lang="ja" data-user-data="">{r.name}</span> },
          { id: "field", label: t("batch.col.field"), width: "16%", render: (r) => t(`batch.field.${r.field}`) },
          { id: "change", label: t("batch.col.change"), render: (r) => <span data-user-data="">{show(r.before)} → {show(r.after)}</span> },
        ]}
      />
    </div>
  );
}

export function BatchDialog(props: { kind: BatchKind | null; ids: string[]; onClose: () => void; onDone: () => void; onGoSource?: (ref: SampleTagCount["sources"][number]) => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const kind = props.kind;
  const n = props.ids.length;
  const [tag, setTag] = useState("");
  const [counts, setCounts] = useState<SampleTagCount[] | null>(null);
  const [remove, setRemove] = useState<Set<string>>(new Set());
  const [name, setName] = useState("");
  const [nature, setNature] = useState("keep");
  const [star, setStar] = useState("keep");
  const [rating, setRating] = useState("keep");
  const [tagOps, setTagOps] = useState("");
  const [plan, setPlan] = useState<BatchEditPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!kind) return;
    setTag("");
    setRemove(new Set());
    setName("");
    setNature("keep");
    setStar("keep");
    setRating("keep");
    setTagOps("");
    setPlan(null);
    setError(null);
    setCounts(null);
    if (kind === "tags-remove") void call("tags.ofSamples", { ids: props.ids }).then(setCounts, () => setCounts([]));
  }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const fields = useMemo<BatchEditFields | null>(() => {
    if (kind === "tags-add") return tag.trim() ? { addTags: [tag.trim()] } : null;
    if (kind === "tags-remove") return remove.size ? { removeTags: [...remove] } : null;
    const f: BatchEditFields = {};
    if (name.trim()) f.name = name.trim();
    if (nature !== "keep") f.nature = nature as Nature;
    if (star !== "keep") f.starred = star === "yes";
    if (rating !== "keep") f.rating = Number(rating);
    // “+好用 −尖叫”：空白分隔，+ 加、− 或 - 去；不带符号的算加
    const add: string[] = [];
    const rm: string[] = [];
    for (const w of tagOps.split(/\s+/).filter(Boolean)) {
      if (w[0] === "-" || w[0] === "−") rm.push(w.slice(1));
      else add.push(w[0] === "+" ? w.slice(1) : w);
    }
    if (add.filter(Boolean).length) f.addTags = add.filter(Boolean);
    if (rm.filter(Boolean).length) f.removeTags = rm.filter(Boolean);
    return Object.keys(f).length ? f : null;
  }, [kind, tag, remove, name, nature, star, rating, tagOps]);

  // 条件一变，旧预览作废
  useEffect(() => setPlan(null), [fields]);

  const preview = async () => {
    if (!fields) return;
    setBusy(true);
    try {
      setPlan(await call("samples.batchEdit", { ids: props.ids, fields }));
      setError(null);
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setBusy(false);
    }
  };
  const apply = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      const n = plan.preview.changes.length;
      const label = kind === "tags-add" ? { code: "batch-tags-add", args: { n, tag: tag.trim() } } : kind === "tags-remove" ? { code: "batch-tags-remove", args: { n } } : plan.batch.label;
      if (plan.batch.ops.length) await call("edits.apply", { batch: { ...plan.batch, label } });
      toast({ text: t("batch.done", { n: plan.preview.changes.length }), action: { label: t("common.undo"), run: () => void undo().then(props.onDone) } });
      props.onDone();
      props.onClose();
    } catch (e) {
      // 期间别处改过（版本不符）→ 整批拒绝，重新预览（R9.1）
      setPlan(null);
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setBusy(false);
    }
  };

  const title = kind === "tags-add" ? t("batch.addTitle", { n }) : kind === "tags-remove" ? t("batch.removeTitle", { n }) : t("batch.editTitle", { n });
  const say = kind === "tags-add" ? t("batch.addSay") : kind === "tags-remove" ? t("batch.removeSay") : t("batch.editSay");
  const keep = { id: "keep", label: t("batch.keep") };
  return (
    <DialogBox
      isOpen={!!kind}
      onClose={props.onClose}
      title={title}
      sub={say}
      width={kind === "tags-add" ? 480 : 640}
      testId="batch-dialog"
      footer={
        <>
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          {plan ? (
            <Button variant="primary" onPress={() => void apply()} isDisabled={busy || !plan.preview.changes.length} data-testid="batch-apply">
              {t("batch.apply", { n: plan.preview.changes.length })}
            </Button>
          ) : (
            <Button variant="primary" onPress={() => void preview()} isDisabled={busy || !fields} data-testid="batch-preview-btn">
              {t("batch.previewBtn")}
            </Button>
          )}
        </>
      }
    >
      {kind === "tags-add" ? (
        <TextField value={tag} onChange={setTag} onSubmit={() => void preview()} autoFocus label={t("batch.tagName")} placeholder={t("ann.tagHint")} testId="batch-tag" />
      ) : null}
      {kind === "tags-remove" ? (
        counts && !counts.length ? (
          <div className={s.mutedText}>{t("batch.noTags")}</div>
        ) : (
          <PagedTable<SampleTagCount & { id: string }>
            label={title}
            rows={(counts ?? []).map((c) => ({ ...c, id: c.tag }))}
            pageSize={8}
            checked={remove}
            onChecked={setRemove}
            isSelectable={(r) => r.local > 0}
            checkLabel={(r) => r.tag}
            columns={[
              { id: "tag", label: t("batch.col.tag"), isRowHeader: true, render: (r) => <span lang="ja" data-user-data="">{r.tag}</span> },
              { id: "local", label: t("batch.col.local"), width: "70px", align: "end", render: (r) => <span className="num">{r.local}</span> },
              {
                id: "inh",
                label: t("batch.col.inherited"),
                width: "140px",
                align: "end",
                render: (r) => (
                  <span className={s.rowOps}>
                    <span className="num">{r.inherited}</span>
                    {r.inherited && r.sources[0] && props.onGoSource ? (
                      <Button size="sm" variant="flat" onPress={() => props.onGoSource!(r.sources[0]!)}>
                        {t("batch.goSource")}
                      </Button>
                    ) : null}
                  </span>
                ),
              },
            ]}
          />
        )
      ) : null}
      {kind === "edit" ? (
        <div className={s.editGrid}>
          <span>{t("batch.field.name")}</span>
          <TextField value={name} onChange={setName} label={t("batch.field.name")} placeholder={t("batch.keepHint")} testId="batch-name" />
          <span>{t("batch.field.nature")}</span>
          <Select value={nature} onChange={setNature} label={t("batch.field.nature")} options={[keep, ...NATURES.map((x) => ({ id: x, label: t(`nature.${x}`) }))]} testId="batch-nature" />
          <span>{t("batch.field.starred")}</span>
          <Select value={star} onChange={setStar} label={t("batch.field.starred")} options={[keep, { id: "yes", label: t("batch.yes") }, { id: "no", label: t("batch.no") }]} />
          <span>{t("batch.field.rating")}</span>
          <Select value={rating} onChange={setRating} label={t("batch.field.rating")} options={[keep, ...[0, 1, 2, 3, 4, 5].map((v) => ({ id: String(v), label: v ? t("batch.ratingN", { n: v }) : t("batch.noRating") }))]} />
          <span>{t("batch.field.local_tags")}</span>
          <TextField value={tagOps} onChange={setTagOps} label={t("batch.field.local_tags")} placeholder={t("batch.tagOpsHint")} testId="batch-tags" />
        </div>
      ) : null}
      {error ? <Callout tone="bad">{error}</Callout> : null}
      {plan ? <PlanPreview plan={plan} /> : null}
    </DialogBox>
  );
}
