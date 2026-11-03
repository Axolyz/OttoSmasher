// 人声／音效与默认轨（规格 05 §5.4、04 §4.2.3；UI_PLAN §5 确认框；原型 tracksModal）：
// 只列容器音频流 + 完整覆盖原片且未变速的资产（同内容只显示一行）；角色可多选；每个角色一个默认轨；改动立即保存、可撤销。
// 与原型的差异：原型把默认轨画成表里的两列单选；这里是表上方两个下拉（跨表格行的单选列做不成一个无障碍的单选组），功能相同。
import { useCallback, useEffect, useState } from "react";
import { CoreFailure, call, useCoreEvent } from "../api/core";
import type { AssetDeletePreview, SourceDetail, SourceRow, TrackRow, Tracks } from "../api/types";
import { Button } from "../components/Button";
import { Callout, Checkbox } from "../components/Controls";
import { Select } from "../components/Fields";
import { DialogBox } from "../components/Overlay";
import { fileSize } from "../format";
import { errorText, t } from "../i18n";
import { useUndo } from "../shell/useUndo";
import { useApp } from "../state/store";
import { displayTitle } from "./SourceList";
import s from "./Sources.module.css";

type Role = "vocal" | "sfx";
const ROLES: Role[] = ["vocal", "sfx"];

export type { TrackRow, Tracks };

/** 音轨的显示名：容器音频流“原混音 · 第 n 条音轨 · 语言”；分离声部“模型 · 声部名” */
export function trackName(tr: TrackRow, detail?: SourceDetail | null): string {
  if (tr.origin === "stream") {
    const st = detail?.streams.find((x) => x.kind === "audio" && x.ordinal === tr.streamOrdinal);
    return [t("track.mix"), t("sources.trackN", { n: (tr.streamOrdinal ?? 0) + 1 }), st?.language ?? tr.language ?? ""].filter(Boolean).join(" · ");
  }
  // 同一个模型可以分离好几次（不做自动复用），带上时间才分得清
  return [tr.production?.model ?? t(`track.origin.${tr.origin}`), tr.stemName ?? "", shortTime(tr.createdAt)].filter(Boolean).join(" · ");
}

