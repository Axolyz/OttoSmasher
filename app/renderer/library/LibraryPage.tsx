// 采样库（UI_PLAN §2；阶段 2 最小版）：用途切换、查找栏（文字 + ★）、结果头（数量、分页）、列表、右侧最小舞台。
// 集合规则（UI_PLAN §6.1）：单击 = 焦点，从不改变勾选；复选框 / ⌘+单击切换勾选；Shift+单击连续勾选；⌘A 勾选全部匹配（跨页）；
// Esc 清空勾选；↑↓ 移动焦点；Space 试听焦点（左键原声；卡拍在阶段 6）；1/2/3/0 一步设性质（勾选集或焦点，可撤销，
// 改完该行留在原位、刷新后按新性质归位）；Delete 删除（确认）。条件变化清空勾选并提示。翻页保留勾选。
import { ArrowUpRight, ChevronLeft, ChevronRight, Play, Square, SquareStack, Star, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PlayerState } from "../../shared/protocol";
import { CoreFailure, call } from "../api/core";
import type { Nature, SamplePage, SampleRow } from "../api/types";
import { Button } from "../components/Button";
import { TextField } from "../components/Fields";
import { NATURE_KEYS, NatureDot, NaturePicker } from "../components/NaturePicker";
import { ConfirmDialog } from "../components/Overlay";
import { clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import shell from "../shell/Shell.module.css";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Library.module.css";

const PAGE = 100;
type Purpose = "all" | Nature;
const PURPOSES: Purpose[] = ["all", "speech", "pitched", "unpitched", "unclassified"];

function isTyping(el: Element | null): boolean {
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || (el as HTMLElement).isContentEditable);
}

