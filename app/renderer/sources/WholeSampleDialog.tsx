// 「建立全长采样…」（所有者 2026-10-07）：给一个或多个原片各建一个整段采样（默认音轨、名 = 文件名去扩展名）。
// 性质：按默认音轨的角色预填（人声 → 语音、音效 → 非调谐单音、其他 → 未分类，规格 04 §4.2.7），或统一指定。每次都新建；一批一次事务。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { Nature } from "../api/types";
import { Button } from "../components/Button";
import { Callout, RadioList } from "../components/Controls";
import { NaturePicker } from "../components/NaturePicker";
import { DialogBox } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export function WholeSampleDialog(props: { ids: string[] | null; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const setPage = useApp((st) => st.setPage);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const [mode, setMode] = useState<"auto" | "fixed">("auto");
  const [nature, setNature] = useState<Nature>("unclassified");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (props.ids) setMode("auto");
  }, [props.ids]);

  const run = async () => {
    if (!props.ids || busy) return;
    setBusy(true);
    try {
      const r = await call<{ sampleIds: string[] }>("sources.wholeSamples", { ids: props.ids, nature: mode === "auto" ? null : nature });
      const first = r.sampleIds[0];
      toast({
        text: t("whole.done", { n: r.sampleIds.length }),
        action: first
          ? {
              label: t("sources.openInLibrary"),
              run: () => {
                setOpenSample(first);
                setPage("library");
              },
            }
          : undefined,
      });
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  const n = props.ids?.length ?? 0;
  return (
    <DialogBox
      isOpen={props.ids != null}
      onClose={props.onClose}
      title={t("whole.title")}
      sub={t("whole.sub", { n })}
      width={520}
      testId="whole-dialog"
      footer={
        <>
          <span className={s.grow} />
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={busy} onPress={() => void run()} data-testid="whole-ok">
            {t("whole.ok", { n })}
          </Button>
        </>
      }
    >
      <Callout>{t("whole.note")}</Callout>
      <RadioList
        label={t("nature.label")}
        value={mode}
        onChange={(v) => setMode(v as "auto" | "fixed")}
        testId="whole-mode"
        items={[
          { id: "auto", label: t("whole.auto"), note: t("whole.autoNote") },
          { id: "fixed", label: t("whole.fixed") },
        ]}
      />
      {mode === "fixed" ? <NaturePicker value={nature} onChange={setNature} testId="whole-nature" /> : null}
    </DialogBox>
  );
}
