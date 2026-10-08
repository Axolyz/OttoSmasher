// 准备清单（UI_PLAN §4、§8；原型 prepSteps / 「准备 ▾」）：顶栏里的分段进度，点开是锚定小面板——
// 字幕标记、整轨人声分离、默认人声轨、默认音效轨、OP/ED、台词采样（语音分析在阶段 4 加入）。每项写现状并带入口；没有顺序、不强制。
import { ChevronDown } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { call, useCoreEvent } from "../api/core";
import type { Prep, PrepAsset, SourceRow } from "../api/types";
import { Button } from "../components/Button";
import { StepsBar } from "../components/Controls";
import { AnchoredPanel } from "../components/Panel";
import { t } from "../i18n";
import s from "./Sources.module.css";

type AssetRef = PrepAsset;
export type PrepAction = "subimport" | "separate" | "tracks" | "oped" | "subsample";

function assetText(a: AssetRef | null): string {
  if (!a) return "";
  if (a.origin === "stream") return `${t("track.mix")} · ${t("sources.trackN", { n: (a.streamOrdinal ?? 0) + 1 })}`;
  return [a.model, a.stem].filter(Boolean).join(" · ");
}

export function PrepPanel(props: { source: SourceRow; onAction: (a: PrepAction) => void }) {
  const [prep, setPrep] = useState<Prep | null>(null);
  const [open, setOpen] = useState(false);
  const load = useCallback(() => void call("sources.prep", { id: props.source.id }).then(setPrep, () => setPrep(null)), [props.source.id]);
  useEffect(load, [load, props.source.version]);
  useCoreEvent("data.changed", load);
  if (!prep) return null;
  const items: Array<{ key: string; ok: boolean; name: string; state: string; action: PrepAction; label: string; disabled?: boolean }> = [
    {
      key: "sub",
      ok: prep.subtitle.ok,
      name: t("prep.subtitle"),
      state: prep.subtitle.ok ? t("prep.subtitleOk", { n: prep.subtitle.markers }) : t("prep.subtitleNo"),
      action: "subimport",
      label: t("prep.import"),
    },
    { key: "sep", ok: prep.separation.ok, name: t("prep.separation"), state: prep.separation.ok ? assetText(prep.separation.asset) : t("prep.separationNo"), action: "separate", label: t("prep.separate") },
    { key: "dv", ok: prep.defaultVocal.ok, name: t("prep.defaultVocal"), state: prep.defaultVocal.ok ? assetText(prep.defaultVocal.asset) : t("prep.unset"), action: "tracks", label: t("prep.assign") },
    { key: "ds", ok: prep.defaultSfx.ok, name: t("prep.defaultSfx"), state: prep.defaultSfx.ok ? assetText(prep.defaultSfx.asset) : t("prep.unset"), action: "tracks", label: t("prep.assign") },
    { key: "op", ok: prep.oped.ok, name: t("prep.oped"), state: prep.oped.ok ? t("prep.opedOk", { n: prep.oped.count }) : t("prep.opedNo"), action: "oped", label: t("prep.opedAction") },
    {
      key: "ln",
      ok: prep.lineSamples.ok,
      name: t("prep.lineSamples"),
      state: t("prep.lineSamplesN", { n: prep.lineSamples.count }),
      action: "subsample",
      label: t("prep.fromSubtitle"),
      disabled: !prep.subtitle.ok,
    },
  ];
  return (
    <AnchoredPanel
      isOpen={open}
      onOpenChange={setOpen}
      title={t("prep.title")}
      aux={t("prep.note")}
      width={460}
      testId="prep-panel"
      trigger={
        <Button variant="secondary" size="sm" data-testid="prep">
          {t("prep.title")}
          <StepsBar steps={items.map((i) => i.ok)} label={t("prep.title")} />
          <ChevronDown size={13} />
        </Button>
      }
    >
      <div className={s.prepList}>
        {items.map((i) => (
          <div key={i.key} className={s.prepRow} data-ok={i.ok || undefined} data-testid={`prep-${i.key}`}>
            <span className={s.prepDot} />
            <span className={s.prepName}>{i.name}</span>
            <span className={s.prepState} data-user-data="">
              {i.state}
            </span>
            <Button
              size="sm"
              variant="flat"
              isDisabled={i.disabled}
              onPress={() => {
                setOpen(false);
                props.onAction(i.action);
              }}
            >
              {i.label}
            </Button>
          </div>
        ))}
      </div>
    </AnchoredPanel>
  );
}
