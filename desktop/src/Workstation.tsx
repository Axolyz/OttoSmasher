import StorageSettings from "./StorageSettings";
import SpeechHits from "./SpeechHits";
import { attachNativeMedia } from "./NativeMedia";
import PhoneModelDialog from "./PhoneModelDialog";
import { useListSelection } from "./ListSelection";
import { usePlaybackTempo } from "./PlaybackTempo";
import { NativeAudio } from "./NativePlayer";
import { SampleThumbnail } from "./SampleThumbnail";
import React, { useEffect, useRef, useState } from "react";
import {
  App,
  Alert,
  Badge,
  Button,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Menu,
  Modal,
  Select,
  Space,
  Splitter,
  Table,
  Tag,
  Tooltip,
  Switch,
  Progress,
} from "antd";
import {
  AppstoreOutlined,
  VideoCameraOutlined,
  ToolOutlined,
  SettingOutlined,
  MoreOutlined,
  PlusOutlined,
  StarOutlined,
  StarFilled,
  SearchOutlined,
  MenuOutlined,
  FolderOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
} from "@ant-design/icons";
import { request, Inspector } from "./Workspace";
import { SourcesWorkspace } from "./SourcesWorkspace";
import WorkflowHub from "./WorkflowHub";
import { FeatureFilters } from "./AcousticFeatures";
import { RhythmSearch } from "./RhythmSearch";
import { useSavedState, Help } from "./Ui";
import { ask } from "./main";
import "./workstation.css";
const api = (p: string, b?: any) => request("/api/samples" + p, b);
export default function Workstation() {
  const { message, modal } = App.useApp();
  const report = (x: any) =>
    message.error(x instanceof Error ? x.message : String(x));
  const [page, setPage] = useSavedState("ui.page", "library"),
    [folder, setFolder] = useSavedState<string[]>("ui.folders", []),
    [text, setText] = useSavedState("ui.text", ""),
    [tags, setTags] = useSavedState<string[]>("ui.tags", []),
    [star, setStar] = useSavedState("ui.star", false),
    [filterMode, setFilterMode] = useSavedState("ui.filter", "browse"),
    [offset, setOffset] = useSavedState("ui.offset", 0),
    [sort, setSort] = useSavedState("ui.sort", {
      key: "created",
      order: "desc",
    });
  const [viewport, setViewport] = useState(window.innerHeight),
    [contextRow, setContextRow] = useState<any>(null);
  useEffect(() => {
    const resize = () => setViewport(window.innerHeight);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const [info, setInfo] = useState<any>({ folders: [], tags: [] }),
    [listing, setListing] = useState<any>({ results: [], total: 0 }),
    [selected, setSelected] = useState<any>(null),
    [selectedId, setSelectedId] = useSavedState("ui.selected", ""),
    [pid, setPid] = useState<string>(),
    [checked, setChecked] = useState<React.Key[]>([]),
    [epoch, setEpoch] = useState(0),
    [conditions, setConditions] = useSavedState<any[]>("ui.conditions", []),
    [busy, setBusy] = useState(false);
  const [jobs, setJobs] = useState<any[]>([]),
    [taskPanel, setTaskPanel] = useState(false),
    [settingsOpen, setSettingsOpen] = useState(false),
    [settings, setSettings] = useState<any>({}),
    [command, setCommand] = useState(false),
    [commandText, setCommandText] = useState(""),
    [sourceTarget, setSourceTarget] = useState<any>(null),
    [file, setFile] = useState(""),
    [nature, setNature] = useSavedState("ui.nature", ""),
    [views, setViews] = useState<any[]>([]),
    [rhythmResults, setRhythmResults] = useState<any>(null),
    [importOpen, setImportOpen] = useState(false),
    [importNature, setImportNature] = useState("unclassified"),
    [paths, setPaths] = useState(""),
    [bulkFlatten, setBulkFlatten] = useState(false),
    [flattenMode, setFlattenMode] = useState("vowels");
  const [playbackBpm, setPlaybackBpm] = usePlaybackTempo();
  const [activeHit, setActiveHit] = useState<any>(null);
  const rowLoop = useRef(false);
  const [rowAudioUrl, setRowAudioUrl] = useState("");
  const [rowPlaying, setRowPlaying] = useState("");
  const [rowLoading, setRowLoading] = useState("");
  const rowAudio = useRef<HTMLAudioElement>(null),
    auditionGeneration = useRef(0);
  const jobsSignature = useRef("");
  async function auditionRow(r: any, quantized = false) {
    rowLoop.current = false;
    const key = r.id + ":" + (quantized ? String(playbackBpm) : "original");
    if (rowPlaying === key && rowAudio.current && !rowAudio.current.paused) {
      rowAudio.current.pause();
      setRowPlaying("");
      return;
    }
    window.dispatchEvent(new Event("otto:pause-media"));
    const generation = ++auditionGeneration.current;
    rowAudio.current?.pause();
    setRowPlaying("");
    setRowLoading(r.id);
    try {
      let url;
      if (quantized) {
        const result = r.plan_id
          ? { selected_plan_id: r.plan_id }
          : await api("/" + r.id + "/plans", { bpm: playbackBpm });
        if (!result.selected_plan_id) throw Error("该采样没有可用的节奏方案");
        url = (
          await api("/" + r.id + "/preview", {
            plan_id: result.selected_plan_id,
            mode: "strict",
          })
        ).url;
      } else {
        url = (
          await api("/" + r.id + "/audition", {
            native: !!window.ottoDesktop?.player,
          })
        ).url;
      }
      if (generation !== auditionGeneration.current) return;
      setRowAudioUrl(url);
      setRowPlaying(key);
      if (rowAudioUrl === url) void rowAudio.current?.play().catch(report);
    } catch (e) {
      if (generation === auditionGeneration.current) report(e);
    } finally {
      if (generation === auditionGeneration.current) setRowLoading("");
    }
  }
  async function auditionHit(
    hit: any,
    quantized: boolean,
    context: boolean,
    loop = false,
  ) {
    window.dispatchEvent(new Event("otto:pause-media"));
    const generation = ++auditionGeneration.current;
    rowAudio.current?.pause();
    setRowLoading(hit.material_id);
    rowLoop.current = loop;
    try {
      const result = await api("/speech-hit", {
        hit,
        action: quantized ? "quantized" : "play",
        context,
        bpm: playbackBpm,
        native: !!window.ottoDesktop?.player,
      });
      if (generation !== auditionGeneration.current) return;
      setRowAudioUrl(result.url);
      setRowPlaying(hit.material_id + ":" + hit.id);
      if (rowAudioUrl === result.url && rowAudio.current) {
        const media = rowAudio.current,
          native = attachNativeMedia(media);
        if (loop && native) await native.playRange(0, media.duration, true);
        else {
          media.currentTime = 0;
          await media.play();
        }
      }
    } catch (e) {
      if (generation === auditionGeneration.current) report(e);
    } finally {
      if (generation === auditionGeneration.current) setRowLoading("");
    }
  }
  function locateHit(hit: any) {
    setPid(hit.plan_id);
    setActiveHit(hit);
    if (selectedId !== hit.material_id)
      void choose(hit.material_id, hit.plan_id, hit);
  }
  useEffect(() => {
    setPid(undefined);
    setRhythmResults(null);
    ++auditionGeneration.current;
    rowAudio.current?.pause();
    setRowPlaying("");
    setRowLoading("");
  }, [playbackBpm]);
  useEffect(() => {
    const pause = () => {
      ++auditionGeneration.current;
      setRowLoading("");
      rowAudio.current?.pause();
      setRowPlaying("");
    };
    window.addEventListener("otto:pause-media", pause);
    return () => window.removeEventListener("otto:pause-media", pause);
  }, []);
  const find = useRef<any>(null);
  const scope = {
    nature,
    pool: "all",
    folder_ids: folder,
    text,
    tags,
    starred: star,
  };
  const refresh = () => setEpoch((x) => x + 1);
  const run = async (fn: () => Promise<any>) => {
    try {
      return await fn();
    } catch (e) {
      report(e);
    }
  };
  const [modelIds, setModelIds] = useState<string[] | null>(null);
  const choiceSerial = useRef(0);
  const detailRequest = useRef<AbortController | null>(null);
  async function choose(id: string, plan?: string, hit?: any) {
    setActiveHit(hit || null);
    const serial = ++choiceSerial.current;
    detailRequest.current?.abort();
    const controller = new AbortController();
    detailRequest.current = controller;
    const stub = rows.find((x: any) => x.id === id);
    setSelectedId(id);
    setPid(plan);
    if (stub) setSelected({ ...stub, _loading: true, analysis_settings: {} });
    let r;
    try {
      const response = await fetch("/api/samples/" + id, {
        signal: controller.signal,
      });
      r = await response.json();
      if (!response.ok) throw Error(r.detail || "采样资料读取失败");
    } catch (e) {
      if (controller.signal.aborted) return;
      throw e;
    }
    if (serial !== choiceSerial.current) return;
    setSelected(r);
    setSelectedId(id);
    setPid(plan);
  }
  function navigate(next: string) {
    window.dispatchEvent(new Event("otto:pause-media"));
    document
      .querySelectorAll<HTMLMediaElement>("audio,video")
      .forEach((m) => m.pause());
    setPage(next);
    history.replaceState(null, "", "/helper/?view=" + next);
  }
  useEffect(() => {
    api("/info")
      .then((v) => {
        setInfo(v);
        setFolder((old) =>
          old.filter((id) => v.folders.some((f: any) => f.id === id)),
        );
        if (!v.total) {
          setSelected(null);
          setSelectedId("");
          setChecked([]);
        }
      })
      .catch(report);
    request("/api/library-tools/views").then(setViews).catch(report);
  }, [epoch]);
  useEffect(() => {
    request("/api/ui/settings")
      .then((x) => {
        setSettings(x);
        localStorage.setItem("otto.ui.settings", JSON.stringify(x));
      })
      .catch(report);
    const q = new URLSearchParams(location.search);
    if (["cut", "prepare", "sources"].includes(q.get("view") || ""))
      navigate("sources");
    else if (q.get("view") === "workflows") navigate("workflows");
    const id = q.get("material") || selectedId;
    if (id)
      choose(id).catch(() => {
        setSelected(null);
        setSelectedId("");
      });
  }, []);
  useEffect(() => {
    let previousStates: Map<string, string> | null = null;
    const load = () =>
      request("/api/helper/jobs")
        .then((rows) => {
          setJobs(rows);
          const analysisFinished =
            previousStates &&
            rows.some(
              (j: any) =>
                ["speech-prepare", "sample-prepare"].includes(j.operation) &&
                ["succeeded", "failed", "cancelled"].includes(j.status) &&
                previousStates!.has(j.id) &&
                previousStates!.get(j.id) !== j.status,
            );
          previousStates = new Map(rows.map((j: any) => [j.id, j.status]));
          if (analysisFinished)
            window.dispatchEvent(new Event("otto:speech-index-changed"));
          const sig = JSON.stringify(
            rows.map((j: any) => [
              j.id,
              j.status,
              j.result?.completed,
              j.result?.stage_revision,
            ]),
          );
          if (sig !== jobsSignature.current) {
            jobsSignature.current = sig;
            refresh();
          }
          window.dispatchEvent(
            new CustomEvent("otto:jobs-updated", { detail: rows }),
          );
        })
        .catch(() => {});
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const cleanup = window.ottoDesktop?.onNavigate?.(({ view, material }) => {
      navigate(
        ["cut", "prepare", "sources"].includes(view)
          ? "sources"
          : view === "workflows"
            ? "workflows"
            : "library",
      );
      if (material) run(() => choose(material));
    });
    return () => {
      cleanup?.();
    };
  }, []);
  useEffect(() => {
    setOffset(0);
    setChecked([]);
    setRhythmResults(null);
  }, [
    text,
    JSON.stringify(tags),
    JSON.stringify(folder),
    nature,
    star,
    filterMode,
    JSON.stringify(conditions),
  ]);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      setBusy(true);
      request("/api/ui/catalog", {
        scope,
        offset,
        limit: 100,
        sort: sort.key,
        order: sort.order,
        conditions:
          filterMode === "pitched" || filterMode === "unpitched"
            ? conditions
            : [],
      })
        .then((v) => {
          if (active) setListing(v);
        })
        .catch(report)
        .finally(() => {
          if (active) setBusy(false);
        });
    }, 180);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    text,
    JSON.stringify(tags),
    JSON.stringify(folder),
    nature,
    star,
    offset,
    epoch,
    sort,
    conditions,
    filterMode,
  ]);
  const rows =
    filterMode === "speech" && rhythmResults
      ? rhythmResults.results.map((r: any) => ({
          ...r,
          id: r.material_id,
          title: r.sample_title,
          duration: r.end - r.start,
          key: r.id || r.material_id,
        }))
      : listing.results;
  const selection = useListSelection(
    checked,
    setChecked,
    rows.map((r: any) => r.id),
    true,
  );
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (
        el.closest(
          "input,textarea,select,[contenteditable=true],.ant-select",
        ) &&
        !((e.metaKey || e.ctrlKey) && ["k", "f"].includes(e.key.toLowerCase()))
      )
        return;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommand(true);
      } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        find.current?.focus();
      } else if (
        page === "library" &&
        (e.key === "ArrowDown" || e.key === "ArrowUp") &&
        !el.closest(".ant-modal")
      ) {
        e.preventDefault();
        const i = rows.findIndex((x: any) => x.id === selectedId),
          next =
            rows[
              Math.max(
                0,
                Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)),
              )
            ];
        if (next) run(() => choose(next.id, next.plan_id));
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [rows, selectedId, page]);
  async function importSamples(list: string[]) {
    for (const path of list) {
      const r = await api("/register", {
        path,
        nature: importNature,
        folder_id: folder.length === 1 ? folder[0] : "inbox",
      });
      await choose(r.id);
    }
    refresh();
    setImportOpen(false);
  }
  async function pickSamples() {
    const files = window.ottoDesktop ? await window.ottoDesktop.pick() : [];
    if (window.ottoDesktop && !files.length) return;
    setPaths(files.join("\n"));
    setImportNature(nature || "unclassified");
    setImportOpen(true);
  }
  async function sourceFor(r: any, hit?: any) {
    setSourceTarget({
      source_id: r.source_id,
      material_id: r.id,
      hit_range: hit ? [hit.start, hit.end] : undefined,
      nonce: Date.now(),
    });
    navigate("sources");
  }
  const toggleStar = (r: any) =>
    run(async () => {
      await api("/" + r.id + "/preferences", { starred: !r.starred });
      refresh();
      if (selectedId === r.id) await choose(r.id, pid);
    });
  async function selectAllSamples() {
    const ids =
      filterMode === "speech" && rhythmResults
        ? rows.map((r: any) => r.id)
        : (
            await request("/api/ui/catalog", {
              scope,
              ids_only: true,
              conditions: ["pitched", "unpitched"].includes(filterMode)
                ? conditions
                : [],
            })
          ).ids;
    selection.select(ids);
  }
  function deleteSamples(ids: React.Key[]) {
    if (!ids.length) return;
    modal.confirm({
      title: `删除 ${ids.length} 个采样？`,
      content: "从采样库删除；保留原片和磁盘音频。",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: async () => {
        await api("/delete", { ids });
        selection.finish();
        if (ids.includes(selectedId)) {
          setSelected(null);
          setSelectedId("");
        }
        setRhythmResults(null);
        refresh();
      },
    });
  }
  function deleteFolders(ids: string[]) {
    if (!ids.length) return;
    modal.confirm({
      title: `删除 ${ids.length} 个文件夹？`,
      content: "其中的采样保留，改为未归档。",
      okText: "删除",
      okButtonProps: { danger: true },
      onOk: async () => {
        await api("/folders/delete", { ids });
        setFolder([]);
        refresh();
      },
    });
  }
  const rowMenu = (r: any) => [
    ...selection.menu(r.id),
    {
      key: "phone-model",
      label: "切换音素模型…",
      onClick: () =>
        setModelIds((checked.includes(r.id) ? checked : [r.id]).map(String)),
    },
    {
      key: "all-filtered",
      label: "全选筛选结果（所有页）",
      onClick: () => run(selectAllSamples),
    },
    {
      key: "delete",
      label: "删除",
      danger: true,
      onClick: () => deleteSamples(checked.includes(r.id) ? checked : [r.id]),
    },
    { key: "source", label: "返回原片", onClick: () => sourceFor(r) },
    {
      key: "rename",
      label: "重命名",
      onClick: () =>
        run(async () => {
          const title = await ask("采样名称", r.title);
          if (title) {
            await request("/api/helper/materials/" + r.id + "/edit", { title });
            refresh();
            if (selectedId === r.id) await choose(r.id, pid);
          }
        }),
    },
    {
      key: "export",
      label: "导出原声文件",
      onClick: () =>
        run(async () => setFile((await api("/" + r.id + "/export", {})).path)),
    },
  ];
  const columns: any[] = [
    {
      title: "采样",
      dataIndex: "title",
      key: "title",
      sorter: true,
      width: 260,
      render: (v: string, r: any) => (
        <div className="sample-row-content">
          <div className="sample-thumb-play">
            <SampleThumbnail material={r} />
            <Tooltip title="左键：原版 · 右键：默认卡拍">
              <Button
                size="small"
                type="text"
                aria-label={`试听 ${r.title}`}
                loading={rowLoading === r.id}
                icon={
                  rowPlaying.startsWith(r.id + ":") ? (
                    <PauseCircleOutlined />
                  ) : (
                    <PlayCircleOutlined />
                  )
                }
                onClick={(e) => {
                  e.stopPropagation();
                  void auditionRow(r);
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  void auditionRow(r, true);
                }}
              />
            </Tooltip>
          </div>
          <div className="sample-title">
            <span>{v}</span>
            <div className="tag-line">
              {(r.tags || [])
                .filter((t: any) => !t.tag.startsWith("cluster:"))
                .slice(0, 5)
                .map((t: any) => (
                  <Tag
                    key={t.tag}
                    title={
                      t.origin === "subtitle"
                        ? "字幕提供，未人工确认"
                        : t.origin === "flatten_target"
                          ? "拉平目标音高"
                          : t.origin
                    }
                    color={
                      t.origin === "manual" && !t.inherited
                        ? "cyan"
                        : t.tag.startsWith("pitch:")
                          ? "gold"
                          : t.tag.startsWith("character:") ||
                              t.tag.startsWith("participants:")
                            ? "purple"
                            : t.tag.startsWith("work:")
                              ? "blue"
                              : undefined
                    }
                  >
                    {t.tag.replace(
                      /^(character|work|type|pitch|participants|speaker-status):/,
                      "",
                    )}
                  </Tag>
                ))}
            </div>
            {!!r.hits?.length && (
              <SpeechHits
                hits={r.hits}
                play={auditionHit}
                locate={locateHit}
                source={(hit) => sourceFor(r, hit)}
                file={setFile}
                changed={refresh}
                onError={report}
                bpm={playbackBpm}
              />
            )}
            {r.plan_id && (
              <small>
                {r.speech_playback_speed?.toFixed(2)}× ·{" "}
                {(r.matched_anchor_indices || [])
                  .map(
                    (i: number, n: number) =>
                      `${n + 1}←${r.anchors?.[i]?.label || "?"}`,
                  )
                  .join(" · ")}
              </small>
            )}
          </div>
        </div>
      ),
    },
    {
      title: "时长",
      dataIndex: "duration",
      key: "duration",
      sorter: true,
      width: 75,
      render: (v: number) => v?.toFixed(2) + "s",
    },
    {
      title: "",
      key: "star",
      fixed: "right",
      width: 38,
      render: (_: any, r: any) => (
        <Button
          type="text"
          size="small"
          aria-label={r.starred ? "取消星标" : "加星标"}
          icon={r.starred ? <StarFilled /> : <StarOutlined />}
          onClick={(e) => {
            e.stopPropagation();
            toggleStar(r);
          }}
        />
      ),
    },
  ];
  const commands = [
    { label: "导入独立采样", run: pickSamples },
    { label: "添加 / 浏览原片", run: () => navigate("sources") },
    {
      label: "节奏检索",
      run: () => {
        navigate("library");
        setFilterMode("speech");
      },
    },
    { label: "工具与工作流", run: () => navigate("workflows") },
    { label: "全局设置", run: () => setSettingsOpen(true) },
    { label: "任务与日志", run: () => setTaskPanel(true) },
  ];
  return (
    <div
      className="studio-shell"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        if (page !== "library") return;
        e.preventDefault();
        const p = [...e.dataTransfer.files]
          .map((f) => window.ottoDesktop?.filePath(f) || "")
          .filter(Boolean);
        if (p.length) run(() => importSamples(p));
      }}
    >
      {rowAudioUrl && (
        <NativeAudio
          ref={rowAudio}
          src={rowAudioUrl}
          autoPlay
          onLoadedMetadata={() => {
            const m = rowAudio.current;
            if (m && rowLoop.current) {
              const native = attachNativeMedia(m);
              if (native) void native.playRange(0, m.duration, true);
              else m.loop = true;
            } else if (m) m.loop = false;
          }}
          onEnded={() => setRowPlaying("")}
          onError={() => {
            report(new Error("试听加载失败"));
            setRowPlaying("");
          }}
        />
      )}
      <div className="studio-header">
        <strong className="studio-brand">OttoSmasher</strong>
        <Menu
          mode="horizontal"
          selectedKeys={[page]}
          onClick={({ key }) => navigate(key)}
          items={[
            { key: "library", icon: <AppstoreOutlined />, label: "采样库" },
            { key: "sources", icon: <VideoCameraOutlined />, label: "原片" },
            { key: "workflows", icon: <ToolOutlined />, label: "工具与工作流" },
          ]}
        />
        <Space>
          <Tooltip title="留空：保持原语速的卡拍；指定 BPM：默认使用不慢于原速的最近二进制方案。">
            <InputNumber
              aria-label="全局目标 BPM"
              prefix="BPM"
              placeholder="原速"
              min={20}
              max={400}
              value={playbackBpm}
              onChange={(v) => setPlaybackBpm(v)}
              style={{ width: 115 }}
            />
          </Tooltip>
          <Tooltip title="命令菜单 ⌘K">
            <Button
              type="text"
              icon={<SearchOutlined />}
              onClick={() => setCommand(true)}
            />
          </Tooltip>
          <Badge
            count={
              jobs.filter((j) => ["running", "queued"].includes(j.status))
                .length
            }
            size="small"
          >
            <Button onClick={() => setTaskPanel(true)}>任务</Button>
          </Badge>
          <Button
            type="text"
            icon={<SettingOutlined />}
            aria-label="全局设置"
            onClick={() =>
              run(async () => {
                setSettings(await request("/api/ui/settings"));
                setSettingsOpen(true);
              })
            }
          />
          <Dropdown
            menu={{
              items: [
                {
                  key: "window",
                  label: "另开窗口",
                  onClick: () =>
                    window.ottoDesktop?.newWindow?.(page, selectedId),
                },
              ],
            }}
          >
            <Button type="text" icon={<MoreOutlined />} aria-label="窗口操作" />
          </Dropdown>
        </Space>
      </div>
      <div className="studio-body" hidden={page !== "library"}>
        <aside
          className="studio-sidebar"
          tabIndex={0}
          onKeyDown={(e) => {
            if ((e.target as HTMLElement).closest("input,textarea")) return;
            if (["Delete", "Backspace"].includes(e.key)) {
              e.preventDefault();
              deleteFolders(folder);
            }
          }}
        >
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => run(pickSamples)}
          >
            导入采样
          </Button>
          <div className="sidebar-caption">性质</div>
          <Menu
            selectedKeys={[nature]}
            items={[
              { key: "", label: "全部性质" },
              { key: "speech", label: "语音" },
              { key: "pitched", label: "调谐单音" },
              { key: "unpitched", label: "非调谐单音" },
            ]}
            onClick={({ key }) => setNature(key)}
          />
          <div className="sidebar-caption">虚拟文件夹</div>
          <Menu
            selectedKeys={folder.length ? folder : ["all"]}
            multiple
            items={[
              { key: "all", label: "全部采样", icon: <AppstoreOutlined /> },
              ...info.folders.map((f: any) => ({
                key: f.id,
                label: (
                  <Dropdown
                    trigger={["contextMenu"]}
                    menu={{
                      items: [
                        {
                          key: "delete",
                          label: "删除文件夹",
                          danger: true,
                          onClick: () =>
                            deleteFolders(
                              folder.includes(f.id) ? folder : [f.id],
                            ),
                        },
                        {
                          key: "all",
                          label: "全选文件夹",
                          onClick: () =>
                            setFolder(info.folders.map((x: any) => x.id)),
                        },
                      ],
                    }}
                  >
                    <span>{f.name}</span>
                  </Dropdown>
                ),
                icon: <FolderOutlined />,
              })),
            ]}
            onClick={({ key, domEvent }) => {
              if (key === "all") setFolder([]);
              else
                setFolder(
                  domEvent.metaKey || domEvent.ctrlKey
                    ? folder.includes(key)
                      ? folder.filter((x) => x !== key)
                      : [...folder, key]
                    : [key],
                );
            }}
          />
          <Button
            type={star ? "primary" : "text"}
            icon={<StarOutlined />}
            onClick={() => setStar(!star)}
          >
            仅星标
          </Button>
          <Dropdown
            menu={{
              items: [
                {
                  key: "add",
                  label: "新建文件夹",
                  onClick: () =>
                    run(async () => {
                      const name = await ask("文件夹名称");
                      if (name) {
                        await api("/folders", { name });
                        refresh();
                      }
                    }),
                },
                {
                  key: "rename",
                  label: "重命名当前文件夹",
                  disabled: folder.length !== 1,
                  onClick: () =>
                    run(async () => {
                      const name = await ask(
                        "文件夹名称",
                        info.folders.find((f: any) => f.id === folder[0])?.name,
                      );
                      if (name) {
                        await api("/folders", { id: folder[0], name });
                        refresh();
                      }
                    }),
                },
                {
                  key: "all-folders",
                  label: "全选文件夹",
                  onClick: () => setFolder(info.folders.map((f: any) => f.id)),
                },
                {
                  key: "delete-folders",
                  label: "删除所选文件夹",
                  danger: true,
                  disabled: !folder.length,
                  onClick: () => deleteFolders(folder),
                },
                {
                  key: "save",
                  label: "保存当前筛选",
                  onClick: () =>
                    run(async () => {
                      const name = await ask("视图名称");
                      if (name) {
                        await request("/api/library-tools/views", {
                          name,
                          scope: { ...scope, mode: filterMode, conditions },
                        });
                        refresh();
                      }
                    }),
                },
              ],
            }}
          >
            <Button type="text" icon={<MoreOutlined />}>
              目录操作
            </Button>
          </Dropdown>
          {views.length > 0 && (
            <>
              <div className="sidebar-caption">保存的筛选</div>
              <Menu
                items={views.map((v) => ({ key: v.id, label: v.name }))}
                onClick={({ key }) => {
                  const s = views.find((v) => v.id === key).scope;
                  setFolder(s.folder_ids || []);
                  setNature(s.nature || "");
                  setText(s.text || "");
                  setTags(s.tags || []);
                  setStar(!!s.starred);
                  setFilterMode(s.mode || "browse");
                  setConditions(s.conditions || []);
                }}
              />
            </>
          )}
        </aside>
        <main className="library-stage">
          <div className="studio-toolbar">
            <Input
              ref={find}
              prefix={<SearchOutlined />}
              placeholder="搜索采样、原句、备注"
              allowClear
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <Select
              mode="multiple"
              allowClear
              maxTagCount="responsive"
              placeholder="标签交集"
              value={tags}
              options={(listing.tags || info.tags).map((t: string) => ({
                value: t,
                label: t.replace(/^(work|character|type):/, ""),
              }))}
              onChange={setTags}
            />
            <Select
              value={filterMode}
              onChange={setFilterMode}
              options={[
                { value: "browse", label: "普通筛选" },
                { value: "speech", label: "语音 · 音块检索" },
                { value: "pitched", label: "单音 · 音色" },
                { value: "unpitched", label: "单音 · 瞬态" },
              ]}
            />
          </div>
          {filterMode === "speech" && (
            <RhythmSearch
              scope={scope}
              onResults={setRhythmResults}
              onMessage={report}
            />
          )}{" "}
          {["pitched", "unpitched"].includes(filterMode) && (
            <FeatureFilters
              mode={filterMode}
              conditions={conditions}
              onChange={setConditions}
              onPrepare={() => run(async () => {
                await request("/api/library-tools/features", {scope});
                message.info("声学指标任务已排队");
              })}
            />
          )}
          <div className="studio-toolbar compact">
            <span>
              {rhythmResults && filterMode === "speech"
                ? `${rows.length} 个命中采样`
                : `${listing.total} 个采样`}
            </span>
            <Button onClick={() => run(selectAllSamples)}>全选</Button>
            {checked.length > 0 && (
              <Button onClick={() => setModelIds(checked.map(String))}>
                切换音素模型
              </Button>
            )}
            {checked.length > 0 && (
              <Button danger onClick={() => deleteSamples(checked)}>
                删除
              </Button>
            )}
            {checked.length > 0 && (
              <>
                <Tag>{checked.length} 项已选</Tag>
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: "analyse",
                        label: "准备语音分析",
                        onClick: () =>
                          window.dispatchEvent(
                            new CustomEvent("otto:analysis-dialog", {
                              detail: { material_ids: checked },
                            }),
                          ),
                      },
                      {
                        key: "flatten",
                        label: "批量拉平…",
                        onClick: () => setBulkFlatten(true),
                      },
                      {
                        key: "accept",
                        label: "接收所选批次候选",
                        onClick: () =>
                          run(async () => {
                            await api("/review", {
                              ids: checked,
                              accept: true,
                            });
                            refresh();
                          }),
                      },
                      {
                        key: "discard",
                        label: "丢弃所选批次候选",
                        onClick: () =>
                          modal.confirm({
                            title: "丢弃所选批次候选？",
                            content: "仅影响待审核候选；父采样和共享音源保留。",
                            onOk: () =>
                              run(async () => {
                                await api("/review", {
                                  ids: checked,
                                  accept: false,
                                });
                                refresh();
                              }),
                          }),
                      },
                      {
                        key: "move",
                        label: "移动到文件夹",
                        children: info.folders
                          .filter((f: any) => !f.batch_id)
                          .map((f: any) => ({
                            key: f.id,
                            label: f.name,
                            onClick: () =>
                              run(async () => {
                                for (const id of checked)
                                  await api("/" + id + "/preferences", {
                                    folder_id: f.id,
                                  });
                                refresh();
                              }),
                          })),
                      },
                    ],
                  }}
                >
                  <Button>批量操作</Button>
                </Dropdown>
              </>
            )}
            {selection.enabled && (
              <Button type="text" onClick={selection.finish}>
                退出多选
              </Button>
            )}
            <span className="toolbar-spacer" />
            <Help>
              单击查看详情，右键进入多选；⌘ / Ctrl 点击切换选择，Shift 连选，Esc
              退出。按住 ⌘ / Ctrl 可选择多个文件夹。
            </Help>
          </div>
          <Splitter className="library-split">
            <Splitter.Panel defaultSize="48%" min={310}>
              <Dropdown
                menu={{ items: contextRow ? rowMenu(contextRow) : [] }}
                trigger={["contextMenu"]}
              >
                <div
                  className="catalog-pane"
                  onKeyDown={(e) => {
                    if (
                      (e.target as HTMLElement).closest(
                        "input,textarea,[contenteditable=true]",
                      )
                    )
                      return;
                    if (e.key === "Escape") selection.finish();
                    if (
                      (e.metaKey || e.ctrlKey) &&
                      e.key.toLowerCase() === "a"
                    ) {
                      e.preventDefault();
                      run(selectAllSamples);
                    }
                    if (["Delete", "Backspace"].includes(e.key)) {
                      e.preventDefault();
                      deleteSamples(
                        checked.length
                          ? checked
                          : selectedId
                            ? [selectedId]
                            : [],
                      );
                    }
                  }}
                  tabIndex={-1}
                >
                  <Table
                    size="small"
                    virtual
                    scroll={{
                      x: 455,
                      y: Math.max(
                        240,
                        viewport - (filterMode === "speech" ? 420 : 240),
                      ),
                    }}
                    rowKey={(r) => r.key || r.id}
                    columns={
                      rhythmResults && filterMode === "speech"
                        ? columns.map((c) => ({ ...c, sorter: false }))
                        : columns
                    }
                    dataSource={rows}
                    loading={busy}
                    pagination={
                      rhythmResults && filterMode === "speech"
                        ? false
                        : {
                            current: offset / 100 + 1,
                            pageSize: 100,
                            total: listing.total,
                            showSizeChanger: false,
                            onChange: (p) => setOffset((p - 1) * 100),
                          }
                    }
                    rowClassName={(r) =>
                      selection.enabled
                        ? checked.includes(r.id)
                          ? "multi-selected-row"
                          : ""
                        : r.id === selectedId &&
                            (!r.plan_id || r.plan_id === pid)
                          ? "selected-row"
                          : ""
                    }
                    onRow={(r) => ({
                      onClick: (e) => {
                        if (!selection.click(r.id, e))
                          run(() => choose(r.id, r.plan_id));
                      },
                      onContextMenu: () => setContextRow(r),
                    })}
                    onChange={(_, __, s: any) => {
                      if (s.field)
                        setSort({
                          key: s.field,
                          order: s.order === "ascend" ? "asc" : "desc",
                        });
                    }}
                  />
                </div>
              </Dropdown>
            </Splitter.Panel>
            <Splitter.Panel min={390}>
              <div className="inspector-scroll">
                {selected ? (
                  <Inspector
                    key={selected.id}
                    material={selected}
                    hitPlan={pid}
                    hit={activeHit}
                    hits={
                      rows.find((x: any) => x.id === selected.id)?.hits || []
                    }
                    onHit={locateHit}
                    folders={info.folders.filter((f: any) => !f.batch_id)}
                    onSource={() => sourceFor(selected, activeHit)}
                    onAudition={(quantized) => auditionRow(selected, quantized)}
                    onSelect={(id, p) => run(() => choose(id, p))}
                    onRefresh={async () => {
                      refresh();
                      await choose(selectedId, pid);
                    }}
                    onMessage={(x) =>
                      x instanceof Error ? report(x) : message.info(String(x))
                    }
                    onFile={setFile}
                            />
                ) : (
                  <Empty description="选择采样，查看波形和制作选区" />
                )}
              </div>
            </Splitter.Panel>
          </Splitter>
        </main>
      </div>
      <div className="page-frame" hidden={page !== "sources"}>
        <SourcesWorkspace
          active={page === "sources"}
          target={sourceTarget}
          materialIds={checked.map(String)}
          onMessage={(x) =>
            x instanceof Error ? report(x) : message.info(String(x))
          }
          onRefresh={refresh}
          onSample={(id) => {
            refresh();
            run(() => choose(id));
            navigate("library");
          }}
          onFile={setFile}
        />
      </div>
      <div className="page-frame workflow-page" hidden={page !== "workflows"}>
        <WorkflowHub />
      </div>
      {file && (
        <div className="file-handoff">
          <span
            draggable
            onDragStart={(e) => {
              e.preventDefault();
              window.ottoDesktop?.drag(file);
            }}
            title={file}
          >
            已导出 · {file.split("/").pop()}　↗ 拖到 DAW
          </span>
          <Button
            type="text"
            size="small"
            onClick={() => window.ottoDesktop?.reveal(file)}
          >
            在访达显示
          </Button>
          <Button type="text" size="small" onClick={() => setFile("")}>
            关闭
          </Button>
        </div>
      )}
      {modelIds && (
        <PhoneModelDialog
          ids={modelIds}
          close={() => setModelIds(null)}
          changed={() => {
            refresh();
            if (selectedId) void choose(selectedId);
          }}
          onError={report}
        />
      )}
      <Modal
        title="批量拉平"
        open={bulkFlatten}
        onCancel={() => setBulkFlatten(false)}
        okText="创建拉平任务"
        onOk={() =>
          run(async () => {
            await api("/batch-flatten", {
              ids: checked,
              mode: flattenMode,
              target_folder: "pitched",
            });
            setBulkFlatten(false);
            setTaskPanel(true);
            refresh();
          })
        }
      >
        <p>
          处理所选 {checked.length}{" "}
          个采样；结果进入待审核批次，接收后归入调谐单音。
        </p>
        <Select
          value={flattenMode}
          onChange={setFlattenMode}
          style={{ width: "100%" }}
          options={[
            { value: "vowels", label: "仅处理已分析的元音" },
            { value: "all", label: "处理整个选段（不需要字幕）" },
          ]}
        />
      </Modal>
      <Drawer
        title="任务与日志"
        open={taskPanel}
        onClose={() => setTaskPanel(false)}
        size={640}
      >
        <Table
          rowKey="id"
          dataSource={jobs}
          pagination={{ pageSize: 15 }}
          columns={[
            { title: "任务", dataIndex: "operation" },
            {
              title: "状态",
              dataIndex: "status",
              render: (v, j: any) => (
                <div>
                  <Tag
                    color={
                      v === "failed"
                        ? "red"
                        : v === "succeeded"
                          ? "green"
                          : "blue"
                    }
                  >
                    {v}
                  </Tag>
                  {settings.separation_progress !== false &&
                    j.status === "running" &&
                    j.progress?.stage === "separation" && (
                      <div style={{ minWidth: 150 }}>
                        <Progress percent={j.progress.percent} size="small" />
                        <small>
                          人声分离 · {j.progress.window}/{j.progress.windows} 段
                          · 段内 {j.progress.window_percent}% · 已用{" "}
                          {Math.round(
                            j.progress.elapsed +
                              Math.max(
                                0,
                                Date.now() / 1000 - j.progress.updated,
                              ),
                          )}
                          s
                        </small>
                      </div>
                    )}
                  {j.status === "running" &&
                    j.progress?.message &&
                    j.progress.stage !== "separation" && (
                      <div>
                        <small>{j.progress.message}</small>
                      </div>
                    )}
                  {j.status === "running" &&
                    j.result?.type === "preparation" && (
                      <small>
                        台词 {j.result.completed}/{j.result.total}
                      </small>
                    )}
                </div>
              ),
            },
            {
              title: "操作",
              render: (_: any, j: any) => (
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: "log",
                        label: "查看日志",
                        onClick: () =>
                          run(async () => {
                            const x = await request(
                              "/api/helper/jobs/" + j.id + "/log",
                            );
                            modal.info({
                              title: "任务日志",
                              width: 850,
                              content: (
                                <pre className="log-view">
                                  {typeof x === "string"
                                    ? x
                                    : x.text || JSON.stringify(x, null, 2)}
                                </pre>
                              ),
                            });
                          }),
                      },
                      {
                        key: "cancel",
                        label: "取消",
                        disabled: !["running", "queued"].includes(j.status),
                        onClick: () =>
                          run(() =>
                            request("/api/helper/jobs/" + j.id + "/cancel", {}),
                          ),
                      },
                      {
                        key: "retry",
                        label: "重试",
                        disabled: !["failed", "cancelled"].includes(j.status),
                        onClick: () =>
                          run(() =>
                            request("/api/helper/jobs/" + j.id + "/retry", {}),
                          ),
                      },
                      {
                        key: "open",
                        label: "打开结果",
                        disabled: !j.result,
                        onClick: () => {
                          if (j.operation === "speech-prepare") {
                            modal.info({
                              title: "语音分析结果",
                              width: 800,
                              content: (
                                <Table
                                  rowKey="material_id"
                                  dataSource={j.result.rows || []}
                                  pagination={{ pageSize: 12 }}
                                  columns={[
                                    {
                                      title: "台词",
                                      render: (_: any, row: any) => (
                                        <Button
                                          type="link"
                                          onClick={() =>
                                            run(async () => {
                                              await choose(row.material_id);
                                              navigate("library");
                                              Modal.destroyAll();
                                            })
                                          }
                                        >
                                          {row.title || "查看台词"}
                                        </Button>
                                      ),
                                    },
                                    { title: "状态", dataIndex: "status" },
                                    {
                                      title: "说明",
                                      render: (_: any, row: any) =>
                                        row.error ||
                                        Object.entries(row.stages || {})
                                          .map(
                                            ([k, v]: any) =>
                                              `${k}: ${v.status}`,
                                          )
                                          .join(" · "),
                                    },
                                  ]}
                                />
                              ),
                            });
                          } else if (
                            [
                              "sample-phones",
                              "native-alignment",
                              "sample-features",
                              "flatten",
                              "separate",
                            ].includes(j.operation) &&
                            j.payload?.material_id
                          ) {
                            run(async () => {
                              const mid =
                                j.result?.sample?.id ||
                                j.result?.material_id ||
                                j.payload.material_id;
                              if (j.operation === "separate")
                                sourceFor(await api("/" + mid));
                              else {
                                await choose(mid);
                                navigate("library");
                              }
                            });
                          } else if (["opening-scan", "source-separation"].includes(j.operation)) {
                            navigate("sources");
                          } else
                            modal.info({
                              title: "任务结果",
                              width: 800,
                              content: (
                                <pre className="log-view">
                                  {JSON.stringify(j.result, null, 2)}
                                </pre>
                              ),
                            });
                          setTaskPanel(false);
                        },
                      },
                    ],
                  }}
                >
                  <Button icon={<MoreOutlined />} />
                </Dropdown>
              ),
            },
          ]}
          expandable={{
            expandedRowRender: (j) => (
              <pre className="log-view">
                {j.error || JSON.stringify(j.result || j.payload, null, 2)}
              </pre>
            ),
          }}
        />
      </Drawer>
      <Modal
        title="全局默认设置"
        open={settingsOpen}
        onCancel={() => setSettingsOpen(false)}
        onOk={() =>
          run(async () => {
            await request("/api/ui/settings", settings);
            localStorage.setItem("otto.ui.settings", JSON.stringify(settings));
            window.dispatchEvent(new Event("otto:settings"));
            setSettingsOpen(false);
            message.success("默认设置已保存；已有采样的分析选择保持不变");
          })
        }
      >
        <Form layout="vertical">
          <StorageSettings />
          <Form.Item label="空闲时整理可重建缓存" tooltip="无客户端访问 5 分钟且没有任务时，清理超过 7 天或超出 2 GiB 的临时缓存；不自动删除模型处理结果。">
            <Switch checked={settings.cache_auto_trim !== false} onChange={v => setSettings({...settings, cache_auto_trim:v})} />
          </Form.Item>
          <Form.Item label="新语音默认模型">
            <Select
              value={settings.phone_backend}
              onChange={(v) => setSettings({ ...settings, phone_backend: v })}
              options={["narabas", "phonetic", "pydomino"].map((v) => ({
                value: v,
                label:
                  {

                    phonetic: "HubertFA",
                    pydomino: "pydomino（末位备选）",
                  }[v] || v,
              }))}
            />
          </Form.Item>
          <Form.Item label="新采样量化路线">
            <Select
              value={settings.quantization}
              onChange={(v) => setSettings({ ...settings, quantization: v })}
              options={[
                { value: "acoustic", label: "原节奏 · 无 mora" },
                { value: "mora_guided", label: "mora 参考校准" },
                { value: "mora", label: "纯 mora" },
              ]}
            />
          </Form.Item>
          <Form.Item label="大数字惩罚度" tooltip="1× 为原权重 0.045。只重建无 mora 的节奏与索引，不重新推理。">
            <InputNumber min={0} max={3} step={0.1} value={settings.large_number_penalty ?? 1}
              onChange={(v) => setSettings({...settings, large_number_penalty: v ?? 1})} suffix="×" />
          </Form.Item>
          <Form.Item label="后续任务推理设备">
            <Select value={settings.inference_device || "auto"}
              onChange={(v) => setSettings({...settings,inference_device:v})}
              options={[{value:"auto",label:"自动"},{value:"cpu",label:"CPU"},{value:"cuda",label:"CUDA"},{value:"mps",label:"MPS（PyTorch）"}]} />
          </Form.Item>
          {settings.inference_device === "cuda" && <Form.Item label="CUDA 设备编号">
            <InputNumber min={0} precision={0} value={settings.cuda_device ?? 0}
              onChange={(v)=>setSettings({...settings,cuda_device:v ?? 0})} />
          </Form.Item>}
          <Button onClick={()=>run(async()=> {
            const result = await request("/api/library-tools/runtime");
            modal.info({title: result.ready ? "统一推理环境" : "环境检查失败",width:700,
              content:<pre className="log-view">{JSON.stringify(result,null,2)}</pre>});
          })}>检查已保存的环境与实际设备</Button>
          <Form.Item label="默认人声模型">
            <Select
              value={settings.vocal_model}
              onChange={(v) => setSettings({ ...settings, vocal_model: v })}
              options={[
                { value: "becruily_deux", label: "becruily Deux" },
                { value: "bs_roformer_voc_hyperacev2", label: "HyperACE" },
              ]}
            />
          </Form.Item>
          <Form.Item label="显示人声分离内部进度">
            <Switch
              checked={settings.separation_progress !== false}
              onChange={(v) =>
                setSettings({ ...settings, separation_progress: v })
              }
            />
          </Form.Item>
          <Form.Item
            label="模型任务并发数"
            tooltip="默认为 1；增加可并行运行模型，但多份模型会叠加内存占用。"
          >
            <InputNumber
              min={1}
              max={4}
              value={settings.model_concurrency || 1}
              onChange={(v) =>
                setSettings({ ...settings, model_concurrency: v })
              }
            />
          </Form.Item>
          <Form.Item label="轻量任务并发数">
            <InputNumber
              min={1}
              max={4}
              value={settings.utility_concurrency || 2}
              onChange={(v) =>
                setSettings({ ...settings, utility_concurrency: v })
              }
            />
          </Form.Item>
          <Form.Item label="波形缩放曲线">
            <Select
              value={settings.zoom_curve}
              onChange={(v) => setSettings({ ...settings, zoom_curve: v })}
              options={[
                { value: "exponential", label: "指数" },
                { value: "linear", label: "线性" },
              ]}
            />
          </Form.Item>
          <Form.Item label="滚轮缩放累计阈值">
            <InputNumber
              min={1}
              max={100}
              value={settings.zoom_threshold}
              onChange={(v) => setSettings({ ...settings, zoom_threshold: v })}
            />
          </Form.Item>
          <Form.Item label="默认导出目录">
            <Input
              value={settings.export_directory}
              placeholder="留空使用工作区持久输出目录"
              onChange={(e) =>
                setSettings({ ...settings, export_directory: e.target.value })
              }
            />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="命令"
        open={command}
        onCancel={() => setCommand(false)}
        footer={null}
      >
        <Input
          autoFocus
          placeholder="搜索操作…"
          value={commandText}
          onChange={(e) => setCommandText(e.target.value)}
        />
        <Menu
          items={commands
            .filter((c) => c.label.includes(commandText))
            .map((c) => ({
              key: c.label,
              label: c.label,
              onClick: () => {
                setCommand(false);
                run(async () => c.run());
              },
            }))}
        />
      </Modal>
      <Modal
        title="导入独立采样"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        onOk={() =>
          run(() =>
            importSamples(
              paths
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean),
            ),
          )
        }
      >
        <Form layout="vertical">
          <Form.Item label="性质">
            <Select
              value={importNature}
              onChange={setImportNature}
              options={[
                { value: "unclassified", label: "未分类" },
                { value: "speech", label: "语音" },
                { value: "pitched", label: "调谐单音" },
                { value: "unpitched", label: "非调谐单音" },
              ]}
            />
          </Form.Item>
        </Form>
        <Input.TextArea
          rows={5}
          placeholder="每行一个本机文件绝对路径"
          value={paths}
          onChange={(e) => setPaths(e.target.value)}
        />
      </Modal>
    </div>
  );
}
