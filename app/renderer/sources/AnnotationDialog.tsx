// 原片上的时间对象的编辑框（所有者 2026-10-09：文本层的段 / 音效提示 / 区段标签各做一件事）。一次保存 = 一次可撤销的编辑；任何变化都不移动已有采样（R4.11）。
// - 段（说了什么，给分析）：文本（= 对齐文本，保留换行）、说话人、开始/结束；删除；写明“这段被 N 个采样使用，修改会影响它们”（P13）与两个受保护标记；
//   添加台词（手输段）：与已有段重叠时让用户选替换 / 切开（只在每个重叠段都只从一侧伸进来时可用）/ 取消；拆分：在某个时刻切成两段、两边的文字由用户分。
// - 音效提示（给人工拣选）：文字、开始/结束；删除；也能手动新增（算受保护）。
// - 区段标签（时间上的属性，用户显式画的）：标签、说明、作用域（原片 / 人声 / 音效）、开始/结束；删除。
import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { EditBatch, RangeTagRow, SegmentAddCheck, SfxHint, TextSegment } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Chips, Segmented } from "../components/Controls";
import { TextArea, TextField, TimeField } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { clock } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export type AnnTarget =
  /** shift：资产作用域的标签存资产局部秒，框里按原片时钟显示（原片秒 = 局部秒 + shift） */
  | { mode: "edit-tag"; tag: RangeTagRow; shift?: number }
  | { mode: "create-tag"; sourceId: string; start: number; end: number }
  | { mode: "edit-segment"; seg: TextSegment }
  | { mode: "create-segment"; sourceId: string; start: number; end: number; text?: string }
  | { mode: "split-segment"; seg: TextSegment; at: number }
  | { mode: "edit-hint"; hint: SfxHint }
  | { mode: "create-hint"; sourceId: string; start: number; end: number };
type Scope = "source" | "vocal" | "sfx";

const scopeOf = (a: Pick<RangeTagRow, "scope" | "scopeRole">): Scope => (a.scope === "role" ? (a.scopeRole ?? "vocal") : "source");

/** 拆分时文字的预填：按时间比例切到最近的字 */
function splitText(text: string, ratio: number): [string, string] {
  const k = Math.max(1, Math.min(text.length - 1, Math.round(text.length * ratio)));
  return [text.slice(0, k).trim(), text.slice(k).trim()];
}

