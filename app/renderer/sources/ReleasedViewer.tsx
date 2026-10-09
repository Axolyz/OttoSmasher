// 媒体已释放的原片（规格 04 §4.8；ARCHITECTURE §4.9；UI_PLAN §4）：原片文件不再引用，查看器不能播放；
// 写明保留了什么，列出留下的（独立化的）采样，单击在采样库打开。台本照常可看（文本层的段还在）。
import { Unplug } from "lucide-react";
import { useEffect, useState } from "react";
import { call } from "../api/core";
import type { SourceRow, TextLayerList } from "../api/types";
import { Button } from "../components/Button";
import { EmptyState } from "../components/Controls";
import { clock } from "../format";
import { t } from "../i18n";
import { useApp } from "../state/store";
import s from "./Sources.module.css";

export function ReleasedViewer(props: { row: SourceRow }) {
  const [tl, setTl] = useState<TextLayerList | null>(null);
  const setOpenSample = useApp((st) => st.setOpenSample);
  const setPage = useApp((st) => st.setPage);
  useEffect(() => {
    void call("textLayer.list", { sourceId: props.row.id, assetId: null }).then(setTl, () => setTl(null));
  }, [props.row.id]);
  return (
    <section className={s.viewer} data-testid="released-viewer">
      <EmptyState icon={<Unplug />} title={t("indep.viewerTitle")} body={t("indep.viewerSay", { n: props.row.independent_samples })} />
      <div className={s.releasedList}>
        {(tl?.derived ?? []).map((d) => (
          <Button
            key={d.id}
            size="sm"
            variant="flat"
            onPress={() => {
              setOpenSample(d.id);
              setPage("library");
            }}
          >
            <span lang="ja" data-user-data="">
              {d.name}
            </span>
            <span className="num"> · {clock(d.start)}</span>
          </Button>
        ))}
      </div>
      {tl?.segments.length ? (
        <div className={s.releasedLines}>
          {tl.segments.slice(0, 200).map((g) => (
            <div key={g.id} className={s.releasedLine}>
              <span className="num">{clock(g.start)}</span>
              <span lang="ja" data-user-data="">
                {g.speakers.length ? `${g.speakers.join(t("settings.subtitle.speakerSep"))} ` : ""}
                {g.text}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
