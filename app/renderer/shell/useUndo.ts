// ⌘Z / ↶：撤销最近资料修改（统一编辑通道，ARCHITECTURE §5）。
import { useCallback } from "react";
import { CoreFailure, call } from "../api/core";
import type { EditLabel } from "../api/types";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { describeLabel } from "./labels";

export function useUndo(): () => Promise<void> {
  const toast = useApp((s) => s.toast);
  return useCallback(async () => {
    try {
      const res = await call<{ label: { args: { of: string; of_args: Record<string, unknown> } } }>("edits.undo");
      const of: EditLabel = { code: res.label.args.of, args: res.label.args.of_args };
      toast({ text: t("undo.done", { label: describeLabel(of) }) });
    } catch (e) {
      if (e instanceof CoreFailure) toast({ text: errorText(e.wire), tone: "error" });
      else throw e;
    }
  }, [toast]);
}