export function AnnotationDialog(props: { target: AnnTarget | null; duration: number; onClose: () => void; onSegmentAdded?: (id: string) => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const tg = props.target;
  const [text, setText] = useState("");
  const [right, setRight] = useState("");
  const [at, setAt] = useState(0);
  const [tags, setTags] = useState<string[]>([]);
  const [speakers, setSpeakers] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [scope, setScope] = useState<Scope>("source");
  const [range, setRange] = useState<{ a: number; b: number }>({ a: 0, b: 0 });
  const [check, setCheck] = useState<SegmentAddCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const mode = tg?.mode ?? null;
  const isTag = mode === "edit-tag" || mode === "create-tag";
  const isSeg = mode === "edit-segment" || mode === "create-segment";
  const isHint = mode === "edit-hint" || mode === "create-hint";

  useEffect(() => {
    if (!tg) return;
    setDraft("");
    setCheck(null);
    if (tg.mode === "edit-tag") {
      setText(tg.tag.label);
      setTags(tg.tag.tags);
      setScope(scopeOf(tg.tag));
      setRange({ a: tg.tag.start + (tg.shift ?? 0), b: tg.tag.end + (tg.shift ?? 0) });
    } else if (tg.mode === "edit-segment") {
      setText(tg.seg.text);
      setSpeakers(tg.seg.speakers);
      setRange({ a: tg.seg.start, b: tg.seg.end });
    } else if (tg.mode === "split-segment") {
      const [l, r] = splitText(tg.seg.text, (tg.at - tg.seg.start) / (tg.seg.end - tg.seg.start));
      setText(l);
      setRight(r);
      setAt(tg.at);
    } else if (tg.mode === "edit-hint") {
      setText(tg.hint.text);
      setRange({ a: tg.hint.start, b: tg.hint.end });
    } else {
      setText(tg.mode === "create-segment" ? (tg.text ?? "") : "");
      setTags([]);
      setSpeakers([]);
      setScope("source");
      setRange({ a: tg.start, b: tg.end });
    }
  }, [tg]);

  const addDraft = () => {
    const v = draft.trim();
    if (!v) return;
    if (isTag && !tags.includes(v)) setTags([...tags, v]);
    if (isSeg && !speakers.includes(v)) setSpeakers([...speakers, v]);
    setDraft("");
  };

  const fail = (e: unknown) => toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
  const run = async (batch: EditBatch, done: string) => {
    setBusy(true);
    try {
      await call("edits.apply", { batch });
      toast({ text: done, action: { label: t("common.undo"), run: () => void undo() } });
      props.onClose();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const addSegment = async (resolve: "replace" | "cut" | null) => {
    if (tg?.mode !== "create-segment") return;
    setBusy(true);
    try {
      if (resolve == null) {
        const c = await call("segments.checkAdd", { sourceId: tg.sourceId, start: range.a, end: range.b });
        if (c.conflicts.length) {
          setCheck(c);
          return;
        }
      }
      const r = await call("segments.add", { sourceId: tg.sourceId, start: range.a, end: range.b, text, resolve });
      toast({ text: t("seg.added"), action: { label: t("common.undo"), run: () => void undo() } });
      if (r.id) props.onSegmentAdded?.(r.id);
      props.onClose();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (!tg) return;
    const extra = draft.trim();
    if (tg.mode === "create-tag") {
      const all = extra && !tags.includes(extra) ? [...tags, extra] : tags;
      const fields: Record<string, unknown> = { source_id: tg.sourceId, start: range.a, end: range.b, tags: all, label: text, scope: scope === "source" ? "source" : "role" };
      if (scope !== "source") fields.scope_role = scope;
      return void run({ label: { code: "annotation-add", args: {} }, ops: [{ entity: "range_tag", op: "create", fields }] }, t("ann.added"));
    }
    if (tg.mode === "edit-tag") {
      const all = extra && !tags.includes(extra) ? [...tags, extra] : tags;
      const a = tg.tag;
      const fields: Record<string, unknown> = {};
      if (text !== a.label) fields.label = text;
      if (JSON.stringify([...all].sort()) !== JSON.stringify([...a.tags].sort())) fields.tags = all;
      if (a.scope !== "asset" && scope !== scopeOf(a)) Object.assign(fields, scope === "source" ? { scope: "source", scope_role: null } : { scope: "role", scope_role: scope });
      const sh = tg.shift ?? 0;
      if (range.a !== a.start + sh) fields.start = range.a - sh;
      if (range.b !== a.end + sh) fields.end = range.b - sh;
      if (!Object.keys(fields).length) return props.onClose();
      return void run({ label: { code: "annotation-edit", args: {} }, ops: [{ entity: "range_tag", id: a.id, version: a.version, fields }] }, t("ann.saved"));
    }
    if (tg.mode === "create-segment") return void addSegment(null);
    if (tg.mode === "edit-segment") {
      const names = extra && !speakers.includes(extra) ? [...speakers, extra] : speakers;
      const a = tg.seg;
      const fields: Record<string, unknown> = {};
      if (text.trim() !== a.text) fields.text = text;
      if (JSON.stringify(names) !== JSON.stringify(a.speakers)) fields.speakers = names;
      if (range.a !== a.start) fields.start = range.a;
      if (range.b !== a.end) fields.end = range.b;
      if (!Object.keys(fields).length) return props.onClose();
      return void run({ label: { code: "segment-edit", args: {} }, ops: [{ entity: "segment", id: a.id, version: a.version, fields }] }, t("seg.saved"));
    }
    if (tg.mode === "split-segment") {
      setBusy(true);
      void call("segments.split", { id: tg.seg.id, version: tg.seg.version, at, left: text, right })
        .then(() => {
          toast({ text: t("seg.splitDone"), action: { label: t("common.undo"), run: () => void undo() } });
          props.onClose();
        }, fail)
        .finally(() => setBusy(false));
      return;
    }
    if (tg.mode === "create-hint") {
      setBusy(true);
      void call("hints.add", { sourceId: tg.sourceId, start: range.a, end: range.b, text })
        .then(() => {
          toast({ text: t("hint.added"), action: { label: t("common.undo"), run: () => void undo() } });
          props.onClose();
        }, fail)
        .finally(() => setBusy(false));
      return;
    }
    const h = tg.hint;
    const fields: Record<string, unknown> = {};
    if (text.trim() !== h.text) fields.text = text;
    if (range.a !== h.start) fields.start = range.a;
    if (range.b !== h.end) fields.end = range.b;
    if (!Object.keys(fields).length) return props.onClose();
    void run({ label: { code: "hint-edit", args: {} }, ops: [{ entity: "sfx_hint", id: h.id, version: h.version, fields }] }, t("hint.saved"));
  };
  const remove = () => {
    if (!tg) return;
    if (tg.mode === "edit-tag")
      return void run({ label: { code: "annotation-delete", args: {} }, ops: [{ entity: "range_tag", id: tg.tag.id, version: tg.tag.version, fields: { deleted: true } }] }, t("ann.deleted"));
    if (tg.mode === "edit-segment")
      return void run({ label: { code: "segment-delete", args: {} }, ops: [{ entity: "segment", id: tg.seg.id, version: tg.seg.version, fields: { deleted: true } }] }, t("seg.deleted"));
    if (tg.mode === "edit-hint")
      return void run({ label: { code: "hint-delete", args: {} }, ops: [{ entity: "sfx_hint", id: tg.hint.id, version: tg.hint.version, fields: { deleted: true } }] }, t("hint.deleted"));
  };

  const split = mode === "split-segment" && tg?.mode === "split-segment" ? tg.seg : null;
  const canSave = !busy && (split ? at > split.start && at < split.end && !!text.trim() && !!right.trim() : range.b > range.a) && (!isTag || tags.length > 0 || !!draft.trim()) && (isTag || !!text.trim());
  const seg = tg?.mode === "edit-segment" ? tg.seg : null;
  const title = !tg
    ? ""
    : t(
        {
          "edit-tag": "ann.editTagTitle",
          "create-tag": "ann.createTitle",
          "edit-segment": "seg.editTitle",
          "create-segment": "seg.createTitle",
          "split-segment": "seg.splitTitle",
          "edit-hint": "hint.editTitle",
          "create-hint": "hint.createTitle",
        }[tg.mode],
      );
  return (
    <DialogBox
      isOpen={tg != null}
      onClose={props.onClose}
      title={title}
      sub={seg?.raw ? <span lang="ja" data-user-data="">{seg.raw}</span> : split ? `${clock(split.start)}–${clock(split.end)}` : undefined}
      width={560}
      testId="annotation-dialog"
      footer={
        <>
          {mode === "edit-tag" || mode === "edit-segment" || mode === "edit-hint" ? (
            <Button variant="flat" icon={<Trash2 />} onPress={remove} isDisabled={busy} data-testid="ann-delete">
              {t("ann.delete")}
            </Button>
          ) : null}
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onPress={save} isDisabled={!canSave || !!check} data-testid="ann-save">
            {mode === "split-segment" ? t("seg.split") : t("common.save")}
          </Button>
        </>
      }
    >
      <Callout>{t(isTag ? "ann.note" : isSeg || split ? "seg.note" : "hint.note")}</Callout>
      {seg ? (
        <div className={s.muted} data-testid="seg-usage">
          {t("seg.usedBy", { n: seg.usedBy })}
          {seg.edited ? ` · ${t("seg.flag.edited")}` : ""}
          {seg.manual ? ` · ${t("seg.flag.manual")}` : ""}
        </div>
      ) : null}
      {check ? (
        <Callout tone="warn" testId="seg-overlap">
          <div>{t("seg.overlap", { n: check.conflicts.length })}</div>
          <ul className={s.overlapList}>
            {check.conflicts.map((c) => (
              <li key={c.id} lang="ja" data-user-data="">{`${clock(c.start)}–${clock(c.end)} ${c.text.replace(/\n/g, " ")}`}</li>
            ))}
          </ul>
          <div className={s.inline}>
            <Button size="sm" variant="primary" onPress={() => void addSegment("replace")} isDisabled={busy} data-testid="seg-replace">
              {t("seg.replace")}
            </Button>
            <Button size="sm" variant="flat" onPress={() => void addSegment("cut")} isDisabled={busy || !check.canCut} title={check.canCut ? undefined : t("seg.cutUnavailable")} data-testid="seg-cut">
              {t("seg.cut")}
            </Button>
            <Button size="sm" variant="flat" onPress={() => setCheck(null)} data-testid="seg-cancel">
              {t("common.cancel")}
            </Button>
          </div>
        </Callout>
      ) : null}
      <div className={s.form}>
        {split ? (
          <>
            <span className={s.formLabel}>{t("seg.splitAt")}</span>
            <TimeField value={at} label={t("seg.splitAt")} testId="seg-split-at" onCommit={(v) => (v > split.start && v < split.end ? (setAt(v), true) : false)} />
            <span className={s.formLabel}>{t("seg.left")}</span>
            <TextArea value={text} onChange={setText} label={t("seg.left")} rows={2} testId="seg-left" />
            <span className={s.formLabel}>{t("seg.right")}</span>
            <TextArea value={right} onChange={setRight} label={t("seg.right")} rows={2} testId="seg-right" />
          </>
        ) : (
          <>
            <span className={s.formLabel}>{t(isTag ? "ann.text" : isSeg ? "seg.text" : "hint.text")}</span>
            {isSeg ? (
              <TextArea value={text} onChange={setText} label={t("seg.text")} rows={3} testId="seg-text" />
            ) : (
              <TextField value={text} onChange={setText} label={t("ann.text")} placeholder={isTag ? t("ann.textHintTag") : undefined} testId="ann-text" />
            )}
            {isTag || isSeg ? (
              <>
                <span className={s.formLabel}>{t(isTag ? "ann.tags" : "seg.speakers")}</span>
                <div className={s.tagEditor}>
                  <Chips
                    label={t(isTag ? "ann.tags" : "seg.speakers")}
                    items={(isTag ? tags : speakers).map((x) => ({ id: x, v: x, lang: "ja" }))}
                    onRemove={(id) => (isTag ? setTags(tags.filter((x) => x !== id)) : setSpeakers(speakers.filter((x) => x !== id)))}
                    testId={isTag ? "ann-tags" : "seg-speakers"}
                  />
                  <div className={s.inline}>
                    <TextField
                      value={draft}
                      onChange={setDraft}
                      onSubmit={addDraft}
                      label={t(isTag ? "ann.addTag" : "seg.addSpeaker")}
                      placeholder={isTag ? t("ann.tagHint") : t("seg.speakerHint")}
                      testId="ann-tag-input"
                    />
                    <Button size="sm" variant="flat" icon={<Plus />} onPress={addDraft} isDisabled={!draft.trim()} aria-label={t(isTag ? "ann.addTag" : "seg.addSpeaker")} />
                  </div>
                </div>
              </>
            ) : null}
            {mode === "create-tag" || (tg?.mode === "edit-tag" && tg.tag.scope !== "asset") ? (
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
              <TimeField value={range.a} label={t("sources.selStart")} testId="ann-start" onCommit={(v) => (v >= 0 && v < range.b ? (setRange({ ...range, a: v }), true) : false)} />
              <span className={s.arrow}>→</span>
              <TimeField
                value={range.b}
                label={t("sources.selEnd")}
                testId="ann-end"
                onCommit={(v) => (v > range.a && v <= props.duration + 1e-6 ? (setRange({ ...range, b: v }), true) : false)}
              />
            </div>
          </>
        )}
      </div>
    </DialogBox>
  );
}
