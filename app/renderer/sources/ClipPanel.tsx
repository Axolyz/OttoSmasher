// 建一个采样（所有者 2026-10-09：建采样是一个动作——单条用这个锚定小面板（原「截取」），批量用整页表格；背后同一个 samples.plan，规则与产物完全相同）。
// 来源：选区（截取 / 详情区里截取 / 命中保存）、文本层的一段、一条音效提示、分离声部。
// 面板：标题 + 区间、音源（段 / 提示可选“默认轨”或“当前查看的轨”）；名称（按规则预填，可改）+ 性质（按来源预填，可改）+ 判定区间 + 保存。
// 显式保存一律新建（R7.1）；保存后跳到采样库打开新采样（命中保存不跳，afterSave 决定）。Enter 保存，Esc 关闭。
import { Scissors } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { Nature, SamplePlan, SamplePlanSource } from "../api/types";
import { Button } from "../components/Button";
import { Segmented } from "../components/Controls";
import { TextArea, TextField } from "../components/Fields";
import { NaturePicker } from "../components/NaturePicker";
import { AnchoredPanel } from "../components/Panel";
import { clock } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export function ClipPanel(props: {
  /** 规划来源：给了就用它；没给就用 assetId + sel（选区） */
  from?: SamplePlanSource | null;
  assetId: string | null;
  track: string;
  sel: { a: number; b: number } | null;
  isOpen: boolean;
  onOpenChange: (o: boolean) => void;
  /** 命中保存：记为 hit */
  via?: "manual" | "hit";
  /** 区间的显示：原片页用原片时钟；舞台用秒 */
  formatRange?: (a: number, b: number) => string;
  /** 段 / 提示：当前查看的轨（可选“在当前轨上建”） */
  currentAsset?: { id: string; label: string } | null;
  /** 保存后做什么（给了就不弹默认提示）；默认 = 提示并打开新采样（跳到采样库） */
  afterSave?: (id: string, name: string) => void;
  trigger?: ReactNode;
  /** 从右键菜单打开：贴着指针位置出现（没有按钮） */
  at?: { x: number; y: number } | null;
}) {
  const toast = useApp((st) => st.toast);
  const setPage = useApp((st) => st.setPage);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const [plan, setPlan] = useState<SamplePlan | null>(null);
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [nature, setNature] = useState<Nature>("unclassified");
  const [track, setTrack] = useState<"default" | "current">("default");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fromKind = props.from?.kind;
  const ranged = fromKind === "segments" || fromKind === "hints";
  const source = (tr = track): SamplePlanSource | null => {
    if (props.from) return ranged ? { ...props.from, track: tr, assetId: tr === "current" ? (props.currentAsset?.id ?? null) : null } : props.from;
    if (!props.assetId || !props.sel) return null;
    return { kind: "selection", assetId: props.assetId, start: props.sel.a, end: props.sel.b, via: props.via ?? "manual", localMarker: t("naming.local") };
  };

  const load = (tr = track) => {
    const src = source(tr);
    if (!src) return;
    setError(null);
    call("samples.plan", { from: src })
      .then((p) => {
        setPlan(p);
        const it = p.items[0];
        if (it) {
          setName(it.name);
          setNature(it.nature);
        }
        if (p.missingDefault) setError(t(`subsample.missing.${p.missingDefault}`));
        else if (it && it.status !== "pending") setError(t(`subsample.status.${it.status}`));
      })
      .catch((e) => setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)));
  };
  useEffect(() => {
    if (!props.isOpen) setTags("");
  }, [props.isOpen]);
  useEffect(() => {
    if (!props.isOpen) return;
    // 段默认建在默认人声轨上；提示默认在当前查看的轨上（批量才默认音效轨）
    const tr = fromKind === "hints" && props.currentAsset ? "current" : "default";
    setTrack(tr);
    setPlan(null);
    load(tr);
  }, [props.isOpen, props.assetId, props.sel?.a, props.sel?.b, JSON.stringify(props.from ?? null)]); // eslint-disable-line react-hooks/exhaustive-deps

  const item = plan?.items[0] ?? null;
  const save = async () => {
    const src = source();
    if (!src || !plan || !item || item.status !== "pending" || plan.missingDefault || !name.trim() || busy) return;
    setBusy(true);
    try {
      const localTags = tags.split(/\r?\n/).map((tag) => tag.trim()).filter(Boolean);
      const r = await call("samples.createPlanned", {
        from: src, token: plan.token, keys: [item.key], overrides: { [item.key]: { name, nature, localTags } },
      });
      const id = r.ids[0]!;
      props.onOpenChange(false);
      if (props.afterSave) props.afterSave(id, name);
      else {
        toast({ text: t("clip.saved", { name }) });
        setOpenSample(id);
        setPage("library");
      }
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
      if (e instanceof CoreFailure && e.wire.code === "sample-plan-stale") load();
    } finally {
      setBusy(false);
    }
  };

  const aux = item
    ? props.formatRange
      ? props.formatRange(item.start, item.end)
      : ranged && item.sourceStart != null
        ? `${clock(item.sourceStart)}–${clock(item.sourceEnd ?? item.sourceStart)}`
        : `${clock(item.start)}–${clock(item.end)}`
    : props.sel
      ? props.formatRange
        ? props.formatRange(props.sel.a, props.sel.b)
        : `${clock(props.sel.a)}–${clock(props.sel.b)}`
      : null;
  const roles = plan?.track?.roles ?? [];
  return (
    <AnchoredPanel
      isOpen={props.isOpen}
      onOpenChange={props.onOpenChange}
      title={t(ranged ? `clip.title.${fromKind}` : fromKind === "stem" ? "clip.title.stem" : "clip.title")}
      aux={aux}
      placement={props.at ? "bottom start" : "top start"}
      width={440}
      testId="clip-panel"
      at={props.at}
      trigger={
        props.at
          ? undefined
          : (props.trigger ?? (
              <Button variant="flat" icon={<Scissors />} isDisabled={!props.sel || !props.assetId} data-testid="clip">
                {t("sources.clip")}
              </Button>
            ))
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
        className={s.clipForm}
      >
        {ranged && props.currentAsset ? (
          <Segmented<"default" | "current">
            size="sm"
            label={t("newsamples.track")}
            value={track}
            onChange={(v) => {
              setTrack(v);
              load(v);
            }}
            options={[
              { id: "default", label: t(`newsamples.trackDefault.${fromKind === "hints" ? "sfx" : "vocal"}`) },
              { id: "current", label: t("newsamples.trackCurrent", { track: props.currentAsset.label }) },
            ]}
            testId="clip-track"
          />
        ) : (
          <div className={s.clipSource} data-user-data="">
            {t("clip.source", { track: props.track })}
          </div>
        )}
        <TextField value={name} onChange={setName} label={t("clip.name")} testId="clip-name" />
        <NaturePicker value={nature} onChange={setNature} testId="clip-nature" />
        <TextArea value={tags} onChange={setTags} label={t("batch.field.local_tags")} placeholder={t("clip.tagsHint")} testId="clip-tags" />
        <div className={s.clipHint}>
          {roles.length ? t("clip.roles", { roles: roles.map((r) => t(`role.${r}`)).join(" + ") }) : t("clip.noRoles")}
          {item?.judgeStart != null && item.judgeEnd != null ? ` · ${t("clip.judge", { a: clock(item.judgeStart), b: clock(item.judgeEnd) })}` : ""}
        </div>
        {error ? <div className={s.warn}>{error}</div> : null}
        <div className={s.clipActions}>
          <Button variant="flat" onPress={() => props.onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" type="submit" isDisabled={busy || !name.trim() || !item || item.status !== "pending" || !!plan?.missingDefault} data-testid="clip-save">
            {t("clip.save")}
          </Button>
        </div>
      </form>
    </AnchoredPanel>
  );
}