/** 11-03 14:20（本地时间） */
export function shortTime(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return Number.isNaN(d.getTime()) ? "" : `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function TracksDialog(props: { source: SourceRow | null; onClose: () => void }) {
  const toast = useApp((st) => st.toast);
  const undo = useUndo();
  const src = props.source;
  const [data, setData] = useState<Tracks | null>(null);
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [del, setDel] = useState<{ tr: TrackRow; pv: AssetDeletePreview } | null>(null);
  const setPage = useApp((st) => st.setPage);
  const setLibraryScope = useApp((st) => st.setLibraryScope);

  const reload = useCallback(async () => {
    if (!src) return;
    const [d, tr] = await Promise.all([call("sources.get", { id: src.id }), call("assets.tracks", { sourceId: src.id })]);
    setDetail(d);
    setData(tr);
  }, [src]);
  useEffect(() => {
    setDel(null);
    if (src) void reload();
    else setData(null);
  }, [src?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useCoreEvent("data.changed", (d) => {
    const c = d as Record<string, string[]>;
    if (c.asset || c.source) void reload();
  });

  // 角色与默认轨的规则在 Core（tracks.setRole / tracks.setDefault，命令行也用同一组）
  const apply = async (run: () => Promise<unknown>, text: string) => {
    try {
      await run();
      toast({ text, action: { label: t("common.undo"), run: () => void undo() } });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
    await reload();
  };

  const toggleRole = (tr: TrackRow, role: Role, on: boolean) => {
    if (!src || !data) return;
    const wasDefault = !on && data.defaults[role] === tr.id;
    // 去掉默认轨的角色 = 同时取消这个默认轨（明确写在提示里，不静默）
    void apply(
      () => call("tracks.setRole", { assetId: tr.id, role, on }),
      t(wasDefault ? "tracks.roleOffAndDefault" : on ? "tracks.roleOn" : "tracks.roleOff", { role: t(`role.${role}`), track: trackName(tr, detail) }),
    );
  };

  const setDefault = (role: Role, id: string) => {
    if (!src || !data) return;
    const v = id || null;
    const tr = data.tracks.find((x) => x.id === v);
    void apply(
      () => call("tracks.setDefault", { sourceId: src.id, role, assetId: v }),
      v ? t("tracks.defaultSet", { role: t(`role.${role}`), track: tr ? trackName(tr, detail) : "" }) : t("tracks.defaultCleared", { role: t(`role.${role}`) }),
    );
  };

  const askDelete = async (tr: TrackRow) => {
    try {
      setDel({ tr, pv: await call("assets.deletePreview", { id: tr.id }) });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
  };
  const confirmDelete = async () => {
    if (!del) return;
    try {
      const r = await call("assets.delete", { ids: [del.tr.id] });
      toast({ text: t("tracks.deleted", { size: fileSize(r.bytes) }) });
    } catch (e) {
      toast({ text: e instanceof CoreFailure ? errorText(e.wire) : String(e), tone: "error" });
    }
    setDel(null);
    await reload();
  };

  return (
    <DialogBox isOpen={src != null} onClose={props.onClose} title={t("tracks.title")} sub={src ? displayTitle(src) : undefined} width={640} testId="tracks-dialog">
      <Callout>{t("tracks.note")}</Callout>
      {data ? (
        <>
          <div className={s.tracksDefaults}>
            {ROLES.map((role) => (
              <div key={role} className={s.tracksDefault} data-testid={`default-${role}`}>
                <span className={s.groupLabel}>{t(`tracks.default.${role}`)}</span>
                <Select
                  value={data.defaults[role] ?? ""}
                  onChange={(v) => setDefault(role, v)}
                  label={t(`tracks.default.${role}`)}
                  options={[
                    { id: "", label: t("tracks.none") },
                    ...data.tracks.filter((tr) => tr.roles.includes(role)).map((tr) => ({ id: tr.id, label: trackName(tr, detail) })),
                  ]}
                />
              </div>
            ))}
          </div>
          <div className={s.opedList} data-testid="tracks-list">
            {data.tracks.map((tr) => (
              <div key={tr.id} className={s.opedRow} data-testid="track-row">
                <span className={s.trackName} data-user-data="">
                  {trackName(tr, detail)}
                </span>
                {tr.duplicates ? <span className={s.muted}>{t("tracks.duplicates", { n: tr.duplicates })}</span> : null}
                <span className={s.grow} />
                {ROLES.map((role) => (
                  <Checkbox key={role} isSelected={tr.roles.includes(role)} onChange={(on) => toggleRole(tr, role, on)} label={t(`role.${role}`)}>
                    {t(`role.${role}`)}
                    {data.defaults[role] === tr.id ? <span className={s.defaultBadge}>{t("tracks.isDefault")}</span> : null}
                  </Checkbox>
                ))}
                {tr.origin === "stream" ? null : (
                  <Button size="sm" variant="flat" onPress={() => void askDelete(tr)} data-testid="track-delete">
                    {t("tracks.delete")}
                  </Button>
                )}
              </div>
            ))}
          </div>
          {del ? (
            <Callout tone={del.pv.deletable ? "warn" : "bad"} testId="track-delete-confirm">
              {del.pv.deletable ? (
                <>
                  <div>{t("tracks.deleteConfirm", { name: trackName(del.tr, detail), size: fileSize(del.pv.bytes) })}</div>
                  {del.pv.defaults.length ? <div>{t("tracks.deleteDefault", { roles: del.pv.defaults.map((x) => t(`role.${x}`)).join(t("settings.subtitle.speakerSep")) })}</div> : null}
                  {del.pv.analyses ? <div>{t("tracks.deleteAnalyses", { n: del.pv.analyses })}</div> : null}
                </>
              ) : (
                <div>{t(`tracks.deleteBlocked.${del.pv.reason}`, { n: del.pv.samples })}</div>
              )}
              <div className={s.sheetBar}>
                <span className={s.grow} />
                <Button size="sm" variant="flat" onPress={() => setDel(null)}>
                  {t("common.cancel")}
                </Button>
                {del.pv.reason === "asset-samples" && src ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onPress={() => {
                      setLibraryScope({ sourceId: src.id, name: displayTitle(src) });
                      setPage("library");
                      props.onClose();
                    }}
                    data-testid="track-delete-view"
                  >
                    {t("tracks.deleteViewSamples")}
                  </Button>
                ) : null}
                {del.pv.deletable ? (
                  <Button size="sm" variant="danger" onPress={() => void confirmDelete()} data-testid="track-delete-run">
                    {t("tracks.deleteRun")}
                  </Button>
                ) : null}
              </div>
            </Callout>
          ) : null}
        </>
      ) : null}
    </DialogBox>
  );
}
