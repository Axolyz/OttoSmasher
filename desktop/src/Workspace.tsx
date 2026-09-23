import { usePlaybackTempo } from "./PlaybackTempo";
import {
  Button,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tabs,
  Tag,
  Alert,
  Switch,
  Table,
} from "antd";
import {
  MoreOutlined,
  PlusOutlined,
  PlayCircleOutlined,
  ScissorOutlined,
  StarOutlined,
  StarFilled,
} from "@ant-design/icons";
import { Help } from "./Ui";
import React, { useEffect, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import Regions from "wavesurfer.js/dist/plugins/regions.esm.js";
import { audioTimeline, isAnnotation } from "./AudioTimeline";
import { AudioPlayer } from "./MediaTimeline";
import { RhythmMapping } from "./RhythmMapping";
import { Cutter, ask } from "./main";
import { NativeAlignment } from "./NativeAlignment";
// Retain the experimental implementations and installed weights, but close the GUI entry.
const NATIVE_ALIGNMENT_ENTRY_ENABLED = false;
import { FeatureDetails } from "./AcousticFeatures";
export async function request(url: string, body?: any, signal?: AbortSignal) {
  if (
    body &&
    window.ottoDesktop?.player &&
    (/^\/api\/samples\/[^/]+\/reference$/.test(url) ||
      [
        "/api/sound/track-preview",
      ].includes(url))
  )
    body = { ...body, native: true };
  const r = await fetch(
    url,
    body === undefined
      ? { signal }
      : {
          signal,
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
const api = (p: string, b?: any, signal?: AbortSignal) =>
  request("/api/samples" + p, b, signal);
const backends: any = {

  narabas: "narabas",
  phonetic: "HubertFA",
  pydomino: "pydomino（末位备选）",
};
const routes: any = {
  acoustic: "原节奏 · 无 mora",
  mora_guided: "mora 参考校准",
  mora: "纯 mora",
};
const roles: any = {
  selected: "采样绑定的音源",
  vocals: "分离人声",
  raw: "原混音",
  residual: "去人声残差",
  flattened: "拉平声音",
  warped: "卡拍声音",
};
export { default } from "./Workstation";

export function Inspector({
  material: r,
  onSource,
  onAudition,
  hitPlan,
  hit,
  hits = [],
  onHit,
  folders,
  onSelect,
  onRefresh,
  onMessage,
  onFile,
}: {
  material: any;
  onSource: () => void;
  onAudition?: (quantized: boolean) => void;
  hitPlan?: string;
  hit?: any;
  hits?: any[];
  onHit?: (hit: any) => void;
  folders: any[];
  onSelect: (id: string, pid?: string) => void;
  onRefresh: () => Promise<void>;
  onMessage: (e: any) => void;
  onFile: (p: string) => void;
}) {
  const [panel, setPanel] = useState(
      r.cue_id || r.nature === "speech" ? "analysis" : "info",
    ),
    [action, setAction] = useState(""),
    [audition, setAudition] = useState("strict"),
    [flattenMode, setFlattenMode] = useState("all"),
    [override, setOverride] = useState<any>({ category: "work", value: "" });
  const [record, setRecord] = useState<any>(null),
    [error, setError] = useState(""),
    [range, setRange] = useState([0, 1]),
    [anchor, setAnchor] = useState<number | null>(null),
    [role, setRole] = useState("selected"),
    [audioCaps, setAudioCaps] = useState<any>(null),
    [audioReady, setAudioReady] = useState(""),
    [acoustics, setAcoustics] = useState<any>(null),
    [plans, setPlans] = useState<any[]>([]),
    [pid, setPid] = useState(""),
    [preview, setPreview] = useState(""),
    [busy, setBusy] = useState(false),
    [folder, setFolder] = useState(""),
    [cutNature, setCutNature] = useState(r.nature || "unclassified");
  const [bpm] = usePlaybackTempo();
  const audio = useRef<HTMLAudioElement>(null);
  const pendingNativeRange = useRef<{id:string;start:number;end:number}|null>(null);
  const wrap = useRef<HTMLDivElement>(null),
    wave = useRef<WaveSurfer | null>(null),
    regions = useRef<any>(null),
    setting = useRef(false);
  const run = async (fn: () => Promise<any>) => {
    setBusy(true);
    try {
      return await fn();
    } catch (e) {
      onMessage(e);
    } finally {
      setBusy(false);
    }
  };
  const analysisRequest = useRef(0);
  const analysisAbort = useRef<AbortController | null>(null);
  const projectionRequested = useRef(new Set<string>());
  useEffect(
    () => () => {
      ++analysisRequest.current;
      analysisAbort.current?.abort();
    },
    [r.id],
  );
  const getAnalysis = async () => {
    const seq = ++analysisRequest.current;
    analysisAbort.current?.abort();
    const controller = new AbortController();
    analysisAbort.current = controller;
    if (!r) return;
    try {
      const a = await api(
        "/" + r.id + "/analysis?part=display",
        undefined,
        controller.signal,
      );
      if (seq !== analysisRequest.current) return;
      setRecord(a);
      setError("");
    } catch (e) {
      if (seq !== analysisRequest.current) return;
      setRecord(null);
      setError(String(e));
      if (
        String(e).includes("过期") &&
        !projectionRequested.current.has(r.id)
      ) {
        projectionRequested.current.add(r.id);
        void request("/api/helper/jobs", {
          operation: "sample-prepare",
          payload: { material_ids: [r.id] },
        }).catch(onMessage);
      }
    }
  };
  useEffect(() => {
    getAnalysis();
    setPlans([]);
    setPid("");
    setPreview("");
  }, [
    r?.id,
    r?.active_phone_backend,
    r?.active_quantization_strategy,
    JSON.stringify(r?.analysis_settings || {}),
  ]);
  useEffect(() => {
    if (!r || !record) return;
    let dead = false;
    api("/" + r.id + "/plans", {
      bpm,
      ...(hitPlan ? { plan_id: hitPlan } : {}),
    })
      .then((x) => {
        if (!dead) {
          setPlans(x.plans);
          setPid(x.selected_plan_id);
        }
      })
      .catch(onMessage);
    return () => {
      dead = true;
    };
  }, [record?.signature, bpm, hitPlan]);
  useEffect(() => {
    if (!r) return;
    let dead = false;
    setAudioReady("");
    setAcoustics(null);
    api("/" + r.id + "/audio-capabilities")
      .then((x) => {
        if (dead) return;
        setAudioCaps(x);
        setRole(x.default_role);
        setAudioReady(r.id);
      })
      .catch(onMessage);
    return () => {
      dead = true;
    };
  }, [r?.id, r?.audio_asset?.sha256]);
  useEffect(() => {
    if (!r || audioReady !== r.id) return;
    let dead = false;
    const refresh = () =>
      api("/" + r.id + "/acoustics?role=" + role)
        .then((x) => {
          if (!dead) setAcoustics(x);
        })
        .catch(onMessage);
    setAcoustics(null);
    refresh();
    window.addEventListener("otto:jobs-updated", refresh);
    return () => {
      dead = true;
      window.removeEventListener("otto:jobs-updated", refresh);
    };
  }, [r?.id, role, audioReady]);
  useEffect(() => {
    let signature = "";
    const refresh = (event: Event) => {
      const jobs = (event as CustomEvent).detail || [];
      const relevant = jobs.filter(
        (j: any) =>
          j.payload?.material_id === r?.id ||
          j.result?.rows?.some((row: any) => row.material_id === r?.id),
      );
      const next = JSON.stringify(
        relevant.map((j: any) => [
          j.id,
          j.status,
          j.result?.completed,
          j.result?.stage_revision,
        ]),
      );
      if (next !== signature) {
        signature = next;
        if (relevant.length) getAnalysis();
      }
    };
    window.addEventListener("otto:jobs-updated", refresh);
    return () => window.removeEventListener("otto:jobs-updated", refresh);
  }, [r?.id]);
  const hitRef = useRef<any>(null);
  hitRef.current = hit;
  const annotations = (r: any) => [
    ...(r?.analysis?.phones || []).map((p: any, i: number) => ({
      id: `phone-${i}`,
      start: p.start,
      end: p.end,
      label: p.label || p.phone || p.text || "",
    })),
    ...(r?.view?.pauses || []).map((p: any, i: number) => ({
      id: `pause-${i}`,
      start: p.start,
      end: p.end,
      label: "休止",
      color: "#060b1499",
    })),
    ...(hitRef.current && hitRef.current.revision === r?.signature
      ? [
          {
            id: "hit",
            start: hitRef.current.start,
            end: hitRef.current.end,
            label: "命中区",
            color: "#51dfb924",
          },
        ]
      : []),
    ...(r?.view?.units || []).map((u: any, i: number) => ({
      id: `beat-${i}`,
      start: u.time,
      label: hitRef.current?.mapping?.find((m: any) => m.unit_index === i)
        ? JSON.stringify(
            hitRef.current.mapping.find((m: any) => m.unit_index === i)
              .measurements,
          )
        : `音块 ${i + 1}`,
      color: hitRef.current?.unit_indices?.includes(i) ? "#79efce" : "#8eaccf",
    })),
  ];
  const framesRef = useRef<any>(null);
  framesRef.current =
    acoustics?.frames || (role === "selected" ? record?.frames : null);
  const recordRef = useRef<any>(null);
  recordRef.current = role === "selected" ? record : null;
  useEffect(() => {
    (wave.current as any)?.ottoSetFrames(framesRef.current);
    (wave.current as any)?.ottoSetAnnotations(annotations(recordRef.current));
  }, [record, role, acoustics, hit]);
  useEffect(() => {
    if (!hit || !record || hit.revision !== record.signature) return;
    setRange([hit.start, hit.end]);
    wave.current?.setTime(hit.start);
    wave.current?.setScrollTime(Math.max(0, hit.start - 0.3));
  }, [hit, record?.signature]);
  useEffect(() => {
    if (action === "features")
      api("/" + r.id + "/analysis?part=features")
        .then((x) =>
          setRecord((old: any) =>
            old ? { ...old, features: x.features } : old,
          ),
        )
        .catch(onMessage);
  }, [action, r.id]);
  useEffect(() => {
    if (!r || !wrap.current) return;
    let dead = false;
    const controller = new AbortController();
    Promise.all([
      api("/" + r.id + "/waveform?role=" + role, undefined, controller.signal),
      window.ottoDesktop?.player
        ? api(
            "/" + r.id + "/audition",
            { role, native: true },
            controller.signal,
          )
        : Promise.resolve(null),
    ])
      .then(([p, playback]) => {
        if (dead || !wrap.current) return;
        const nativeRange = pendingNativeRange.current?.id === r.id ? pendingNativeRange.current : null;
        pendingNativeRange.current = null;
        const focus = nativeRange || hitRef.current;
        const w = audioTimeline({
          container: wrap.current,
          visualizationKey: p.visualization_key,
          onSelectionChange: (bounds: number[]) => {
            if (!setting.current) setRange(bounds);
          },
          peaks: p.peaks,
          peakLevels: p.peak_levels,
          duration: p.duration,
          url: playback?.url || "/api/samples/" + r.id + "/audio?role=" + role,
          height: 90,
          waveColor: "#577f78",
          progressColor: "#b1efbd",
        });
        const plugin = (w as any).ottoRegions as Regions;
        regions.current = plugin;
        (w as any).ottoSetFrames(framesRef.current);
        wave.current = w;
        w.once("ready", () =>
          plugin.addRegion({
            id: "selection",
            start: focus?.start ?? 0,
            end: focus?.end ?? p.duration,
            color: "#a3edc22a",
            drag: false,
            resize: true,
          }),
        );

        w.on("ready", () => {
          (w as any).ottoSetAnnotations(annotations(recordRef.current));
          if (focus) {
            w.setTime(focus.start);
            w.setScrollTime(Math.max(0, focus.start - 0.3));
          }
        });
        w.on("error", onMessage);
        setRange(
          focus
            ? [focus.start, focus.end]
            : [0, p.duration],
        );
      })
      .catch((e) => {
        if (!controller.signal.aborted) onMessage(e);
      });
    return () => {
      dead = true;
      controller.abort();
      wave.current?.destroy();
      wave.current = null;
    };
  }, [r?.id, role]);
  useEffect(() => {
    const reg = regions.current
      ?.getRegions()
      .find((x: any) => !isAnnotation(x.id));
    if (reg) {
      setting.current = true;
      reg.setOptions({ start: range[0], end: range[1] });
      setting.current = false;
    }
  }, [range[0], range[1]]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        !wrap.current?.getClientRects().length ||
        (e.target as HTMLElement).closest(
          "input,textarea,select,[contenteditable=true],.ant-modal,.ant-select",
        )
      )
        return;
      if (e.key === " ") {
        e.preventDefault();
        wave.current?.playPause();
      } else if (e.key.toLowerCase() === "i")
        setRange((old) => [wave.current?.getCurrentTime() || 0, old[1]]);
      else if (e.key.toLowerCase() === "o")
        setRange((old) => [old[0], wave.current?.getCurrentTime() || 0]);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  if (!r)
    return (
      <section className="inspector empty">
        <h2>选择一个采样</h2>
        <p>查看音素、节奏和音高，或从原句连续选音。</p>
      </section>
    );
  const p = plans.find((p) => p.plan_id === pid),
    phones = record?.analysis.phones || [];
  const prefs = (body: any) =>
    run(async () => {
      await api("/" + r.id + "/preferences", body);
      if (
        body.active_phone_backend ||
        body.active_quantization_strategy ||
        body.analysis_settings
      ) {
        onSelect(r.id);
        window.dispatchEvent(new Event("otto:speech-index-changed"));
      }
      await onRefresh();
    });
  const localTags = r.tags
    .filter((t: any) => t.origin === "manual" && !t.inherited)
    .map((t: any) => t.tag);
  const saveTags = async (tags: string[]) => {
    await request("/api/helper/materials/" + r.id + "/edit", {
      tags: [...new Set(tags)],
    });
    await onRefresh();
  };
  const flattenSelection = async (mode: string) => {
    const job = await api("/" + r.id + "/flatten", {
      mode,
      start: range[0],
      end: range[1],
      role,
    });
    await onRefresh();
    onMessage("当前选区拉平已排队：" + job.id);
  };
  const play = async (mode: string) => {
    const v = await api("/" + r.id + "/preview", { plan_id: pid, mode });
    setPreview(v.url);
  };
  const saveCut = () =>
    run(async () => {
      const child = await api("/" + r.id + "/select", {
        start: range[0],
        end: range[1],
        role,
        folder_id: folder,
        nature: cutNature,
      });
      await onRefresh();
      onSelect(child.id);
      setAction("");
    });
  const actions = [
    { key: "cut", label: "保存选区…", onClick: () => setAction("cut") },
    { key: "flatten", label: "拉平选区…", onClick: () => setAction("flatten") },
    { key: "source", label: "返回原片", onClick: onSource },
    {
      key: "rename",
      label: "重命名",
      onClick: () =>
        run(async () => {
          const title = await ask("采样名称", r.title);
          if (title) {
            await request("/api/helper/materials/" + r.id + "/edit", { title });
            await onRefresh();
          }
        }),
    },
    {
      key: "export",
      label: "导出当前音源",
      onClick: () =>
        run(async () =>
          onFile((await api("/" + r.id + "/export", { role })).path),
        ),
    },
    {
      key: "save-beat",
      label: "保存卡拍结果",
      disabled: !pid,
      onClick: () =>
        run(async () => {
          onFile((await api("/" + r.id + "/export", { plan_id: pid })).path);
          await onRefresh();
        }),
    },
    {
      key: "reaper",
      label: "复制卡拍到 REAPER",
      disabled: !pid,
      onClick: () =>
        run(async () => {
          await api("/" + r.id + "/reaper", { plan_id: pid });
          onMessage("已复制，可在 REAPER 粘贴");
        }),
    },
    {
      key: "separate",
      label: "准备分离音源",
      onClick: () =>
        run(async () => {
          await api("/" + r.id + "/separate", { save: false });
          onMessage("分离任务已排队");
        }),
    },
  ];
  return (
    <section className="inspector modern-inspector">
      <div className="inspector-heading">
        <h2>{r.title}</h2>
        {onAudition && (
          <Button
            type="text"
            aria-label="试听当前采样"
            title="左键原声／右键卡拍"
            icon={<PlayCircleOutlined />}
            onClick={() => onAudition(false)}
            onContextMenu={(e) => {
              e.preventDefault();
              onAudition(true);
            }}
          />
        )}
        <Button
          type="text"
          icon={r.starred ? <StarFilled /> : <StarOutlined />}
          onClick={() => prefs({ starred: !r.starred })}
        />
        <Dropdown menu={{ items: actions }} trigger={["click"]}>
          <Button type="text" icon={<MoreOutlined />} aria-label="采样操作" />
        </Dropdown>
      </div>
      <div className="tag-line">
        {r.tags
          .filter((t: any) => !t.tag.startsWith("cluster:"))
          .map((t: any) => (
            <Tag
              key={t.tag}
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
              title={
                t.origin === "subtitle"
                  ? "字幕提供，未人工确认"
                  : t.origin === "flatten_target"
                    ? "拉平目标音高"
                    : t.inherited
                      ? "来源继承"
                      : "本地标签"
              }
              closable={t.origin === "manual" && !t.inherited}
              onClose={(e) => {
                e.preventDefault();
                void run(() =>
                  saveTags(localTags.filter((v: string) => v !== t.tag)),
                );
              }}
            >
              {t.tag.replace(
                /^(work|character|type|pitch|participants|speaker-status):/,
                "",
              )}
            </Tag>
          ))}
        <Button
          size="small"
          type="dashed"
          icon={<PlusOutlined />}
          aria-label="添加本地标签"
          title="添加本地标签"
          onClick={() =>
            run(async () => {
              const tag = (await ask("添加本地标签"))?.trim();
              if (tag) await saveTags([...localTags, tag]);
            })
          }
        />
      </div>
      <div className="studio-toolbar compact">
        <Select
          value={role}
          onChange={setRole}
          options={["selected", "raw", "vocals", "residual"].map((value) => ({
            value,
            label: roles[value],
            disabled:
              !!audioCaps &&
              !audioCaps.roles.some((x: any) => x.value === value),
          }))}
        />
        {role === "raw" && audioCaps?.errors?.selected && (
          <Tag>当前原混音 · 人声尚未准备</Tag>
        )}
        <Button
          size="small"
          onClick={() =>
            run(async () => {
              await request("/api/helper/jobs", {
                operation: "sample-features",
                payload: { material_id: r.id, role },
              });
              onMessage("音高与能量任务已提交，可在任务面板查看");
            })
          }
        >
          {acoustics?.status === "ready" ? "重新分析音高" : "准备音高"}
        </Button>
        <span className="toolbar-spacer" />
        <Help>
          蓝色为响度包络，金色为可靠
          F0，横线为十二平均律。单击定位，拖动自由选区；Shift 点击整音，Shift
          拖动吸附音素边界。
        </Help>
      </div>
      {hit && (
        <Space wrap>
          <Button
            size="small"
            disabled={hits.findIndex((x) => x.id === hit.id) <= 0}
            onClick={() =>
              onHit?.(hits[hits.findIndex((x) => x.id === hit.id) - 1])
            }
          >
            上一个命中
          </Button>
          <span>
            {hits.findIndex((x) => x.id === hit.id) + 1} / {hits.length}
          </span>
          <Button
            size="small"
            disabled={hits.findIndex((x) => x.id === hit.id) >= hits.length - 1}
            onClick={() =>
              onHit?.(hits[hits.findIndex((x) => x.id === hit.id) + 1])
            }
          >
            下一个命中
          </Button>
          {record && hit.revision !== record.signature && (
            <Tag color="warning">命中已失效，请重新查询</Tag>
          )}
        </Space>
      )}
      <Dropdown menu={{ items: actions }} trigger={["contextMenu"]}>
        <div ref={wrap} />
      </Dropdown>
      <div className="studio-toolbar compact">
        <InputNumber
          aria-label="选区开始"
          precision={3}
          size="small"
          value={range[0]}
          step={0.001}
          onChange={(v) => setRange([v || 0, range[1]])}
        />
        <span>—</span>
        <InputNumber
          aria-label="选区结束"
          precision={3}
          size="small"
          value={range[1]}
          step={0.001}
          onChange={(v) => setRange([range[0], v || 0])}
        />
        <span>s</span>
        <span className="toolbar-spacer" />
        <Button
          type="primary"
          icon={<ScissorOutlined />}
          onClick={() => setAction("cut")}
        >
          保存选区
        </Button>
        <Button onClick={() => setAction("flatten")}>拉平…</Button>
      </div>
      {error && panel === "analysis" && (
        <Alert
          type="warning"
          title="当前音素分析不可用"
          description={error}
          showIcon
        />
      )}
      <Tabs
        activeKey={panel}
        onChange={setPanel}
        items={[
          {
            key: "rhythm",
            label: "节奏与卡拍",
            children: record ? (
              <>
                <div className="studio-toolbar compact">
                  <span>{bpm === null ? "原速卡拍" : `BPM ${bpm}`}</span>
                  <Select
                    value={pid || undefined}
                    onChange={setPid}
                    placeholder="正在准备节奏方案"
                    options={plans.map((p) => ({
                      value: p.plan_id,
                      label: p.label,
                    }))}
                  />
                  {hitPlan && (
                    <Button type="text" onClick={() => onSelect(r.id)}>
                      解除命中
                    </Button>
                  )}
                </div>
                {p && (
                  <>
                    <RhythmMapping plan={p} />
                    <div className="studio-toolbar compact">
                      <Select
                        value={audition}
                        onChange={setAudition}
                        options={[
                          { value: "strict", label: "严格卡拍" },
                          { value: "strict_overlay", label: "卡拍＋节拍" },
                          { value: "strict_rhythm", label: "卡拍起点声" },
                          { value: "original", label: "原始起点声" },
                          { value: "overlay", label: "原声＋原始起点" },
                        ]}
                      />
                      <Button
                        icon={<PlayCircleOutlined />}
                        loading={busy}
                        onClick={() =>
                          run(async () => {
                            if (
                              audition === "original" ||
                              audition === "overlay"
                            ) {
                              const x = await api(
                                "/" + r.id + "/original-clicks",
                                { overlay: audition === "overlay" },
                              );
                              setPreview(x.url);
                            } else await play(audition);
                          })
                        }
                      >
                        试听
                      </Button>
                      <Button type="text" onClick={() => setAction("slots")}>
                        占格编辑…
                      </Button>
                    </div>
                  </>
                )}
              </>
            ) : (
              <EmptyState />
            ),
          },
          {
            key: "analysis",
            label: "音素与分析",
            children: (
              <>
                <Form layout="vertical">
                  <Form.Item label="采用音素模型">
                    <Select
                      value={r.active_phone_backend}
                      options={Object.entries(backends).map(
                        ([value, label]) => ({ value, label: String(label) }),
                      )}
                      onChange={(v) => prefs({ active_phone_backend: v })}
                    />
                  </Form.Item>
                  <Form.Item label="量化路线">
                    <Select
                      value={r.active_quantization_strategy}
                      options={Object.entries(routes).map(([value, label]) => ({
                        value,
                        label: String(label),
                      }))}
                      onChange={(v) =>
                        prefs({ active_quantization_strategy: v })
                      }
                    />
                  </Form.Item>
                </Form>
                <div className="phone-strip">
                  {phones.map((ph: any, i: number) => (
                    <Button
                      key={i}
                      size="small"
                      type={
                        ph.end > range[0] && ph.start < range[1]
                          ? "primary"
                          : "default"
                      }
                      title={`${ph.start.toFixed(3)}–${ph.end.toFixed(3)}s`}
                      onClick={(e) => {
                        const first =
                            e.shiftKey && anchor !== null
                              ? Math.min(anchor, i)
                              : i,
                          last =
                            e.shiftKey && anchor !== null
                              ? Math.max(anchor, i)
                              : i;
                        setRange([phones[first].start, phones[last].end]);
                        if (!e.shiftKey) setAnchor(i);
                      }}
                    >
                      {ph.label}
                      {ph.partial ? "◐" : ""}
                    </Button>
                  ))}
                </div>
                {record && (
                  <p className="context-text">
                    {record.root_cue.original || record.root_cue.spoken}
                  </p>
                )}
                <Space wrap>
                  <Button onClick={() => setAction("advanced")}>
                    分组与停顿…
                  </Button>
                  <Button onClick={() => setAction("features")}>
                    逐音属性…
                  </Button>
                  <Button
                    onClick={() =>
                      run(async () => {
                        await api("/" + r.id + "/prepare", {});
                        await getAnalysis();
                      })
                    }
                  >
                    重建局部分析
                  </Button>
                  {!r.cue_id && (
                    <Button
                      onClick={() =>
                        run(async () => {
                          const text = await ask("实际朗读台词");
                          if (text) {
                            await api("/" + r.id + "/analyze", { text });
                            onMessage("已安排人声及音素分析");
                          }
                        })
                      }
                    >
                      提供台词并分析
                    </Button>
                  )}
                </Space>
                {NATIVE_ALIGNMENT_ENTRY_ENABLED && <NativeAlignment id={r.id} task={()=>onMessage("字符／音节分析已排队，可在任务面板查看")} report={onMessage} locate={(a,b,sourceRole)=>{if(sourceRole!==role)pendingNativeRange.current={id:r.id,start:a,end:b};setRole(sourceRole);setRange([a,b]);wave.current?.setTime(a);wave.current?.setScrollTime(Math.max(0,a-.3));}} />}
                <FeatureDetails id={r.id} />
              </>
            ),
          },
          {
            key: "info",
            label: "资料与来源",
            children: (
              <>
                <Form layout="vertical">
                  <Form.Item label="性质">
                    <Select
                      value={r.nature || "unclassified"}
                      options={[
                        { value: "unclassified", label: "未分类" },
                        { value: "speech", label: "语音" },
                        { value: "pitched", label: "调谐单音" },
                        { value: "unpitched", label: "非调谐单音" },
                      ]}
                      onChange={(v) => prefs({ nature: v })}
                    />
                  </Form.Item>
                  <Form.Item label="归档文件夹">
                    <Select
                      value={r.folder_id}
                      options={[{ id: "", name: "未归档" }, ...folders].map(
                        (f) => ({
                          value: f.id,
                          label: f.name,
                        }),
                      )}
                      onChange={(v) => prefs({ folder_id: v })}
                    />
                  </Form.Item>
                  <Form.Item label="备注">
                    <Input.TextArea
                      defaultValue={r.notes}
                      autoSize={{ minRows: 2, maxRows: 6 }}
                      onBlur={(e) =>
                        run(() =>
                          request("/api/helper/materials/" + r.id + "/edit", {
                            notes: e.target.value,
                          }),
                        )
                      }
                    />
                  </Form.Item>
                  <Form.Item label="评分">
                    <InputNumber
                      min={0}
                      max={5}
                      value={r.rating}
                      onChange={(v) =>
                        run(async () => {
                          await request(
                            "/api/helper/materials/" + r.id + "/edit",
                            { rating: v },
                          );
                          await onRefresh();
                        })
                      }
                    />
                  </Form.Item>
                </Form>
                <Space wrap>
                  <Button onClick={onSource}>返回原片</Button>
                  <Button onClick={() => setAction("tags")}>
                    标签继承与覆盖…
                  </Button>
                  <Button onClick={() => setAction("diagnostics")}>
                    技术详情…
                  </Button>
                </Space>
                {r.derivation && (
                  <p>
                    <Button
                      type="link"
                      onClick={() => onSelect(r.derivation.parent_id)}
                    >
                      ↑ 父采样 · {r.derivation.operation}
                    </Button>
                    <Button
                      onClick={() => {
                        setPreview(
                          "/api/samples/" + r.derivation.parent_id + "/audio",
                        );
                        setPanel("rhythm");
                      }}
                    >
                      试听父采样
                    </Button>
                  </p>
                )}
                {r.children?.length > 0 && (
                  <Table
                    size="small"
                    rowKey="id"
                    pagination={{ pageSize: 5 }}
                    dataSource={r.children}
                    columns={[
                      {
                        title: "派生采样",
                        dataIndex: "title",
                        render: (v: any, id: any) => (
                          <Button type="link" onClick={() => onSelect(id.id)}>
                            {v}
                          </Button>
                        ),
                      },
                    ]}
                  />
                )}
              </>
            ),
          },
        ].sort(
          (a, b) =>
            ["analysis", "rhythm", "info"].indexOf(a.key) -
            ["analysis", "rhythm", "info"].indexOf(b.key),
        )}
      />
      <AudioPlayer key={preview} mediaRef={audio} url={preview} autoPlay />
      <Modal
        title={action === "flatten" ? "拉平选区" : "保存选区"}
        open={["cut", "flatten"].includes(action)}
        onCancel={() => setAction("")}
        confirmLoading={busy}
        onOk={() =>
          action === "cut"
            ? saveCut()
            : run(async () => {
                await flattenSelection(flattenMode);
                setAction("");
              })
        }
      >
        <p>
          {range[0].toFixed(3)}—{range[1].toFixed(3)}s · {roles[role]}
        </p>
        {action === "cut" ? (
          <Form layout="vertical">
            <Form.Item label="性质">
              <Select
                value={cutNature}
                onChange={setCutNature}
                options={[
                  { value: "speech", label: "语音" },
                  { value: "pitched", label: "调谐单音" },
                  { value: "unpitched", label: "非调谐单音" },
                  { value: "unclassified", label: "未分类" },
                ]}
              />
            </Form.Item>
            <Form.Item label="文件夹">
              <Select
                style={{ width: "100%" }}
                value={folder}
                onChange={setFolder}
                options={[{ id: "", name: "未归档" }, ...folders].map((f) => ({
                  value: f.id,
                  label: f.name,
                }))}
              />
            </Form.Item>
          </Form>
        ) : (
          <>
            <Select
              style={{ width: "100%" }}
              value={flattenMode}
              onChange={setFlattenMode}
              options={[
                { value: "all", label: "整个选段（无需字幕）" },
                {
                  value: "vowels",
                  label: "仅元音，保留辅音",
                  disabled: !record,
                },
              ]}
            />
            <Help>
              根据可靠 F0
              选择最近的十二平均律音。仅保存最终拉平采样，保留处理来源；没有可靠
              F0 时报告失败。
            </Help>
          </>
        )}
      </Modal>
      <Modal
        title="人工占格"
        open={action === "slots"}
        onCancel={() => setAction("")}
        footer={<Button onClick={() => setAction("")}>完成</Button>}
      >
        <Table
          size="small"
          pagination={false}
          rowKey="unit_index"
          dataSource={p?.unit_targets || []}
          columns={[
            { title: "音", dataIndex: "label" },
            {
              title: "目标拍",
              dataIndex: "target_beat",
              render: (v) => v.toFixed(3),
            },
            {
              title: "占格",
              render: (_, u, i) => (
                <InputNumber
                  min={1}
                  disabled={!!hitPlan}
                  value={p?.slots?.[i]?.effective_slots || 1}
                  onChange={(value) =>
                    prefs({
                      analysis_settings: {
                        ...r.analysis_settings,
                        slots: { ...r.analysis_settings.slots, [i]: value },
                      },
                    })
                  }
                />
              ),
            },
          ]}
        />
      </Modal>
      <Modal
        title="分组与停顿"
        open={action === "advanced"}
        onCancel={() => setAction("")}
        footer={<Button onClick={() => setAction("")}>完成</Button>}
      >
        <Form layout="vertical">
          <Form.Item label="音素编号前拆点（从 0 计数，逗号分隔）">
            <Input
              defaultValue={(r.analysis_settings.split_before || []).join(",")}
              onBlur={(e) =>
                prefs({
                  analysis_settings: {
                    ...r.analysis_settings,
                    split_before: e.target.value
                      .split(",")
                      .filter(Boolean)
                      .map(Number),
                  },
                })
              }
            />
          </Form.Item>
          <Form.Item label="停顿检测灵敏度">
            <InputNumber
              min={0.2}
              max={3}
              step={0.1}
              value={r.analysis_settings.pause_sensitivity || 1}
              onChange={(v) =>
                prefs({
                  analysis_settings: {
                    ...r.analysis_settings,
                    pause_sensitivity: v,
                  },
                })
              }
            />
          </Form.Item>
          <Form.Item label="独立语段最短停顿（秒）">
            <InputNumber
              min={0.16}
              max={2}
              step={0.01}
              value={
                r.analysis_settings.segments?.pause_threshold_seconds || 0.28
              }
              onChange={(v) =>
                prefs({
                  analysis_settings: {
                    ...r.analysis_settings,
                    segments: {
                      ...r.analysis_settings.segments,
                      pause_threshold_seconds: v,
                    },
                  },
                })
              }
            />
          </Form.Item>
          {r.active_quantization_strategy === "mora" && (
            <Button
              onClick={() =>
                prefs({
                  analysis_settings: {
                    ...r.analysis_settings,
                    auto_long_vowels: !r.analysis_settings.auto_long_vowels,
                  },
                })
              }
            >
              自动长音补格：{r.analysis_settings.auto_long_vowels ? "开" : "关"}
            </Button>
          )}
        </Form>
      </Modal>
      <Modal
        title="逐音属性"
        open={action === "features"}
        onCancel={() => setAction("")}
        footer={null}
        width={760}
      >
        <Table
          rowKey={(_, i) => String(i)}
          dataSource={record?.features || []}
          columns={[
            { title: "首元音", dataIndex: "first_vowel" },
            {
              title: "相对音高",
              dataIndex: "pitch_relative_semitones",
              render: (v) => v?.toFixed(1) ?? "未知",
            },
            {
              title: "音内走向",
              dataIndex: "pitch_trend_semitones",
              render: (v) => v?.toFixed(1) ?? "未知",
            },
            {
              title: "相对响度",
              dataIndex: "energy_relative_db",
              render: (v) => v?.toFixed(1) ?? "未知",
            },
          ]}
        />
      </Modal>
      <Modal
        title="标签继承与本地覆盖"
        open={action === "tags"}
        onCancel={() => setAction("")}
        footer={null}
      >
        <Form layout="vertical">
          <Form.Item label="覆盖来源属性">
            <Select
              value={override.category}
              onChange={(category) => setOverride({ ...override, category })}
              options={[
                { value: "work", label: "作品" },
                { value: "type", label: "来源类型" },
                { value: "character", label: "角色" },
              ]}
            />
            <Input
              value={override.value}
              onChange={(e) =>
                setOverride({ ...override, value: e.target.value })
              }
              placeholder="留空可屏蔽继承值"
            />
          </Form.Item>
          <Space>
            <Button
              onClick={() =>
                run(async () => {
                  await request("/api/ui/tag-override", {
                    material_id: r.id,
                    ...override,
                  });
                  await onRefresh();
                })
              }
            >
              保存本地覆盖
            </Button>
            <Button
              onClick={() =>
                run(async () => {
                  await request("/api/ui/tag-override", {
                    material_id: r.id,
                    category: override.category,
                    reset: true,
                  });
                  await onRefresh();
                })
              }
            >
              恢复来源继承
            </Button>
          </Space>
          {r.tags
            .filter((t: any) => t.origin === "manual")
            .map((t: any) => (
              <p key={t.tag}>
                {t.tag}{" "}
                <Switch
                  checked={!!t.inheritable}
                  checkedChildren="派生继承"
                  unCheckedChildren="不继承"
                  onChange={(inherit) =>
                    run(async () => {
                      await request("/api/ui/tag-rule", {
                        tag: t.tag,
                        inherit,
                      });
                      await onRefresh();
                    })
                  }
                />
              </p>
            ))}
        </Form>
      </Modal>
      <Modal
        title="技术详情"
        open={action === "diagnostics"}
        onCancel={() => setAction("")}
        footer={null}
        width={800}
      >
        <pre className="log-view">
          {JSON.stringify(
            {
              audio: r.audio_asset,
              source: r.path,
              derivation: r.derivation,
              analysis: r.local_analysis_status,
            },
            null,
            2,
          )}
        </pre>
      </Modal>
    </section>
  );
}
function EmptyState() {
  return (
    <p className="muted">此采样尚无节奏分析。可直接播放、截取、拉平或导出。</p>
  );
}