export function LibraryPage() {
  const ready = useApp((st) => st.core.state === "ready");
  const page = useApp((st) => st.page);
  const toast = useApp((st) => st.toast);
  const openSample = useApp((st) => st.openSample);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const setPage = useApp((st) => st.setPage);
  const setSourceJump = useApp((st) => st.setSourceJump);
  const undo = useUndo();
  const [purpose, setPurpose] = useState<Purpose>("all");
  const [text, setText] = useState("");
  const [starredOnly, setStarredOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<SamplePage | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [playing, setPlaying] = useState<string | null>(null);
  const [deleteIds, setDeleteIds] = useState<string[] | null>(null);
  const [focusRow, setFocusRow] = useState<SampleRow | null>(null);
  const anchor = useRef<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const auditionGen = useRef(-1);

  const query = useMemo(
    () => ({ natures: purpose === "all" ? undefined : [purpose], starred: starredOnly, text }),
    [purpose, starredOnly, text],
  );

  const load = useCallback(
    async (off: number) => {
      const r = await call<SamplePage>("samples.list", { ...query, offset: off, limit: PAGE });
      setData(r);
      return r;
    },
    [query],
  );

  // 条件变化：回到第一页，清空勾选并提示（UI_PLAN §6.1）
  const firstQuery = useRef(true);
  useEffect(() => {
    if (!ready) return;
    setOffset(0);
    void load(0);
    if (firstQuery.current) {
      firstQuery.current = false;
      return;
    }
    setChecked((c) => {
      if (c.size) toast({ text: t("library.checkCleared", { n: c.size }) });
      return new Set();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, query]);

  // 切回本页时刷新（资料可能在别处变了：新截取、删除原片）
  useEffect(() => {
    if (page === "library" && ready) void load(offset);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  // 截取后打开新采样
  useEffect(() => {
    if (!openSample || !ready) return;
    void (async () => {
      const r = await call<SamplePage>("samples.list", { offset: 0, limit: PAGE });
      setPurpose("all");
      setText("");
      setStarredOnly(false);
      setOffset(0);
      setData(r);
      setFocus(openSample);
      setOpenSample(null);
      listRef.current?.focus();
    })();
  }, [openSample, ready, setOpenSample]);

  // 焦点采样的资料（舞台）
  useEffect(() => {
    if (!focus) return setFocusRow(null);
    const inPage = data?.rows.find((r) => r.id === focus);
    if (inPage) setFocusRow(inPage);
    else void call<SampleRow>("samples.get", { id: focus }).then(setFocusRow, () => setFocusRow(null));
  }, [focus, data]);

  // 试听状态
  useEffect(
    () =>
      window.otto.player.onState((st: PlayerState) => {
        if (st.player !== "audition" || st.gen !== auditionGen.current) return;
        if (st.ended || st.error || !st.playing) {
          if (st.ended || st.error) setPlaying(null);
        }
      }),
    [],
  );

  const rows = data?.rows ?? [];
  const audition = async (r: SampleRow) => {
    if (playing === r.id) {
      window.otto.player.stopAudition();
      setPlaying(null);
      return;
    }
    try {
      setPlaying(r.id);
      auditionGen.current = await window.otto.player.audition(r.asset_id, r.start, r.end);
    } catch (e) {
      setPlaying(null);
      toast({ text: errorText(e as { code: string; args: Record<string, unknown> }), tone: "error" });
    }
  };

  const edit = async (ids: string[], fields: Record<string, unknown>, label: string) => {
    const targets = rows.filter((r) => ids.includes(r.id));
    const missing = ids.filter((id) => !targets.some((r) => r.id === id));
    const extra = await Promise.all(missing.map((id) => call<SampleRow>("samples.get", { id })));
    const all = [...targets, ...extra];
    try {
      await call("edits.apply", {
        batch: { label: { code: label, args: { n: all.length } }, ops: all.map((r) => ({ entity: "sample", id: r.id, version: r.version, fields })) },
      });
      // 就地更新，不重排（改完该行留在原位，刷新后按新条件归位）
      setData((d) => d && { ...d, rows: d.rows.map((r) => (ids.includes(r.id) ? { ...r, ...fields, version: r.version + 1 } : r)) });
      toast({ text: t("library.edited", { n: all.length }), action: { label: t("common.undo"), run: () => void undo().then(() => load(offset)) } });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
      void load(offset);
    }
  };

  const targetIds = () => (checked.size ? [...checked] : focus ? [focus] : []);

  const toggle = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    anchor.current = id;
    setChecked(next);
  };
  const extend = (id: string) => {
    const from = rows.findIndex((r) => r.id === (anchor.current ?? focus));
    const to = rows.findIndex((r) => r.id === id);
    if (from < 0 || to < 0) return toggle(id);
    const next = new Set(checked);
    for (const r of rows.slice(Math.min(from, to), Math.max(from, to) + 1)) next.add(r.id);
    setChecked(next);
  };

  const onKey = async (e: React.KeyboardEvent) => {
    if (isTyping(document.activeElement)) return;
    const idx = rows.findIndex((r) => r.id === focus);
    const k = e.key;
    if (k === "ArrowDown" || k === "ArrowUp") {
      e.preventDefault();
      const next = rows[Math.max(0, Math.min(rows.length - 1, idx + (k === "ArrowDown" ? 1 : -1)))];
      if (next) {
        setFocus(next.id);
        if (e.shiftKey) setChecked((c) => new Set(c).add(next.id));
      }
    } else if (k === " ") {
      e.preventDefault();
      const r = rows[idx];
      if (r) void audition(r);
    } else if (k in NATURE_KEYS && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      const ids = targetIds();
      if (ids.length) void edit(ids, { nature: NATURE_KEYS[k] }, "sample-nature");
    } else if (k === "Escape" && checked.size) {
      e.preventDefault();
      e.stopPropagation();
      setChecked(new Set());
    } else if ((k === "a" || k === "A") && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      setChecked(new Set(await call<string[]>("samples.ids", query)));
    } else if (k === "Delete" || k === "Backspace") {
      e.preventDefault();
      const ids = targetIds();
      if (ids.length) setDeleteIds(ids);
    }
  };

  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const pageNo = Math.floor(offset / PAGE) + 1;
  const goto = (p: number) => {
    const off = (Math.max(1, Math.min(pages, p)) - 1) * PAGE;
    setOffset(off);
    void load(off);
  };

  const removeConfirmed = async () => {
    if (!deleteIds) return;
    try {
      const r = await call<{ deleted: number }>("samples.delete", { ids: deleteIds });
      toast({ text: t("library.deleted", { n: r.deleted }) });
      setChecked((c) => new Set([...c].filter((id) => !deleteIds.includes(id))));
      if (focus && deleteIds.includes(focus)) setFocus(null);
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setDeleteIds(null);
      void load(offset);
    }
  };

  const backToSource = (r: SampleRow) => {
    if (r.source_start == null) return;
    const len = r.end - r.start;
    setSourceJump({ sourceId: r.source_id, ordinal: r.stream_ordinal, a: r.source_start, b: r.source_start + len });
    setPage("sources");
  };

  return (
    <div className={s.page} data-testid="page-library">
      <section className={s.left}>
        <div className={s.purposes} role="tablist">
          {PURPOSES.map((p) => (
            <button
              key={p}
              type="button"
              role="tab"
              aria-selected={purpose === p}
              className={s.purpose}
              data-on={purpose === p || undefined}
              onClick={() => setPurpose(p)}
              data-testid={`purpose-${p}`}
            >
              {p !== "all" ? <NatureDot nature={p} /> : null}
              {p === "all" ? t("library.all") : t(`nature.${p}`)}
            </button>
          ))}
        </div>
        <div className={s.find}>
          <TextField value={text} onChange={setText} label={t("library.search")} placeholder={t("library.search")} testId="library-search" />
          <Button
            variant={starredOnly ? "primary" : "secondary"}
            icon={<Star />}
            onPress={() => setStarredOnly((v) => !v)}
            aria-label={t("library.starredOnly")}
            aria-pressed={starredOnly}
          />
        </div>
        <div className={s.resultHead}>
          <span data-testid="library-total">{t("library.total", { n: total })}</span>
          <span className={s.grow} />
          <Button size="sm" variant="flat" icon={<ChevronLeft />} isDisabled={pageNo <= 1} onPress={() => goto(pageNo - 1)} aria-label={t("library.prev")} />
          <span className="num">
            {pageNo} / {pages}
          </span>
          <Button size="sm" variant="flat" icon={<ChevronRight />} isDisabled={pageNo >= pages} onPress={() => goto(pageNo + 1)} aria-label={t("library.next")} />
        </div>
        <div className={s.list} ref={listRef} tabIndex={0} onKeyDown={(e) => void onKey(e)} data-testid="sample-list">
          {data && !rows.length ? (
            <div className={shell.empty}>
              <SquareStack size={36} strokeWidth={1.2} />
              <h3>{t(total || text || starredOnly || purpose !== "all" ? "library.noMatch" : "library.empty.title")}</h3>
              <div>{t("library.empty.body")}</div>
            </div>
          ) : null}
          {rows.map((r) => (
            <div
              key={r.id}
              className={s.row}
              data-testid="sample-row"
              data-id={r.id}
              data-focus={r.id === focus || undefined}
              data-nature={r.nature}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey) toggle(r.id);
                else if (e.shiftKey) extend(r.id);
                else {
                  anchor.current = r.id;
                  setFocus(r.id);
                }
              }}
              onDoubleClick={() => void audition(r)}
            >
              <input
                type="checkbox"
                checked={checked.has(r.id)}
                onClick={(e) => e.stopPropagation()}
                onChange={() => toggle(r.id)}
                aria-label={t("library.check", { name: r.name })}
              />
              <button
                type="button"
                className={s.play}
                data-playing={playing === r.id || undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  void audition(r);
                }}
                aria-label={playing === r.id ? t("library.stop") : t("library.audition")}
                data-testid="sample-play"
              >
                {playing === r.id ? <Square size={12} /> : <Play size={12} />}
              </button>
              <div className={s.body}>
                <div className={s.name} lang={r.language ?? "ja"} title={r.name} data-user-data="">
                  {r.name}
                </div>
                <div className={s.meta}>
                  <NatureDot nature={r.nature} />
                  <span>{r.created_via === "manual" ? t("library.manualUnanalyzed") : t(`nature.${r.nature}`)}</span>
                  <span className={s.src} data-user-data="">
                    {r.source_name} · {clock(r.source_start)}
                  </span>
                  <span className={`${s.dur} num`}>{t("format.sec", { v: seconds(r.duration) })}</span>
                </div>
              </div>
              <button
                type="button"
                className={s.star}
                data-on={r.starred || undefined}
                onClick={(e) => {
                  e.stopPropagation();
                  void edit([r.id], { starred: !r.starred }, "sample-star");
                }}
                aria-label={t("library.star")}
              >
                <Star size={14} />
              </button>
            </div>
          ))}
        </div>
        {checked.size ? (
          <div className={s.checkedBar} data-testid="library-checked">
            {t("library.checkedN", { n: checked.size })}
            <Button size="sm" variant="flat" onPress={async () => setChecked(new Set(await call<string[]>("samples.ids", query)))}>
              {t("library.checkAll", { n: total })}
            </Button>
            <span className={s.grow} />
            <Button size="sm" variant="danger" icon={<Trash2 />} onPress={() => setDeleteIds([...checked])}>
              {t("library.delete")}
            </Button>
            <Button size="sm" variant="flat" icon={<X />} onPress={() => setChecked(new Set())} aria-label={t("sources.clearChecked")} />
          </div>
        ) : null}
      </section>
      <section className={s.stage} data-testid="stage">
        {focusRow ? (
          <>
            <h2 className={s.stageTitle} lang={focusRow.language ?? "ja"} data-testid="stage-title" data-user-data="">
              {focusRow.name}
            </h2>
            <div className={s.stageMeta}>
              <span className="num">{t("format.sec", { v: seconds(focusRow.duration) })}</span>
              <span data-user-data="">
                {focusRow.source_name} · {clock(focusRow.source_start)}
              </span>
              <Button size="sm" variant="flat" icon={<ArrowUpRight />} onPress={() => backToSource(focusRow)} isDisabled={focusRow.source_start == null} data-testid="back-to-source">
                {t("library.backToSource")}
              </Button>
            </div>
            <NaturePicker
              value={focusRow.nature}
              onChange={(n) => void edit([focusRow.id], { nature: n }, "sample-nature")}
              testId="stage-nature"
            />
            <div className={s.stageActions}>
              <Button variant="primary" icon={playing === focusRow.id ? <Square /> : <Play />} onPress={() => void audition(focusRow)}>
                {playing === focusRow.id ? t("library.stop") : t("library.audition")}
              </Button>
              <Button variant="danger" icon={<Trash2 />} onPress={() => setDeleteIds([focusRow.id])}>
                {t("library.delete")}
              </Button>
            </div>
            {focusRow.parent_label && !focusRow.parent_sample_id ? <div className={s.note}>{t("library.parentDeleted", { name: focusRow.parent_label })}</div> : null}
            <div className={s.note}>{t("library.stageLater")}</div>
          </>
        ) : (
          <div className={shell.empty}>
            <div>{t("library.pickHint")}</div>
          </div>
        )}
      </section>
      <ConfirmDialog
        isOpen={!!deleteIds}
        title={t("library.deleteTitle", { n: deleteIds?.length ?? 0 })}
        confirmLabel={t("library.delete")}
        danger
        onConfirm={() => void removeConfirmed()}
        onClose={() => setDeleteIds(null)}
        testId="sample-delete"
      >
        <div>{t("library.deleteWill")}</div>
        <div className={s.keep}>{t("library.deleteKeeps")}</div>
      </ConfirmDialog>
    </div>
  );
}
