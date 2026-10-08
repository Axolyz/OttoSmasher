// 分离（PyMSS Studio）确认框（规格 05 §5.5、14 §14.6；UI_PLAN §5、§8 分离行；原型 sepModal）：
// 范围（整片连续音轨 / 当前选区）→ 模型（整片：人声模型与三轨模型；选区：任意已下载模型）→ 保留声部（空 = 全部）→「排队分离」。
// 输入与设备在提交时冻结；结果是新的声音资产，不自动保存为采样、不自动设为默认轨；同输入同模型已有结果时直接复用。
import { useEffect, useMemo, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { SettingEntry, StudioModel, StudioStatus } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox, RadioList, Segmented } from "../components/Controls";
import { DialogBox } from "../components/Overlay";
import { clock, seconds } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

type Scope = "full" | "sel";

/** 分离确认框（挂在应用外壳上；原片页与舞台的动作条都通过 store.requestSeparation 打开） */
export function SeparationDialog() {
  const input = useApp((st) => st.separationRequest);
  const requestSeparation = useApp((st) => st.requestSeparation);
  const props = { input, onClose: () => requestSeparation(null) };
  const toast = useApp((st) => st.toast);
  const setTasksOpen = useApp((st) => st.setTasksOpen);
  const inp = props.input;
  const [status, setStatus] = useState<StudioStatus | null>(null);
  const [scope, setScope] = useState<Scope>("full");
  const [model, setModel] = useState<string | null>(null);
  const [stems, setStems] = useState<Set<string>>(new Set());
  const [settings, setSettings] = useState<Record<string, SettingEntry>>({});
  const [busy, setBusy] = useState(false);

  const load = async () => setStatus(await call("studio.status"));
  useEffect(() => {
    if (!inp) return;
    setScope(inp.scope === "sel" && inp.selection ? "sel" : "full");
    setStems(new Set());
    void load();
    void call("settings.list").then(setSettings);
  }, [inp]); // eslint-disable-line react-hooks/exhaustive-deps
  // 列模型任务完成后刷新
  useCoreEvent("job.updated", (d) => {
    const j = d as { id: string; status: string };
    if (status?.listingJob === j.id && j.status !== "queued" && j.status !== "running") void load();
  });

  const preferred = String(settings["studio.vocal_model"]?.value ?? "");
  const models = useMemo(() => {
    const all = status?.models ?? [];
    return scope === "full" ? all.filter((m) => m.vocal || m.threeTrack) : all;
  }, [status, scope]);
  const missingPreferred = preferred && status?.models && !status.models.some((m) => m.name === preferred || m.aliases.includes(preferred));
  useEffect(() => {
    // 默认取设置里的默认人声模型；不在可用列表里就不选（不自动替换）
    const hit = models.find((m) => m.name === preferred || m.aliases.includes(preferred));
    setModel((cur) => (cur && models.some((m) => m.name === cur) ? cur : hit ? hit.name : null));
  }, [models, preferred]);
  const chosen = models.find((m) => m.name === model) ?? null;

  const submit = async () => {
    if (!inp || !chosen || busy) return;
    setBusy(true);
    try {
      const range = scope === "sel" && inp.selection ? { start: inp.selection.a, end: inp.selection.b } : {};
      const r = await call("separation.submit", {
        assetId: inp.assetId,
        model: chosen.name,
        stems: stems.size ? chosen.stems.filter((x) => stems.has(x)) : null,
        ...range,
      });
      if (r.reused) toast({ text: t("sep.reused", { n: r.reused.length }) });
      else {
        toast({ text: t("sep.queued", { model: chosen.name }), action: { label: t("sep.openTasks"), run: () => setTasksOpen(true) } });
      }
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const aliases = (settings["separation.role_aliases"]?.value as Array<[string, string]> | undefined) ?? [];
  const prefill = chosen
    ? chosen.stems.flatMap((st) => aliases.filter(([n]) => n.toLowerCase() === st.toLowerCase()).map(([, r]) => `${st} → ${t(`role.${r}`)}`))
    : [];
  const device = String(settings["studio.device"]?.value ?? "auto");
  const inputText = !inp
    ? ""
    : scope === "full"
      ? t("sep.inputFull", { end: seconds(inp.duration), track: inp.trackLabel })
      : t("sep.inputSel", { a: clock(inp.selection?.a), b: clock(inp.selection?.b), track: inp.trackLabel });

  return (
    <DialogBox
      isOpen={inp != null}
      onClose={props.onClose}
      title={t("sep.title")}
      sub={inputText}
      width={600}
      testId="sep-dialog"
      footer={
        <>
          <span className={s.sheetNote}>
            {t("sep.footer", { device: t(`settings.studio.device.${device}`) })}
            {prefill.length ? ` · ${t("sep.prefill", { list: prefill.join(t("settings.subtitle.speakerSep")) })}` : ""}
          </span>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!chosen || busy} onPress={() => void submit()} data-testid="sep-submit">
            {t("sep.submit")}
          </Button>
        </>
      }
    >
      <Callout>{t("sep.note")}</Callout>
      {status && !status.ok && status.error ? (
        <Callout tone="bad" testId="sep-studio-error">
          {errorText(status.error)}
        </Callout>
      ) : null}
      <Segmented<Scope>
        value={scope}
        onChange={setScope}
        label={t("sep.scope")}
        options={[
          { id: "full", label: t("sep.scopeFull") },
          { id: "sel", label: t("sep.scopeSel"), isDisabled: !inp?.selection },
        ]}
      />
      {status?.ok && status.models == null ? <div className={s.muted}>{t("sep.listing")}</div> : null}
      {missingPreferred ? <Callout tone="warn">{t("sep.preferredMissing", { model: preferred })}</Callout> : null}
      {status?.models ? (
        models.length ? (
          <RadioList
            label={t("sep.model")}
            value={model}
            onChange={(v) => {
              setModel(v);
              setStems(new Set());
            }}
            testId="sep-models"
            items={models.map((m) => ({
              id: m.name,
              label: `${m.name} · ${m.stems.join(" | ")}`,
              note: [m.name === preferred || m.aliases.includes(preferred) ? t("sep.preferred") : "", m.threeTrack ? t("sep.threeTrack") : ""].filter(Boolean).join(" · "),
            }))}
          />
        ) : (
          <Callout tone="warn">{t(scope === "full" ? "sep.noModelsFull" : "sep.noModels")}</Callout>
        )
      ) : null}
      {chosen ? (
        <div className={s.opedBar}>
          <span className={s.groupLabel}>{t("sep.stems")}</span>
          {chosen.stems.map((st) => (
            <Checkbox
              key={st}
              isSelected={stems.has(st)}
              onChange={(on) => setStems((x) => {
                const n = new Set(x);
                if (on) n.add(st);
                else n.delete(st);
                return n;
              })}
              label={st}
            >
              {st}
            </Checkbox>
          ))}
          <span className={s.muted}>{t("sep.stemsAll")}</span>
        </div>
      ) : null}
    </DialogBox>
  );
}
