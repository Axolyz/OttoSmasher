// 标注（规格 04 §4.2.2：时间、文字、标签、作用域可编辑，可软删除，每次编辑留版本；任何变化都不移动已有采样 R4.11）：
// - 编辑：文字、种类（台词 / 音效 / 歌词——歌词只能由用户手动标）、标签、作用域、开始/结束；删除；
// - 新增区段标签（原片页时间线右键 / 选区）：纯标签区间，作用域 原片 / 人声 / 音效，至少一个标签。
// 一次保存 = 一次可撤销的编辑。
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { EditBatch } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Chips, Segmented } from "../components/Controls";
import { TextField, TimeField } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Sources.module.css";
import type { Ann } from "./Transcript";

export type AnnTarget = { mode: "edit"; ann: Ann } | { mode: "create"; sourceId: string; start: number; end: number };
type Scope = "source" | "vocal" | "sfx";
type Kind = "line" | "sfx" | "song";

const scopeOf = (a: Pick<Ann, "scope" | "scopeRole">): Scope => (a.scope === "role" ? (a.scopeRole ?? "vocal") : "source");

export function AnnotationDialog(props: { target: AnnTarget | null; duration: number; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const tg = props.target;
  const [text, setText] = useState("");
  const [kind, setKind] = useState<Kind>("line");
  const [tags, setTags] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [scope, setScope] = useState<Scope>("source");
  const [range, setRange] = useState<{ a: number; b: number }>({ a: 0, b: 0 });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!tg) return;
    setDraft("");
    if (tg.mode === "edit") {
      setText(tg.ann.name);
      setKind(tg.ann.kind === "tag" ? "line" : tg.ann.kind);
      setTags(tg.ann.tags);
      setScope(scopeOf(tg.ann));
      setRange({ a: tg.ann.start, b: tg.ann.end });
    } else {
      setText("");
      setTags([]);
      setScope("source");
      setRange({ a: tg.start, b: tg.end });
    }
  }, [tg]);

  const isTag = tg?.mode === "create" || (tg?.mode === "edit" && tg.ann.kind === "tag");
  const addDraft = () => {
    const v = draft.trim();
    if (v && !tags.includes(v)) setTags([...tags, v]);
    setDraft("");
  };

  const run = async (batch: EditBatch, done: string) => {
    setBusy(true);
    try {
      await call("edits.apply", { batch });
      toast({ text: done, action: { label: t("common.undo"), run: () => void undo() } });
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (!tg) return;
    const all = draft.trim() && !tags.includes(draft.trim()) ? [...tags, draft.trim()] : tags;
    const scoped = scope === "source" ? { scope: "source", scope_role: null } : { scope: "role", scope_role: scope };
    if (tg.mode === "create") {
      const fields = { source_id: tg.sourceId, kind: "tag", start: range.a, end: range.b, tags: all, clean_text: text, ...scoped };
      if (scope === "source") delete (fields as Record<string, unknown>).scope_role;
      return void run({ label: { code: "annotation-add", args: {} }, ops: [{ entity: "annotation", op: "create", fields }] }, t("ann.added"));
    }
    const a = tg.ann;
    const fields: Record<string, unknown> = {};
    if (text !== a.name) fields.clean_text = text;
    if (!isTag && kind !== a.kind) fields.kind = kind;
    if (JSON.stringify([...all].sort()) !== JSON.stringify([...a.tags].sort())) fields.tags = all;
    if (a.scope !== "asset" && scope !== scopeOf(a)) Object.assign(fields, scoped);
    if (range.a !== a.start) fields.start = range.a;
    if (range.b !== a.end) fields.end = range.b;
    if (!Object.keys(fields).length) return props.onClose();
    void run({ label: { code: "annotation-edit", args: {} }, ops: [{ entity: "annotation", id: a.id, version: a.version, fields }] }, t("ann.saved"));
  };
  const remove = () => {
    if (tg?.mode !== "edit") return;
    void run(
      { label: { code: "annotation-delete", args: {} }, ops: [{ entity: "annotation", id: tg.ann.id, version: tg.ann.version, fields: { deleted: true } }] },
      t("ann.deleted"),
    );
  };

  const canSave = !busy && range.b > range.a && (!isTag || tags.length > 0 || !!draft.trim());
  return (
    <DialogBox
      isOpen={tg != null}
      onClose={props.onClose}
      title={tg?.mode === "create" ? t("ann.createTitle") : t(isTag ? "ann.editTagTitle" : "ann.editTitle")}
      sub={tg?.mode === "edit" && tg.ann.text ? <span lang="ja" data-user-data="">{tg.ann.text}</span> : undefined}
      width={560}
      testId="annotation-dialog"
      footer={
        <>
          {tg?.mode === "edit" ? (
            <Button variant="flat" icon={<Trash2 />} onPress={remove} isDisabled={busy} data-testid="ann-delete">
              {t("ann.delete")}
            </Button>
          ) : null}
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={save} isDisabled={!canSave} data-testid="ann-save">
            {t("common.save")}
          </Button>
        </>
      }
    >
      <Callout>{t("ann.note")}</Callout>
      <div className={s.form}>
        <span className={s.formLabel}>{t("ann.text")}</span>
        <TextField value={text} onChange={setText} label={t("ann.text")} placeholder={isTag ? t("ann.textHintTag") : undefined} testId="ann-text" />
        {!isTag ? (
          <>
            <span className={s.formLabel}>{t("ann.kind")}</span>
            <div>
              <Segmented<Kind>
                value={kind}
                onChange={setKind}
                label={t("ann.kind")}
                testId="ann-kind"
                options={(["line", "sfx", "song"] as const).map((k) => ({ id: k, label: t(`ann.kind.${k}`) }))}
              />
            </div>
          </>
        ) : null}
        <span className={s.formLabel}>{t("ann.tags")}</span>
        <div className={s.tagEditor}>
          <Chips
            label={t("ann.tags")}
            items={tags.map((x) => ({ id: x, v: x, lang: "ja" }))}
            onRemove={(id) => setTags(tags.filter((x) => x !== id))}
            testId="ann-tags"
          />
          <div className={s.inline}>
            <TextField value={draft} onChange={setDraft} onSubmit={addDraft} label={t("ann.addTag")} placeholder={t("ann.tagHint")} testId="ann-tag-input" />
            <Button size="sm" variant="flat" icon={<Plus />} onPress={addDraft} isDisabled={!draft.trim()} aria-label={t("ann.addTag")} />
          </div>
        </div>
        {tg?.mode === "create" || (tg?.mode === "edit" && tg.ann.scope !== "asset") ? (
          <>
            <span className={s.formLabel}>{t("ann.scope")}</span>
            <div>
              <Segmented<Scope>
                value={scope}
                onChange={setScope}
                label={t("ann.scope")}
                testId="ann-scope"
                options={(["source", "vocal", "sfx"] as const).map((k) => ({ id: k, label: t(`ann.scope.${k}`) }))}
              />
            </div>
          </>
        ) : null}
        <span className={s.formLabel}>{t("ann.time")}</span>
        <div className={s.inline}>
          <TimeField
            value={range.a}
            label={t("sources.selStart")}
            testId="ann-start"
            onCommit={(v) => (v >= 0 && v < range.b ? (setRange({ ...range, a: v }), true) : false)}
          />
          <span className={s.arrow}>→</span>
          <TimeField
            value={range.b}
            label={t("sources.selEnd")}
            testId="ann-end"
            onCommit={(v) => (v > range.a && v <= props.duration + 1e-6 ? (setRange({ ...range, b: v }), true) : false)}
          />
        </div>
      </div>
    </DialogBox>
  );
}
