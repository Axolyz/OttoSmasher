// 工具页（UI_PLAN §9 PA5）：脚本批量入口是 P2（阶段 11）。这里另放组件样张和开发用的任务自检。
import { useState } from "react";
import { CoreFailure, call } from "../api/core";
import { Button } from "../components/Button";
import { errorText, t } from "../i18n";
import { useApp } from "../state/store";
import { ProbePanel } from "./ProbePanel";
import { Specimen } from "./Specimen";
import s from "./Tools.module.css";

export function ToolsPage() {
  const dev = useApp((st) => st.hello?.dev ?? false);
  const toast = useApp((st) => st.toast);
  const setTasksOpen = useApp((st) => st.setTasksOpen);
  const [showSpecimen, setShowSpecimen] = useState(false);
  const submit = async (kind: string, params: Record<string, unknown>) => {
    try {
      await call("jobs.submit", { kind, params });
      setTasksOpen(true);
    } catch (e) {
      if (e instanceof CoreFailure) toast({ text: errorText(e.wire), tone: "error" });
    }
  };
  return (
    <div className={s.page} data-testid="page-tools">
      <div className={s.cards}>
        <section className={s.card}>
          <h3>{t("tools.scripts")}</h3>
          <p>{t("tools.scripts.body")}</p>
        </section>
        <section className={s.card}>
          <h3>{t("tools.specimen")}</h3>
          <p>{t("tools.specimen.body")}</p>
          <Button onPress={() => setShowSpecimen((v) => !v)} data-testid="specimen-toggle">
            {t("tools.specimen")}
          </Button>
        </section>
        {dev ? (
          <section className={s.card}>
            <h3>{t("tools.selftest")}</h3>
            <div className={s.btns}>
              <Button size="sm" onPress={() => void submit("selftest.sleep", { seconds: 5 })}>
                {t("tools.selftest.sleep", { s: 5 })}
              </Button>
              <Button size="sm" onPress={() => void submit("selftest.sleep_model", { seconds: 5 })}>
                {t("tools.selftest.sleepModel", { s: 5 })}
              </Button>
              <Button size="sm" onPress={() => void submit("selftest.sleep", { seconds: 60, children: 2 })}>
                {t("tools.selftest.tree")}
              </Button>
              <Button size="sm" variant="danger" onPress={() => void submit("selftest.fail", { reason: "demo" })}>
                {t("tools.selftest.fail")}
              </Button>
            </div>
          </section>
        ) : null}
        {dev ? <ProbePanel /> : null}
      </div>
      {showSpecimen ? <Specimen /> : null}
    </div>
  );
}
