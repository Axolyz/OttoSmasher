// 本地标签提升为区段标签（规格 07 §7.4、04 §4.3、16 R5.6）：显式操作，预览后应用，可撤销。
// 作用域默认取资产的角色（两个角色时让用户选；没有角色 → 只作用于这个资产，时间用资产局部秒）；时间默认 = 采样选区换算到对应坐标，可改。
// 应用后：本地标签消失，有效标签仍在（改为来自区段）。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { PromoteInfo, SampleRow } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, Segmented } from "../components/Controls";
import { TimeField } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { clock } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import s from "./Library.module.css";

type Info = PromoteInfo;

export function PromoteDialog(props: { sample: SampleRow | null; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const smp = props.sample;
  const local = (smp?.tags ?? []).filter((x) => x.provenance === "local").map((x) => x.tag);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [role, setRole] = useState<"vocal" | "sfx" | null>(null);
  const [needRole, setNeedRole] = useState<Array<"vocal" | "sfx">>([]);
  const [range, setRange] = useState<{ a: number; b: number } | null>(null);
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!smp) return;
    setChosen(new Set(local));
    setRole(null);
    setNeedRole([]);
    setRange(null);
    setInfo(null);
    setError(null);
  }, [smp?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // 每次改选择都重新生成批次并让编辑通道预览（校验）；预览不写库
  useEffect(() => {
    if (!smp || !chosen.size) return setInfo(null);
    let live = true;
    void (async () => {
      try {
        const r = await call("tags.promoteBatch", { sampleId: smp.id, tags: [...chosen], role, start: range?.a, end: range?.b });
        await call("edits.preview", { batch: r.batch });
        if (!live) return;
        setInfo(r);
        setError(null);
        if (!range) setRange({ a: r.start, b: r.end });
      } catch (e) {
        if (!live) return;
        setInfo(null);
        if (e instanceof CoreFailure && e.wire.args.reason === "role-required") {
          // 两个角色：列出来让用户选（先放第一个，确认前可改）
          const roles = e.wire.args.roles as Array<"vocal" | "sfx">;
          setNeedRole(roles);
          setRole(roles[0]!);
        }
        else setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
      }
    })();
    return () => {
      live = false;
    };
  }, [smp?.id, chosen, role, range]); // eslint-disable-line react-hooks/exhaustive-deps

  const apply = async () => {
    if (!info || busy) return;
    setBusy(true);
    try {
      await call("edits.apply", { batch: info.batch });
      toast({ text: t("promote.done", { n: chosen.size }), action: { label: t("common.undo"), run: () => void undo().then(props.onDone) } });
      props.onDone();
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const scopeText = info ? (info.scope === "asset" ? t("promote.scopeAsset") : t(`ann.scope.${info.role}`)) : "";
  return (
    <DialogBox
      isOpen={smp != null}
      onClose={props.onClose}
      title={t("promote.title")}
      sub={smp ? <span data-user-data="">{smp.name}</span> : undefined}
      width={540}
      testId="promote-dialog"
      footer={
        <>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!info || busy} onPress={() => void apply()} data-testid="promote-apply">
            {t("promote.apply")}
          </Button>
        </>
      }
    >
      <Callout>{t("promote.note")}</Callout>
      <div className={s.form}>
        <span className={s.formLabel}>{t("ann.tags")}</span>
        <div>
          {local.map((tag) => (
            <Checkbox
              key={tag}
              isSelected={chosen.has(tag)}
              label={tag}
              onChange={(on) => {
                const n = new Set(chosen);
                if (on) n.add(tag);
                else n.delete(tag);
                setChosen(n);
              }}
            >
              <span data-user-data="">{tag}</span>
            </Checkbox>
          ))}
        </div>
        {needRole.length ? (
          <>
            <span className={s.formLabel}>{t("ann.scope")}</span>
            <div>
              <Segmented<"vocal" | "sfx">
                value={role ?? needRole[0]!}
                onChange={setRole}
                label={t("ann.scope")}
                testId="promote-role"
                options={needRole.map((r) => ({ id: r, label: t(`ann.scope.${r}`) }))}
              />
            </div>
          </>
        ) : null}
        {range ? (
          <>
            <span className={s.formLabel}>{t("ann.time")}</span>
            <div className={s.inline}>
              <TimeField value={range.a} label={t("sources.selStart")} onCommit={(v) => (v >= 0 && v < range.b ? (setRange({ ...range, a: v }), true) : false)} />
              <span>→</span>
              <TimeField value={range.b} label={t("sources.selEnd")} onCommit={(v) => (v > range.a ? (setRange({ ...range, b: v }), true) : false)} />
            </div>
          </>
        ) : null}
      </div>
      {error ? <Callout tone="bad">{error}</Callout> : null}
      {info ? (
        <Callout testId="promote-preview">
          {t("promote.preview", { scope: scopeText, a: clock(info.start), b: clock(info.end), tags: [...chosen].join(t("settings.subtitle.speakerSep")) })}
        </Callout>
      ) : null}
    </DialogBox>
  );
}
