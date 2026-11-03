// 批量把分离出的人声设为默认人声轨（所有者 2026-11-03）：分离不自动设默认轨（DECISIONS §9），这里是用户明确点的那一步。
// 列出所选原素材里已有的“模型 · 人声声部”，选一个 → 有它的原素材都改用它，一次可撤销；没有它的不动。
import { useEffect, useState } from "react";
import { CoreFailure, call } from "../api/core";
import type { SeparatedVocalOption } from "../api/types";
import { Button } from "../components/Button";
import { Callout, RadioList } from "../components/Controls";
import { DialogBox } from "../components/Overlay";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";

const keyOf = (o: SeparatedVocalOption) => `${o.model}\n${o.stem}`;

export function SeparatedVocalDialog(props: { sourceIds: string[] | null; onClose: () => void; onDone: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const ids = props.sourceIds;
  const [options, setOptions] = useState<SeparatedVocalOption[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setOptions(null);
    setPicked(null);
    if (!ids) return;
    void call("tracks.separatedVocals", { sourceIds: ids }).then((list) => {
      setOptions(list);
      setPicked(list[0] ? keyOf(list[0]) : null); // 按覆盖的原素材数排序，第一个覆盖最多
    });
  }, [ids]);

  const chosen = options?.find((o) => keyOf(o) === picked) ?? null;
  const run = async () => {
    if (!ids || !chosen || busy) return;
    setBusy(true);
    try {
      const r = await call("tracks.defaultFromSeparation", { sourceIds: ids, model: chosen.model, stem: chosen.stem });
      toast({
        text: t("tracks.separatedDone", { n: r.applied, m: r.skipped }),
        action: r.edit_id ? { label: t("common.undo"), run: () => void undo() } : undefined,
      });
      props.onDone();
      props.onClose();
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogBox
      isOpen={ids != null}
      onClose={props.onClose}
      title={t("tracks.separatedTitle")}
      sub={t("tracks.separatedSub", { n: ids?.length ?? 0 })}
      width={560}
      testId="separated-vocal"
      footer={
        <>
          <Button variant="flat" onPress={props.onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" isDisabled={!chosen || busy} onPress={() => void run()} data-testid="separated-vocal-run">
            {t("tracks.separatedRun", { n: chosen?.sources ?? 0 })}
          </Button>
        </>
      }
    >
      {options && !options.length ? <Callout tone="warn">{t("tracks.separatedNone")}</Callout> : null}
      {options?.length ? (
        <RadioList
          label={t("tracks.separatedTitle")}
          value={picked}
          onChange={setPicked}
          testId="separated-vocal-options"
          items={options.map((o) => ({
            id: keyOf(o),
            label: `${o.model} · ${o.stem}`,
            note: t("tracks.separatedCount", { n: o.sources, total: ids?.length ?? 0 }),
          }))}
        />
      ) : null}
    </DialogBox>
  );
}
