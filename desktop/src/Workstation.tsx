import {RuntimeSettings} from "./RuntimeSettings";
import {DraftNumber as InputNumber} from "./DraftNumber";
import {LibraryFilters,TagEdit} from "./LibraryFilters";
import ViewBoundary from "./ViewBoundary";
import {useSearchResults, ResultStatus} from "./SearchResults";
import AssetResult from "./AssetResult";
import TagExpressionInput from "./TagExpressionInput";
import StudioModelSelect from "./StudioModelSelect";
import BusinessTextEditor from "./BusinessTextEditor";
import FrontendDialog from "./FrontendDialog";
import PhoneTimingEditor from "./PhoneTimingEditor";
import PitchSearch from "./PitchSearch";
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
  const [edition, setEdition] = useState("standard");
  useEffect(() => { request("/api/helper/capabilities").then(c => {
    setEdition(c.edition); document.title = `OttoSmasher · ${c.edition}`;
  }).catch(report); }, []);
  const report = (x: any) =>
    message.error(x instanceof Error ? x.message : String(x));
  const [pageSizeMode,setPageSizeMode]=useSavedState<number>("ui.page-size",0);
  const [panelHeight,setPanelHeight]=useState(Math.max(300,window.innerHeight-280));
  const catalogPanel=useRef<HTMLDivElement>(null);
  const [sidebarCollapsed,setSidebarCollapsed]=useSavedState('ui.sidebar-collapsed',false);
  useEffect(()=>{const element=catalogPanel.current;if(!element)return;const observer=new ResizeObserver(entries=>{const height=entries[0].contentRect.height;if(height>0)setPanelHeight(height)});observer.observe(element);return()=>observer.disconnect()},[]);
  const pageSize=pageSizeMode || Math.max(1,Math.min(100,Math.floor((panelHeight-95)/62)));
  const results = useSearchResults(report,pageSize);
  const [singleTag,setSingleTag]=useSavedState<string|undefined>('ui.single-tag',undefined);
  const [activeFilter,setActiveFilter]=useState<any>(null),[tagEdit,setTagEdit]=useState<any>(null);
  const resultTable = useRef<any>(null);
  const [page, setPage] = useSavedState("ui.page", "library"),
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
  const [tagExpression, setTagExpression] = useSavedState("ui.tag-expression", tags.map(t => JSON.stringify(t)).join(" AND "));
  const [tagError, setTagError] = useState("");
  useEffect(() => {
    let cancelled = false;
    const timer = setTimeout(() => {
      api("/tags/validate", {expression: tagExpression}).then(result => {
        if (!cancelled) setTagError(result.valid ? "" : result.error);
      }).catch(e => { if (!cancelled) setTagError(String(e)); });
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [tagExpression]);
  useEffect(() => {
    const resize = () => setViewport(window.innerHeight);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const [info, setInfo] = useState<any>({ tags: [] }),
    [listing, setListing] = useState<any>({ results: [], total: 0 }),
    [selected, setSelected] = useState<any>(null),
    [selectedId, setSelectedId] = useSavedState("ui.selected", ""),
    [pid, setPid] = useState<string>(),
    [checked, setChecked] = useState<React.Key[]>([]),
    [epoch, setEpoch] = useState(0),
    [conditions, setConditions] = useSavedState<any[]>("ui.conditions", []),
    [busy, setBusy] = useState(false);
  const [newSamples, setNewSamples] = useState(false);
  const [jobs, setJobs] = useState<any[]>([]),
    [taskPanel, setTaskPanel] = useState(false),
    [settingsOpen, setSettingsOpen] = useState(false),
    [settings, setSettings] = useState<any>({}),
    [command, setCommand] = useState(false),
    [commandText, setCommandText] = useState(""),
    [sourceTarget, setSourceTarget] = useState<any>(null),
    [file, setFile] = useState(""),
    [nature, setNature] = useSavedState("ui.nature", ""),
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
  useEffect(()=>{
    const play=(event:Event)=>{window.dispatchEvent(new Event("otto:pause-media"));rowLoop.current=false;setRowAudioUrl((event as CustomEvent).detail);setRowPlaying("pitch-hit");const player=rowAudio.current;if(player&&player.getAttribute("src")===(event as CustomEvent).detail){player.currentTime=0;void player.play().catch(report);}};
    window.addEventListener("otto:pitch-audition",play);return()=>window.removeEventListener("otto:pitch-audition",play);
  },[]);
  const jobsSignature = useRef("");
  async function auditionRow(r: any, quantized = false) {
    rowLoop.current = false;
    const key = r.id + ":" + (quantized ? String(playbackBpm) : "original");
    if (rowPlaying === key && rowAudio.current && !rowAudio.current.paused) {
      rowAudio.current.pause();
      setRowPlaying("");
      return;
    }
    if(r.result_status)return;
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
    if(hit.disabled)return;
    window.dispatchEvent(new Event("otto:pause-media"));
    const generation = ++auditionGeneration.current;
    rowAudio.current?.pause();
    setRowLoading(hit.material_id);
    rowLoop.current = loop;
    try {
      const result = hit.kind === "pitch" ? await api("/pitch-hit", {asset_id:hit.asset_id,start:hit.file_start,end:hit.file_end}) : await api("/speech-hit", {
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
    if(hit.disabled)return;
    if(!hit.material_id){void sourceFor({source_id:hit.source_id,source_result:true},hit);return;}
    setPid(hit.plan_id);
    setActiveHit(hit);
    if (selectedId !== hit.material_id)
      void choose(hit.material_id, hit.plan_id, hit);
  }
  useEffect(() => {
    setPid(undefined);
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
    single_tag: singleTag,
    intersections: activeFilter ? [activeFilter.scope] : [],
    text,
    tag_expression: tagExpression,
    starred: star,
  };
  const browseScopeKey=JSON.stringify(scope);
  const previousBrowseScope=useRef(browseScopeKey);
  useEffect(()=>{if(previousBrowseScope.current!==browseScopeKey){previousBrowseScope.current=browseScopeKey;results.browse();}},[browseScopeKey]);
  const refresh = () => setEpoch((x) => x + 1);
  const run = async (fn: () => Promise<any>) => {
    try {
      return await fn();
    } catch (e) {
      report(e);
    }
  };
  const [modelIds, setModelIds] = useState<string[] | null>(null);
  const [editObjects, setEditObjects] = useState<{type: string; id: string}[] | null>(null);
  const [frontendTarget, setFrontendTarget] = useState<{cueId?: string} | null>(null);
  const [timingTarget, setTimingTarget] = useState<{id:string;backend:string}|null>(null);
  const reanalyse = (ids: React.Key[]) => run(async () => {
    ids=ids.filter(id=>!rows.find((r:any)=>r.id===id)?.source_result);if(!ids.length)return;
    const result = await api("/reanalyse", {ids:ids.map(String),backend:settings.phone_model_order?.[0] || settings.phone_backend});
    if(result.job) message.success(`重新 FA 已排队：${result.job.id}`);
    if(result.missing.length) modal.info({title:"部分采样需要补充输入",content:result.missing.map((x:any)=><p key={x.material_id}>{x.material_id}: {x.reason}</p>)});
    refresh();
  });
  const editSamples = (ids: React.Key[]) => {const targets=ids.filter(id=>!rows.find((r:any)=>r.id===id)?.source_result);if(targets.length)setEditObjects(targets.map(id => ({type: "sample", id: String(id)})));};
  const choiceSerial = useRef(0);
  const detailRequest = useRef<AbortController | null>(null);
  async function choose(id: string, plan?: string, hit?: any) {
    results.remember({selected_id:id});
    setActiveHit(hit || null);
    const serial = ++choiceSerial.current;
    detailRequest.current?.abort();
    const controller = new AbortController();
    detailRequest.current = controller;
    const stub = rows.find((x: any) => x.id === id);
    setSelectedId(id);
    setPid(plan);
    if(stub?.source_result){setSelected(null);return;}
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
        if (!v.total) {
          setSelected(null);
          setSelectedId("");
          setChecked([]);
        }
      })
      .catch(report);
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
    let previousSignatures = new Map<string, string>();
    const load = () =>
      request("/api/helper/jobs?summary=true")
        .then((rows) => {
          const changed = rows.filter((j: any) => previousSignatures.get(j.id) !== JSON.stringify([j.status,j.result]));
          const initialized = previousSignatures.size > 0;
          previousSignatures = new Map(rows.map((j: any) => [j.id, JSON.stringify([j.status,j.result])]));
          if (changed.length) setJobs(rows);
          if (initialized && changed.some((j: any) => j.status === "succeeded")) setNewSamples(true);
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
            window.dispatchEvent(new CustomEvent("otto:jobs-updated", { detail: initialized ? changed : [] }));
          }
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
  }, [
    text,
    JSON.stringify(tags),
    nature,
    star,
    filterMode,
    tagExpression,
    singleTag,
    JSON.stringify(conditions),
    activeFilter,
    JSON.stringify(sort),
  ]);
  useEffect(() => {
    if(results.active)return;
    let active = true;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setBusy(true);
      request("/api/ui/catalog", {
        scope,
        offset,
        limit: pageSize,
        sort: sort.key,
        order: sort.order,
        conditions:
          filterMode === "pitched" || filterMode === "unpitched"
            ? conditions
            : [],
      }, controller.signal)
        .then((v) => {
          if (active) setListing(v);
        })
        .catch(e=>{if(!controller.signal.aborted)report(e)})
        .finally(() => {
          if (active) setBusy(false);
        });
    }, 180);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [
    text,
    JSON.stringify(tags),
    nature,
    star,
    offset,
    epoch,
    sort,
    conditions,
    filterMode,
    results.active,
    pageSize,
    activeFilter,
    tagExpression,
    singleTag,
  ]);
  const rhythmResults = results.result;
  useEffect(()=>{
    if(!rhythmResults)return;
    const frame=requestAnimationFrame(()=>resultTable.current?.scrollTo({top:rhythmResults.state?.scroll||0}));
    const id=rhythmResults.state?.selected_id;
    if(id && rhythmResults.results.some((r:any)=>(r.id||r.material_id)===id&&!r.result_status))void choose(id).catch(report);
    return()=>cancelAnimationFrame(frame);
  },[rhythmResults?.session_id]);
  const rows =
    results.active && rhythmResults
      ? rhythmResults.results.map((r: any) => ({
          ...r,
          id: r.material_id || r.id,
          title: r.sample_title || r.title,
          duration: r.duration ?? r.end - r.start,
          key: r.id || r.material_id,
        }))
      : results.active ? [] : listing.results;
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
    if(r.source_result){const id=r.id||hit?.source_asset_id;results.remember({selected_id:id});setSelectedId(id);}
    setSourceTarget({
      source_id: r.source_id,
      material_id: r.source_result ? undefined : r.id,
      hit_range: hit ? [hit.start, hit.end] : undefined,
      source_range: hit?.source_range,
      source_role: hit?.source_role,
      nonce: Date.now(),
    });
    navigate("sources");
  }
  const toggleStar = (r: any) =>
    run(async () => {
      await api("/" + r.id + "/preferences", { starred: !r.starred });
      refresh();
      results.reload();
      if (selectedId === r.id) await choose(r.id, pid);
    });
  async function selectAllSamples() {
    const ids =
      results.active && rhythmResults
        ? (await request(`/api/library-tools/search-results/${results.active}/ids`)).ids
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
    ids=ids.filter(id=>!rows.find((r:any)=>r.id===id)?.source_result);
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
            refresh();
      },
    });
  }
  const batchMenu=(ids:React.Key[])=>[
    {key:'tags-add',label:`给所选 ${ids.length} 项添加标签…`,onClick:()=>setTagEdit({ids,operation:'add'})},
    {key:'tags-remove',label:`从所选 ${ids.length} 项移除指定标签…`,onClick:()=>setTagEdit({ids,operation:'remove'})},
    {key:'edit',label:`编辑所选 ${ids.length} 项资料…`,onClick:()=>editSamples(ids)},
    {key:'fa',label:`重新 FA 所选 ${ids.length} 项…`,onClick:()=>reanalyse(ids)},
    {key:'model',label:`切换所选 ${ids.length} 项音素模型…`,onClick:()=>setModelIds(ids.map(String))},
    {key:'flatten',label:`批量拉平所选 ${ids.length} 项…`,onClick:()=>setBulkFlatten(true)},
    {key:'delete',label:`删除所选 ${ids.length} 项…`,danger:true,onClick:()=>deleteSamples(ids)}
  ];
  useEffect(()=>{selection.finish()},[browseScopeKey,JSON.stringify(sort),JSON.stringify(conditions),results.active]);
  const rowMenu = (r: any) => checked.includes(r.id)&&checked.length>1 ? batchMenu(checked) : r.source_result ? [{key:'source',label:'打开来源音轨',disabled:!!r.result_status,onClick:()=>sourceFor(r,r.hits?.[0])}] : [
    ...batchMenu([r.id]).slice(0,2),
    { key: "force-fa", label: "重新 FA 所选采样", onClick: () => reanalyse(checked.includes(r.id) ? checked : [r.id]) },
    { key: "phone-times", label: "编辑音素时间 / 切换版本", onClick: () => run(async () => {
      const item=await api("/"+r.id); setTimingTarget({id:r.id,backend:item.active_phone_backend});
    }) },
    { key: "alignment-text", label: "编辑对齐文本 / 预览 G2P", onClick: () => run(async () => {
      const item = await api("/" + r.id); if (!item.cue_id) throw Error("此采样没有文字标注，请先补台词");
      setFrontendTarget({cueId: item.cue_id});
    }) },
    { key: "edit-json", label: "编辑资料…", onClick: () => editSamples([r.id]) },
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
            {!r.source_result && <SampleThumbnail material={r} />}
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
                  if(r.source_result)void auditionHit(r.hits[0],false,false);else void auditionRow(r);
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if(r.source_result)void auditionHit(r.hits[0],false,false);else void auditionRow(r, true);
                }}
              />
            </Tooltip>
          </div>
          <div className="sample-title">
            <span>{v}</span>{r.result_status&&<Tag color="warning">{r.result_status==="deleted"?"采样已删除":"音源已变化"}</Tag>}
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
      render: (v: number) => Number.isFinite(v) ? v.toFixed(2) + "s" : "—",
    },
    {
      title: "",
      key: "star",
      fixed: "right",
      width: 38,
      render: (_: any, r: any) => r.source_result ? null : (
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
    { label: "音高检索", run: () => { navigate("library");setFilterMode("pitch"); } },
    { label: "重新 FA 所选采样", run: () => reanalyse(checked.length ? checked : selectedId ? [selectedId] : []) },
    { label: "用户辞典 / G2P 预览", run: () => setFrontendTarget({}) },
    { label: "编辑所选资料", run: () => editSamples(checked.length ? checked : selectedId ? [selectedId] : []) },
    { label: "撤销最近资料修改", run: () => run(async () => { await api("/edit/undo", {}); refresh(); }) },
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
      <BusinessTextEditor objects={editObjects} onClose={() => setEditObjects(null)} onSaved={() => { refresh(); results.reload(); if(selectedId)void api('/'+selectedId).then(updated=>setSelected((old:any)=>old?.id===updated.id?updated:old)).catch(report); }} />
      <FrontendDialog target={frontendTarget} onClose={() => setFrontendTarget(null)} />
      <PhoneTimingEditor target={timingTarget} onClose={()=>setTimingTarget(null)} onSaved={()=>{refresh();if(selectedId)void choose(selectedId);}} />
      <div className="studio-header">
        <strong className="studio-brand">OttoSmasher <Tag>{edition}</Tag></strong>
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
              allowEmpty
              prefix="BPM"
              placeholder="原速"
              min={20}
              max={400}
              value={playbackBpm}
              onChange={(v: any) => setPlaybackBpm(v)}
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
                ...[1,1.25,1.5].map(factor=>({key:'zoom-'+factor,label:`显示缩放 ${factor*100}%`,onClick:()=>window.ottoDesktop?.zoom?.(factor)})),
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
          hidden={sidebarCollapsed}
          tabIndex={0}

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
          <LibraryFilters singleTag={singleTag} onSingleTag={setSingleTag} scope={scope} conditions={conditions} active={activeFilter} onSelect={setActiveFilter} report={report} tags={info.tags} onTagsChanged={refresh}/>
          <Button type={star?'primary':'text'} icon={<StarOutlined/>} onClick={()=>setStar(!star)}>仅星标</Button>
        </aside>
        <main className="library-stage">
          <div className="studio-toolbar">
            <Button onClick={()=>setSidebarCollapsed(!sidebarCollapsed)} aria-label="切换筛选侧栏">{sidebarCollapsed?"展开筛选":"收起筛选"}</Button>
            <Input
              ref={find}
              prefix={<SearchOutlined />}
              placeholder="搜索采样、原句、备注"
              allowClear
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            {activeFilter&&<Tag closable onClose={()=>setActiveFilter(null)}>筛选器：{activeFilter.name}</Tag>}
            {singleTag&&<Tag closable onClose={()=>setSingleTag(undefined)}>标签范围：{singleTag.replace(/^character:/,'角色：').replace(/^participants:/,'参与者（未分段）：')}</Tag>}
            <span>进一步筛选</span><TagExpressionInput value={tagExpression} onChange={setTagExpression} tags={info.tags||[]} error={tagError}/>

            <Select
              value={filterMode}
              onChange={setFilterMode}
              options={[
                { value: "browse", label: "普通筛选" },
                { value: "speech", label: "语音 · 音块检索" },
                { value: "pitch", label: "独立音高检索" },
                { value: "pitched", label: "单音 · 音色" },
                { value: "unpitched", label: "单音 · 瞬态" },
              ]}
            />
          </div>
          {filterMode === "speech" && (
            <RhythmSearch
              scope={scope}
              onResults={(r,q)=>{void results.add("speech",q,r).catch(report)}}
              onMessage={report}
            />
          )}{" "}
          {filterMode === "pitch" && <PitchSearch scope={scope} onResults={(r,q)=>{void results.add("pitch",q,r).catch(report)}}/>}
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
          {results.bar}
          <ResultStatus result={rhythmResults} onRepeat={()=>run(async()=>{
            if(!rhythmResults)return;
            const kind=rhythmResults.kind;
            const began=performance.now();
            const value=await api(kind==='pitch'?'/pitch-query':'/speech-query',rhythmResults.query);
            await results.add(kind,rhythmResults.query,{...(kind==='pitch'?{...value,results:value.grouped_results,grouped_results:undefined}:value),_ui_started_at:began});
          })}/>
          <div className="studio-toolbar compact">
            <span>
              {results.active && rhythmResults
                ? `${rhythmResults.total} 个命中采样`
                : `${listing.total} 个采样`}
            </span>
            {newSamples && <Button size="small" onClick={() => {setNewSamples(false); refresh();}}>资料已更新 · 刷新浏览列表</Button>}
            <Button onClick={() => run(selectAllSamples)}>选全部匹配结果</Button>
            {checked.length>0&&<><Tag>{checked.length} 项已选</Tag><Dropdown menu={{items:batchMenu(checked)}}><Button>批量操作</Button></Dropdown></>}
            <Button onClick={()=>selection.select([...checked,...rows.filter((r:any)=>!r.source_result&&!r.result_status).map((r:any)=>r.id)])}>选本页</Button>
            <Select aria-label="每页数量" value={pageSizeMode} onChange={(v: any)=>{setPageSizeMode(v)}} options={[{value:0,label:'一屏一页'},...[20,50,100].map(value=>({value,label:`${value} 项 / 页`}))]}/>
            {selection.enabled && (
              <Button type="text" onClick={selection.finish}>
                退出多选
              </Button>
            )}
            <span className="toolbar-spacer" />
            <Help>
              单击查看详情，勾选框选择；⌘ / Ctrl 点击切换选择，Shift 页内连选，翻页保留勾选，Esc 清空。
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
                  ref={catalogPanel}
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
                    ref={resultTable}
                    onScroll={e=>results.scroll((e.currentTarget as HTMLElement).scrollTop)}
                    size="small"
                    virtual
                    scroll={{
                      x: 455,
                      y: Math.max(120,panelHeight-95),
                    }}
                    rowSelection={{columnWidth:32,selectedRowKeys:checked,onChange:keys=>selection.select(keys),preserveSelectedRowKeys:true,getCheckboxProps:(r:any)=>({disabled:!!r.source_result||!!r.result_status})}}
                    rowKey={(r) => r.id}
                    columns={
                      results.active && rhythmResults
                        ? columns.map((c) => ({ ...c, sorter: false }))
                        : columns
                    }
                    dataSource={rows}
                    loading={results.active ? results.loading : busy}
                    pagination={
                      results.active && rhythmResults
                        ? {current:Math.floor(results.offset/pageSize)+1,pageSize,total:rhythmResults.total,showSizeChanger:false,onChange:(p:number)=>results.setOffset((p-1)*pageSize)}
                        : {
                            current: Math.floor(offset / pageSize) + 1,
                            pageSize,
                            total: listing.total,
                            showSizeChanger: false,
                            onChange: (p) => setOffset((p - 1) * pageSize),
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
                      "data-sample-id":r.id,
                      onClick: (e) => {
                        if(r.result_status==='deleted'){message.info("此采样已删除，保留搜索记录供参考");return;}
                        if(r.source_result){void sourceFor(r,r.result_status?undefined:r.hits?.[0]);return;}
                        if (!selection.click(r.id, e))
                          run(() => choose(r.id, r.result_status ? undefined : r.plan_id));
                      },
                      onMouseDown: (e) => {if(e.shiftKey||e.ctrlKey||e.metaKey)e.preventDefault()},
                      onContextMenu: () => {if(r.source_result||r.result_status)selection.finish();else if(!checked.includes(r.id))selection.select([r.id]);setContextRow(r)},
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
                  <ViewBoundary key={selected.id}><Inspector
                    key={selected.id}
                    material={selected}
                    hitPlan={pid}
                    hit={activeHit}
                    hits={
                      rows.find((x: any) => x.id === selected.id)?.hits || []
                    }
                    onHit={locateHit}
                    onSource={() => sourceFor(selected, activeHit)}
                    onAudition={(quantized) => auditionRow(selected, quantized)}
                    onSelect={(id, p) => run(() => choose(id, p))}
                    onRefresh={async () => {
                      const id = selectedId;
                      const updated = await api("/" + id);
                      results.reload();
                      setSelected((previous: any) => previous?.id === id ? updated : previous);
                      setListing((previous: any) => ({...previous, results: previous.results.map((row: any) => row.id === id ? {...row, ...updated} : row)}));
                    }}
                    onMessage={(x) =>
                      x instanceof Error ? report(x) : message.info(String(x))
                    }
                    onFile={setFile}
                            /></ViewBoundary>
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
      {tagEdit&&<TagEdit initial={tagEdit} onClose={()=>setTagEdit(null)} onSaved={()=>{refresh();results.reload()}} report={report}/>}
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
            });
            setBulkFlatten(false);
            message.info("批量拉平已排队；当前列表和选区保持不变，可在任务中查看进度。");
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
                        onClick: () => run(async () => {
                          const detail = await request("/api/helper/jobs/" + j.id);
                          j = detail;
                          if (j.operation === "separate" && j.result?.assets?.length) {
                            modal.info({title:"分离结果 · 声音资产",width:760,content:<>{j.result.assets.map((a:any)=><AssetResult key={a.selection.asset_id} selection={a.selection} name={a.stem} onSaved={()=>refresh()}/>)}</>});
                          } else if (j.operation === "speech-prepare") {
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
                        }),
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
          <RuntimeSettings settings={settings} onChange={setSettings}/>
          <StorageSettings />
          <Button onClick={() => { setSettingsOpen(false); setFrontendTarget({}); }}>编辑用户辞典 / 预览 G2P</Button>
          <Form.Item label="空闲时整理可重建缓存" tooltip="无客户端访问 5 分钟且没有任务时，清理超过 7 天或超出 2 GiB 的临时缓存；不自动删除模型处理结果。">
            <Switch checked={settings.cache_auto_trim !== false} onChange={(v: any) => setSettings({...settings, cache_auto_trim:v})} />
          </Form.Item>
          <Form.Item label="FA 模型顺序（首项为默认，不自动重试其他模型）">
            <Input value={(settings.phone_model_order || [settings.phone_backend, "phonetic", "pydomino"]).join(" ")}
              onChange={e => { const order = e.target.value.trim().split(/\s+/); setSettings({...settings, phone_model_order: order, phone_backend: order[0]}); }} />
            <small>填写 narabas、phonetic（HubertFA）、pydomino，各一次。</small>
          </Form.Item>
          <Form.Item label="FA 前 / 后容差（秒）">
            <Space><InputNumber min={0} max={5} step={0.05} value={settings.fa_padding_before ?? .65}
              onChange={(v: any) => setSettings({...settings, fa_padding_before: v ?? .65})} />
              <InputNumber min={0} max={5} step={0.05} value={settings.fa_padding_after ?? .65}
              onChange={(v: any) => setSettings({...settings, fa_padding_after: v ?? .65})} /></Space>
          </Form.Item>
          <Form.Item label="新采样量化路线">
            <Select
              value={settings.quantization}
              onChange={(v: any) => setSettings({ ...settings, quantization: v })}
              options={[
                { value: "acoustic", label: "原节奏 · 无 mora" },
                { value: "mora_guided", label: "mora 参考校准" },
                { value: "mora", label: "纯 mora" },
              ]}
            />
          </Form.Item>
          <Form.Item label="大数字惩罚度" tooltip="1× 为原权重 0.045。只重建无 mora 的节奏与索引，不重新推理。">
            <InputNumber min={0} max={3} step={0.1} value={settings.large_number_penalty ?? 1}
              onChange={(v: any) => setSettings({...settings, large_number_penalty: v ?? 1})} suffix="×" />
          </Form.Item>
          <Form.Item label="外部 Studio 分离设备">
            <Select value={settings.inference_device || "auto"}
              onChange={(v: any) => setSettings({...settings,inference_device:v})}
              options={[{value:"auto",label:"自动"},{value:"cpu",label:"CPU"},{value:"cuda",label:"CUDA"},{value:"mps",label:"MPS（PyTorch）"}]} />
          </Form.Item>
          {settings.inference_device === "cuda" && <Form.Item label="CUDA 设备编号">
            <InputNumber min={0} precision={0} value={settings.cuda_device ?? 0}
              onChange={(v: any)=>setSettings({...settings,cuda_device:v ?? 0})} />
          </Form.Item>}
          <Button onClick={()=>run(async()=> {
            const result = await request("/api/library-tools/runtime");
            modal.info({title: result.ready ? "ONNX 推理环境" : "环境检查失败",width:700,
              content:<pre className="log-view">{JSON.stringify(result,null,2)}</pre>});
          })}>检查已保存的环境与实际设备</Button>
          <Form.Item label="PyMSS Studio 安装目录（留空自动检测）"><Input value={settings.studio_app} onChange={e=>setSettings({...settings,studio_app:e.target.value})} /></Form.Item>
          <Form.Item label="Studio 数据目录（留空使用默认目录）"><Input value={settings.studio_data} onChange={e=>setSettings({...settings,studio_data:e.target.value})} /></Form.Item>
          <small>先保存目录，再重新打开设置以刷新模型列表。此选项仅用于外部 Studio 和显式启用的 experiment 任务。ONNX 加速在上方单独设置。</small>
          <Form.Item label="默认人声模型">
            <StudioModelSelect
              value={settings.vocal_model}
              onChange={(v: any) => setSettings({ ...settings, vocal_model: v })}
/>
          </Form.Item>
          <Form.Item label="显示人声分离内部进度">
            <Switch
              checked={settings.separation_progress !== false}
              onChange={(v: any) =>
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
              onChange={(v: any) =>
                setSettings({ ...settings, model_concurrency: v })
              }
            />
          </Form.Item>
          <Form.Item label="轻量任务并发数">
            <InputNumber
              min={1}
              max={4}
              value={settings.utility_concurrency || 2}
              onChange={(v: any) =>
                setSettings({ ...settings, utility_concurrency: v })
              }
            />
          </Form.Item>
          <Form.Item label="波形缩放曲线">
            <Select
              value={settings.zoom_curve}
              onChange={(v: any) => setSettings({ ...settings, zoom_curve: v })}
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
              onChange={(v: any) => setSettings({ ...settings, zoom_threshold: v })}
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
