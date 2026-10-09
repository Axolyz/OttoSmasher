// 管理标签（规格 07 §7.4、16 R8.5；UI_PLAN §8「管理标签：⋯ 菜单 / 命令面板 · 标签右键」；L33）。
// 全部在用的标签按分面列出：采样数（有效标签，按采样计）、本地、区段标签、原片、段（说话人）。
// 每个标签可以「全局改名…」「全局移除…」：作用于带该本地标签的采样、带该标签的区段标签、作品 / 类型匹配的原片、人物对应的段的说话人；
// 预览影响数量（不写库）→ 原子应用 → 可撤销。不允许全局添加。
import { useEffect, useMemo, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { GlobalTagPlan, TagUsage } from "../api/types";
import { Button } from "../components/Button";
import { Callout } from "../components/Controls";
import { TextField } from "../components/Fields";
import { useContextMenu } from "../components/Menu";
import { ConfirmDialog, DialogBox } from "../components/Overlay";
import { PagedTable } from "../components/PagedTable";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { useUndo } from "./useUndo";
import s from "./Shell.module.css";

export function ManageTags() {
  const open = useApp((st) => st.manageTagsOpen);
  const setOpen = useApp((st) => st.setManageTagsOpen);
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const [rows, setRows] = useState<TagUsage[]>([]);
  const [q, setQ] = useState("");
  const [act, setAct] = useState<{ op: "rename" | "remove"; tag: string } | null>(null);
  const [to, setTo] = useState("");
  const [plan, setPlan] = useState<GlobalTagPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const menu = useContextMenu("tag-menu");
  const load = () => void call("tags.list", {}).then(setRows, () => setRows([]));
  useEffect(() => {
    if (open) load();
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows.filter((r) => !needle || r.tag.toLowerCase().includes(needle)).map((r) => ({ ...r, id: r.tag }));
  }, [rows, q]);

  // 预览：改名要等填了新名字
  useEffect(() => {
    setPlan(null);
    setError(null);
    if (!act || (act.op === "rename" && !to.trim())) return;
    const id = setTimeout(() => {
      void call("tags.globalPlan", { op: act.op, tag: act.tag, to: act.op === "rename" ? to.trim() : null }).then(
        (p) => setPlan(p),
        (e) => setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)),
      );
    }, 200);
    return () => clearTimeout(id);
  }, [act, to]);

  const begin = (op: "rename" | "remove", tag: string) => {
    setAct({ op, tag });
    setTo(op === "rename" ? tag : "");
  };
  const apply = async () => {
    if (!plan || !act) return;
    try {
      await call("edits.apply", { batch: plan.batch });
      toast({ text: t(act.op === "rename" ? "tags.renamed" : "tags.removed", { tag: act.tag, to: to.trim() }), action: { label: t("common.undo"), run: () => void undo().then(load) } });
      setAct(null);
      load();
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
      setPlan(null);
    }
  };
  const rp = plan?.report;

  return (
    <>
      <DialogBox isOpen={open} onClose={() => setOpen(false)} title={t("tags.manageTitle")} sub={t("tags.manageSub")} width={760} testId="manage-tags">
        <TextField value={q} onChange={setQ} label={t("tags.search")} placeholder={t("tags.search")} testId="manage-tags-search" />
        <div
          onContextMenu={(e) => {
            const row = (e.target as HTMLElement).closest<HTMLElement>("[data-tag]");
            if (!row) return;
            e.preventDefault();
            const tag = row.dataset.tag!;
            menu.open(e, {
              head: t("menu.on", { name: tag }),
              items: [
                { id: "rename", label: t("tags.renameDots"), run: () => begin("rename", tag) },
                { id: "remove", label: t("tags.removeDots"), danger: true, run: () => begin("remove", tag) },
              ],
            });
          }}
        >
          <PagedTable<TagUsage & { id: string }>
            label={t("tags.manageTitle")}
            rows={shown}
            pageSize={12}
            empty={<span className={s.muted}>{t("tags.none")}</span>}
            columns={[
              {
                id: "tag",
                label: t("tags.col.tag"),
                isRowHeader: true,
                render: (r) => (
                  <span data-tag={r.tag} lang="ja" data-user-data="">
                    <span className={s.muted}>{t(`facet.${r.facet}`)} · </span>
                    {r.tag}
                  </span>
                ),
              },
              { id: "samples", label: t("tags.col.samples"), width: "64px", align: "end", render: (r) => <span className="num">{r.samples}</span> },
              { id: "local", label: t("tags.col.local"), width: "56px", align: "end", render: (r) => <span className="num">{r.local}</span> },
              { id: "range", label: t("tags.col.rangeTags"), width: "56px", align: "end", render: (r) => <span className="num">{r.rangeTags}</span> },
              { id: "src", label: t("tags.col.sources"), width: "56px", align: "end", render: (r) => <span className="num">{r.sources}</span> },
              { id: "seg", label: t("tags.col.segments"), width: "56px", align: "end", render: (r) => <span className="num">{r.segments}</span> },
              {
                id: "ops",
                label: "",
                width: "150px",
                align: "end",
                render: (r) => (
                  <span className={s.rowOps}>
                    <Button size="sm" variant="flat" onPress={() => begin("rename", r.tag)} data-testid="tag-rename">
                      {t("tags.rename")}
                    </Button>
                    <Button size="sm" variant="flat" onPress={() => begin("remove", r.tag)} data-testid="tag-remove">
                      {t("tags.remove")}
                    </Button>
                  </span>
                ),
              },
            ]}
          />
        </div>
        <div className={s.muted}>{t("tags.noGlobalAdd")}</div>
      </DialogBox>
      {menu.node}
      <ConfirmDialog
        isOpen={!!act}
        title={act ? t(act.op === "rename" ? "tags.renameTitle" : "tags.removeTitle", { tag: act.tag }) : ""}
        confirmLabel={t(act?.op === "rename" ? "tags.renameOk" : "tags.removeOk", { n: plan?.changes ?? 0 })}
        danger={act?.op === "remove"}
        confirmDisabled={!plan || !plan.changes}
        onConfirm={() => void apply()}
        onClose={() => setAct(null)}
        testId="tag-global"
      >
        {act?.op === "rename" ? <TextField value={to} onChange={setTo} autoFocus label={t("tags.newName")} testId="tag-new-name" /> : null}
        {rp ? (
          <div className={s.muted} data-testid="tag-global-report">
            {t("tags.report", { samples: rp.samples, rangeTags: rp.rangeTags, sources: rp.sources, segments: rp.segments })}
            {rp.segments && act?.tag.startsWith("participants:") ? ` ${t("tags.speakerNote")}` : null}
            {rp.segments && act?.tag.startsWith("character:") ? ` ${t("tags.speakerNote")}` : null}
          </div>
        ) : null}
        {rp?.folderSources ? <Callout tone="warn">{t("tags.folderSources", { n: rp.folderSources })}</Callout> : null}
        {rp?.derived ? <Callout tone="warn">{t("tags.derived", { n: rp.derived })}</Callout> : null}
        {error ? <Callout tone="bad">{error}</Callout> : null}
        <div className={s.muted}>{t("tags.undoable")}</div>
      </ConfirmDialog>
    </>
  );
}
