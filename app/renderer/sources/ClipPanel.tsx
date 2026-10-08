// 截取（UI_PLAN §5 锚定小面板、§8 入口表）：标题 + 区间、音源；名称（建议名，可改）+ 性质（按资产角色预填，可改）+ 保存。
// 显式保存一律新建（R7.1）；保存后跳到采样库打开新采样。Enter 保存，Esc 关闭。
import { Scissors } from "lucide-react";
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { Nature, SampleRow, SampleSuggestion } from "../api/types";
import { Button } from "../components/Button";
import { TextField } from "../components/Fields";
import { NaturePicker } from "../components/NaturePicker";
import { AnchoredPanel } from "../components/Panel";
import { clock } from "../format";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export function ClipPanel(props: { assetId: string | null; track: string; sel: { a: number; b: number } | null; isOpen: boolean; onOpenChange: (o: boolean) => void }) {
  const toast = useApp((st) => st.toast);
  const setPage = useApp((st) => st.setPage);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const [name, setName] = useState("");
  const [nature, setNature] = useState<Nature>("unclassified");
  const [hint, setHint] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!props.isOpen || !props.assetId || !props.sel) return;
    setError(null);
    call("samples.suggest", { assetId: props.assetId, start: props.sel.a, end: props.sel.b, localMarker: t("naming.local") })
      .then((sg) => {
        setName(sg.name);
        setNature(sg.nature);
        setHint(sg.roles.length ? t("clip.roles", { roles: sg.roles.map((r) => t(`role.${r}`)).join(" + ") }) : t("clip.noRoles"));
      })
      .catch((e) => setError(e instanceof CoreFailure ? errorText(e.wire) : String(e)));
  }, [props.isOpen, props.assetId, props.sel]);

  const save = async () => {
    if (!props.assetId || !props.sel || busy) return;
    setBusy(true);
    try {
      const smp = await call("samples.create", { assetId: props.assetId, start: props.sel.a, end: props.sel.b, name, nature });
      props.onOpenChange(false);
      toast({ text: t("clip.saved", { name: smp.name }) });
      setOpenSample(smp.id);
      setPage("library");
    } catch (e) {
      setError(e instanceof CoreFailure ? errorText(e.wire) : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnchoredPanel
      isOpen={props.isOpen}
      onOpenChange={props.onOpenChange}
      title={t("clip.title")}
      aux={props.sel ? `${clock(props.sel.a)}–${clock(props.sel.b)}` : null}
      placement="top start"
      width={420}
      testId="clip-panel"
      trigger={
        <Button variant="flat" icon={<Scissors />} isDisabled={!props.sel || !props.assetId} data-testid="clip">
          {t("sources.clip")}
        </Button>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
        className={s.clipForm}
      >
        <div className={s.clipSource} data-user-data="">
          {t("clip.source", { track: props.track })}
        </div>
        <TextField value={name} onChange={setName} label={t("clip.name")} testId="clip-name" />
        <NaturePicker value={nature} onChange={setNature} testId="clip-nature" />
        <div className={s.clipHint}>{hint}</div>
        {error ? <div className={s.warn}>{error}</div> : null}
        <div className={s.clipActions}>
          <Button variant="flat" onPress={() => props.onOpenChange(false)}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" type="submit" isDisabled={busy || !name.trim()} data-testid="clip-save">
            {t("clip.save")}
          </Button>
        </div>
      </form>
    </AnchoredPanel>
  );
}
