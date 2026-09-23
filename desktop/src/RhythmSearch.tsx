import { usePlaybackTempo } from "./PlaybackTempo";
import React, { useEffect, useRef, useState } from "react";
import {
  Button,
  Checkbox,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Slider,
  Space,
  Tag,
  Segmented,
} from "antd";
import { MoreOutlined, SearchOutlined } from "@ant-design/icons";
import { request } from "./Workspace";
import { Help, useSavedState, uiDefault } from "./Ui";
export function RhythmSearch({
  scope,
  onResults,
  onMessage,
}: {
  scope: any;
  onResults: (r: any) => void;
  onMessage: (e: any) => void;
}) {
  const [notes, setNotes] = useSavedState<any[]>("ui.rhythm.notes", [
      { start_beats: 0, end_beats: 0.5 },
      { start_beats: 1, end_beats: 1.5 },
    ]),
    [span, setSpan] = useSavedState("ui.rhythm.span", 4),
    [step, setStep] = useSavedState("ui.rhythm.step", 0.5),
    [boundary, setBoundary] = useSavedState("ui.rhythm.boundary", "anywhere"),
    [pauses, setPauses] = useSavedState("ui.rhythm.pauses", false),
    [range, setRange] = useSavedState("ui.rhythm.scope", "both"),
    [edit, setEdit] = useState<number | null>(null),
    [options, setOptions] = useState(false),
    [busy, setBusy] = useState(false),
    [status, setStatus] = useState("");
  const [mode, setMode] = useSavedState("ui.speech.policy", (() => {
    let old = "sequence";
    try { old = JSON.parse(localStorage.getItem("ui.speech.mode") || '\"sequence\"'); } catch {}
    localStorage.removeItem("ui.speech.mode");
    localStorage.removeItem("ui.rhythm.aversion");
    return old === "rhythm" ? "required" : "none";
  })());
  const [basis, setBasis] = useSavedState("ui.speech.boundary", "phrase");
  const [cross, setCross] = useSavedState("ui.speech.cross", false);
  const [gap, setGap] = useSavedState<number | null>("ui.speech.gap", null);
  const [bpm] = usePlaybackTempo();
  const sequenceDrag = useRef<number | null>(null);
  const drag = useRef<any>(null);
  const patch = (v: any) => {
    if (edit === null) return;
    const updated = { ...notes[edit], ...v };
    if (
      mode !== "none" &&
      (!(
        updated.start_beats >= 0 &&
        updated.end_beats > updated.start_beats &&
        updated.end_beats <= span
      ) ||
        notes.some(
          (n, i) =>
            i !== edit &&
            n.start_beats < updated.end_beats &&
            n.end_beats > updated.start_beats,
        ))
    ) {
      onMessage(new Error("音块必须在查询范围内，长度为正且不能重叠"));
      return;
    }
    setNotes(notes.map((n, i) => (i === edit ? updated : n)));
  };
  const pos = (e: React.PointerEvent<SVGSVGElement>) =>
    Math.max(
      0,
      Math.min(
        span - step,
        Math.floor(
          (((e.clientX - e.currentTarget.getBoundingClientRect().left) /
            e.currentTarget.getBoundingClientRect().width) *
            span) /
            step,
        ) * step,
      ),
    );
  const hasQueried = useRef(false);
  const queryAbort = useRef<AbortController | null>(null);
  useEffect(() => () => queryAbort.current?.abort(), []);
  const search = async () => {
    hasQueried.current = true;
    const activeNotes =
      mode !== "none"
        ? [...notes].sort((a, b) => a.start_beats - b.start_beats)
        : notes;
    queryAbort.current?.abort();
    const controller = new AbortController();
    queryAbort.current = controller;

    setBusy(true);
    try {
      const unitKeys = [
        "phone",
        "speaker",
        "pitch_trend",
        "pitch_trend_min",
        "pitch_register",
        "pitch_register_min",
        "energy_relative_min_db",
        "strength_min",
        "consonants",
        "pitch_class",
        "octave",
        "tolerance_cents",
        "stability_cents",
        "min_coverage",
        "duration_min",
        "duration_max",
        "duration_measure",
      ];
      const oldKeys = [
        "start_beats",
        "end_beats",
        "phone",
        "speaker",
        "pitch_trend",
        "pitch_trend_min",
        "pitch_register",
        "pitch_register_min",
        "energy_relative_min_db",
        "sustain_to_end",
        "strength_min",
        "duration_min_beats",
        "duration_max_beats",
      ];
      const pick = (n: any, keys: string[]) =>
        Object.fromEntries(
          Object.entries(n).filter(([k, v]) => keys.includes(k) && v != null),
        );
      const r = await request(
        "/api/samples/speech-query",
        {
          rhythm_policy: mode,
          scope,
          units: activeNotes.map((n) => pick(n, unitKeys)),
          boundary,
          boundary_basis: basis,
          cross_pauses: cross,
          max_gap: gap,
          limit: 100,
          rhythm:
            mode !== "none"
              ? {
                  notes: activeNotes.map((n) => pick(n, oldKeys)),
                  span_beats: span,
                  bpm,
                  adjust_pauses: pauses,
                  scope: range,
                  tolerance_beats: Math.min(0.1, step / 3),
                }
              : null,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      onResults(r);
      setStatus(
        `${r.results.length} 个采样 · ${r.hit_count} 处命中 · ${r.elapsed_ms.toFixed(0)} ms${r.index_status?.errors?.length ? " · " + r.index_status.errors.length + " 项缺少有效分析" : ""}`,
      );
    } catch (e) {
      if (!controller.signal.aborted) onMessage(e);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  const searchRef = useRef(search);
  searchRef.current = search;
  useEffect(() => {
    const refresh = () => {
      if (hasQueried.current) void searchRef.current();
    };
    window.addEventListener("otto:speech-index-changed", refresh);
    return () =>
      window.removeEventListener("otto:speech-index-changed", refresh);
  }, []);
  return (
    <div className="rhythm-query">
      <div className="studio-toolbar compact">
        <Segmented
          value={mode}
          onChange={(v) => setMode(String(v))}
          options={[
            { value: "none", label: "不限节奏" },
            { value: "required", label: "必须满足节奏" },
            { value: "rank", label: "按节奏相似度排序" },
          ]}
        />
        {mode !== "none" && (
          <span>{bpm === null ? "归一化节奏形状（无 BPM）" : `BPM ${bpm}`}</span>
        )}
        <Select
          value={boundary}
          onChange={setBoundary}
          options={[
            { value: "anywhere", label: "任意位置" },
            { value: "start", label: "从句首" },
            { value: "end", label: "到句末" },
            { value: "both", label: "句首与句末" },
          ]}
        />
        <Button
          type="primary"
          disabled={!notes.length}
          loading={busy}
          icon={<SearchOutlined />}
          onClick={search}
        >
          查找
        </Button>
        <Button
          type="text"
          icon={<MoreOutlined />}
          aria-label="语音查询设置"
          onClick={() => setOptions(true)}
        />
        <Help>
          {mode === "none"
            ? "拖动编号音块排序，点击设置属性。只匹配相邻音块，缺失测量不会当作零。"
            : "在空白处拖动绘制音块，拖动音块移动、拖动右侧调整长度；右键编辑逐音条件。三种自适应速度参与检索。"}
        </Help>
        <span className="toolbar-spacer" />
        <small>{status}</small>
      </div>
      {mode === "none" ? (
        <Space wrap>
          {notes.map((n, i) => (
            <div
              key={i}
              draggable
              onDragStart={() => {
                sequenceDrag.current = i;
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const from = sequenceDrag.current;
                if (from === null) return;
                const next = [...notes];
                const [moved] = next.splice(from, 1);
                next.splice(i, 0, moved);
                setNotes(
                  next.map((x, j) => ({
                    ...x,
                    start_beats: notes[j].start_beats,
                    end_beats: notes[j].end_beats,
                  })),
                );
                sequenceDrag.current = null;
              }}
            >
              <Button
                style={{ height: 64, minWidth: 110 }}
                onClick={() => setEdit(i)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setEdit(i);
                }}
              >
                <b>{i + 1}</b>{" "}
                {n.pitch_class != null
                  ? [
                      "C",
                      "C♯",
                      "D",
                      "D♯",
                      "E",
                      "F",
                      "F♯",
                      "G",
                      "G♯",
                      "A",
                      "A♯",
                      "B",
                    ][n.pitch_class] + (n.octave ?? "")
                  : "任意音高"}
                <br />
                <small>
                  {n.phone || "任意元音"}{" "}
                  {n.duration_min != null ? `≥${n.duration_min}s` : ""}
                </small>
              </Button>
            </div>
          ))}
          <Button
            onClick={() => {
              const end = Math.max(0, ...notes.map((n) => n.end_beats));
              setNotes([...notes, { start_beats: end, end_beats: end + 0.5 }]);
              setSpan(Math.max(span, end + 0.5));
            }}
          >
            ＋ 音块
          </Button>
        </Space>
      ) : (
        <div className="rhythm-roll">
          <svg
            height="82"
            preserveAspectRatio="none"
            width={Math.max(480, span * 90)}
            viewBox={`0 0 ${span * 90} 82`}
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              const a = pos(e);
              const hit = (e.target as Element).closest("[data-note]");
              const index = hit ? Number(hit.getAttribute("data-note")) : -1;
              const note = notes[index];
              const bounds = e.currentTarget.getBoundingClientRect();
              const edge =
                note &&
                bounds.left +
                  (note.end_beats / span) * bounds.width -
                  e.clientX <
                  9
                  ? "resize"
                  : "move";
              drag.current = { start: a, index, note, edge };
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              const d = drag.current;
              if (!d || d.index < 0) return;
              const delta = pos(e) - d.start;
              const start =
                d.edge === "resize"
                  ? d.note.start_beats
                  : Math.max(
                      0,
                      Math.min(
                        span - (d.note.end_beats - d.note.start_beats),
                        d.note.start_beats + delta,
                      ),
                    );
              const end =
                d.edge === "resize"
                  ? Math.max(
                      start + step,
                      Math.min(span, d.note.end_beats + delta),
                    )
                  : start + d.note.end_beats - d.note.start_beats;
              if (
                !notes.some(
                  (n, i) =>
                    i !== d.index && n.start_beats < end && n.end_beats > start,
                )
              )
                setNotes(
                  notes.map((n, i) =>
                    i === d.index
                      ? { ...n, start_beats: start, end_beats: end }
                      : n,
                  ),
                );
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
            onPointerUp={(e) => {
              if (!drag.current) return;
              if (drag.current.index >= 0) {
                drag.current = null;
                setNotes(
                  [...notes].sort((a, b) => a.start_beats - b.start_beats),
                );
                return;
              }
              const a = drag.current.start,
                b = pos(e);
              drag.current = null;
              const n = {
                start_beats: Math.min(a, b),
                end_beats: Math.min(span, Math.max(a, b) + step),
              };
              if (
                !notes.some(
                  (x) =>
                    x.start_beats < n.end_beats && x.end_beats > n.start_beats,
                )
              )
                setNotes(
                  [...notes, n].sort((x, y) => x.start_beats - y.start_beats),
                );
            }}
          >
            {Array.from({ length: Math.ceil(span / step) + 1 }, (_, i) => (
              <g key={i}>
                <line
                  x1={i * step * 90}
                  x2={i * step * 90}
                  y1="20"
                  y2="82"
                  stroke={(i * step) % 1 === 0 ? "#505e70" : "#293442"}
                />
                {(i * step) % 1 === 0 && (
                  <text
                    x={i * step * 90 + 4}
                    y="13"
                    fill="#a6b5c8"
                    fontSize="11"
                  >
                    {i * step + 1}
                  </text>
                )}
              </g>
            ))}
            {notes.map((n, i) => (
              <g
                key={i}
                data-note={i}
                tabIndex={0}
                role="button"
                aria-label={`音块 ${i + 1}`}
                onDoubleClick={() => setEdit(i)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setEdit(i);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") setEdit(i);
                  if (e.key === "Delete" || e.key === "Backspace")
                    setNotes(notes.filter((_, j) => j !== i));
                }}
              >
                <rect
                  x={n.start_beats * 90 + 1}
                  y="26"
                  width={(n.end_beats - n.start_beats) * 90 - 2}
                  height="44"
                  rx="4"
                  fill="#346ba1"
                />
                <text
                  x={n.start_beats * 90 + 6}
                  y="45"
                  fill="white"
                  fontSize="12"
                >
                  {i + 1} {n.phone || ""}
                  {n.pitch_trend === "up"
                    ? " ↗"
                    : n.pitch_trend === "down"
                      ? " ↘"
                      : ""}
                </text>
                <text
                  x={n.start_beats * 90 + 6}
                  y="62"
                  fill="#c5def8"
                  fontSize="10"
                >
                  {n.sustain_to_end ? "持续" : ""}
                </text>
              </g>
            ))}
          </svg>
        </div>
      )}
      <Modal
        title={edit === null ? "音块属性" : `音块 ${edit + 1}`}
        open={edit !== null}
        onCancel={() => setEdit(null)}
        footer={
          <Space>
            <Button
              danger
              onClick={() => {
                setNotes(notes.filter((_, i) => i !== edit));
                setEdit(null);
              }}
            >
              删除音块
            </Button>
            <Button type="primary" onClick={() => setEdit(null)}>
              完成
            </Button>
          </Space>
        }
      >
        <Form layout="vertical">
          {mode !== "none" && (
            <Space>
              <Form.Item label="起点（拍）">
                <InputNumber
                  min={0}
                  max={span - step}
                  step={step}
                  value={notes[edit ?? -1]?.start_beats}
                  onChange={(v) => v !== null && patch({ start_beats: v })}
                />
              </Form.Item>
              <Form.Item label="终点（拍）">
                <InputNumber
                  min={step}
                  max={span}
                  step={step}
                  value={notes[edit ?? -1]?.end_beats}
                  onChange={(v) => v !== null && patch({ end_beats: v })}
                />
              </Form.Item>
            </Space>
          )}
          <Form.Item label="前导辅音">
            <Select
              value={
                notes[edit ?? -1]?.consonants === undefined
                  ? "any"
                  : notes[edit ?? -1]?.consonants?.length
                    ? "specified"
                    : "none"
              }
              onChange={(v) =>
                patch({
                  consonants:
                    v === "any" ? undefined : v === "none" ? [] : ["k"],
                })
              }
              options={[
                { value: "any", label: "任意" },
                { value: "none", label: "无前导辅音" },
                { value: "specified", label: "指定辅音序列" },
              ]}
            />
            {!!notes[edit ?? -1]?.consonants?.length && (
              <Input
                value={notes[edit ?? -1].consonants.join(" ")}
                placeholder="如 k、sh 或 k y，用空格分隔"
                onChange={(e) =>
                  patch({
                    consonants: e.target.value.split(/\s+/).filter(Boolean),
                  })
                }
              />
            )}
          </Form.Item>
          <Form.Item label="目标音高（留空不限，八度留空匹配音级）">
            <Space>
              <Select
                allowClear
                placeholder="音名"
                style={{ width: 100 }}
                value={notes[edit ?? -1]?.pitch_class}
                onChange={(v) => patch({ pitch_class: v })}
                options={[
                  "C",
                  "C♯",
                  "D",
                  "D♯",
                  "E",
                  "F",
                  "F♯",
                  "G",
                  "G♯",
                  "A",
                  "A♯",
                  "B",
                ].map((label, value) => ({ label, value }))}
              />
              <InputNumber
                placeholder="八度"
                min={-1}
                max={9}
                value={notes[edit ?? -1]?.octave}
                onChange={(v) => patch({ octave: v ?? undefined })}
              />
              <InputNumber
                prefix="±"
                suffix="音分"
                min={0}
                max={600}
                value={notes[edit ?? -1]?.tolerance_cents ?? 50}
                onChange={(v) => patch({ tolerance_cents: v ?? 50 })}
              />
            </Space>
          </Form.Item>
          <Form.Item label="平稳程度（可靠 F0 的 P90−P10）">
            <Space>
              <Checkbox
                checked={notes[edit ?? -1]?.stability_cents != null}
                onChange={(e) =>
                  patch({ stability_cents: e.target.checked ? 100 : undefined })
                }
              >
                限制上限
              </Checkbox>
              <InputNumber
                disabled={notes[edit ?? -1]?.stability_cents == null}
                suffix="音分"
                min={0}
                value={notes[edit ?? -1]?.stability_cents}
                onChange={(v) => patch({ stability_cents: v ?? 100 })}
              />
            </Space>
          </Form.Item>
          <Form.Item label="有效 F0 覆盖率至少">
            <InputNumber
              min={0}
              max={1}
              step={0.1}
              value={notes[edit ?? -1]?.min_coverage ?? 0.5}
              onChange={(v) => patch({ min_coverage: v ?? 0.5 })}
            />
          </Form.Item>
          <Form.Item label="原声时值（秒，留空不限）">
            <Space wrap>
              <Select
                value={notes[edit ?? -1]?.duration_measure || "sustain"}
                onChange={(v) => patch({ duration_measure: v })}
                options={[
                  { value: "sustain", label: "有效持续时长" },
                  { value: "span", label: "音块跨度" },
                ]}
              />
              <InputNumber
                min={0}
                placeholder="下限"
                value={notes[edit ?? -1]?.duration_min}
                onChange={(v) => patch({ duration_min: v ?? undefined })}
              />
              —
              <InputNumber
                min={0}
                placeholder="上限"
                value={notes[edit ?? -1]?.duration_max}
                onChange={(v) => patch({ duration_max: v ?? undefined })}
              />
            </Space>
          </Form.Item>
          <Form.Item label="首元音">
            <Select
              allowClear
              value={notes[edit ?? -1]?.phone}
              onChange={(v) => patch({ phone: v })}
              options={["a", "i", "u", "e", "o"].map((value) => ({
                value,
                label: value,
              }))}
            />
          </Form.Item>
          <Form.Item label="角色">
            <Input
              value={notes[edit ?? -1]?.speaker || ""}
              onChange={(e) => patch({ speaker: e.target.value || undefined })}
            />
          </Form.Item>
          <Form.Item label="音内走势">
            <Select
              allowClear
              value={notes[edit ?? -1]?.pitch_trend}
              onChange={(v) => patch({ pitch_trend: v })}
              options={[
                { value: "up", label: "上扬" },
                { value: "down", label: "下降" },
              ]}
            />
            <InputNumber
              addonAfter="半音"
              min={0}
              max={24}
              value={notes[edit ?? -1]?.pitch_trend_min ?? 1}
              onChange={(v) => patch({ pitch_trend_min: v })}
            />
          </Form.Item>
          <Form.Item label="语段内音高">
            <Select
              allowClear
              value={notes[edit ?? -1]?.pitch_register}
              onChange={(v) => patch({ pitch_register: v })}
              options={[
                { value: "high", label: "偏高" },
                { value: "low", label: "偏低" },
              ]}
            />
            <InputNumber
              addonAfter="半音"
              min={0}
              max={24}
              value={notes[edit ?? -1]?.pitch_register_min ?? 2}
              onChange={(v) => patch({ pitch_register_min: v })}
            />
          </Form.Item>
          <Form.Item label="相对响度下限（留空不限）">
            <InputNumber
              addonAfter="dB"
              min={-40}
              max={40}
              value={notes[edit ?? -1]?.energy_relative_min_db}
              onChange={(v) =>
                patch({ energy_relative_min_db: v ?? undefined })
              }
            />
          </Form.Item>
          {mode !== "none" && (
            <Form.Item label="时值范围（拍，留空不限）">
              <Space>
                <InputNumber min={0} placeholder="下限" value={notes[edit ?? -1]?.duration_min_beats} onChange={v=>patch({duration_min_beats:v??undefined})}/>
                <InputNumber min={0} placeholder="上限" value={notes[edit ?? -1]?.duration_max_beats} onChange={v=>patch({duration_max_beats:v??undefined})}/>
              </Space>
            </Form.Item>
          )}
          <Form.Item label="起音强度下限（0–1，留空不限）">
            <InputNumber min={0} max={1} step={0.1} value={notes[edit ?? -1]?.strength_min} onChange={v=>patch({strength_min:v??undefined})}/>
          </Form.Item>
          {mode !== "none" && (
            <Checkbox
              checked={notes[edit ?? -1]?.sustain_to_end}
              onChange={(e) => patch({ sustain_to_end: e.target.checked })}
            >
              声音必须持续到块尾
            </Checkbox>
          )}
        </Form>
      </Modal>
      <Modal
        title="语音搜索设置"
        open={options}
        onCancel={() => setOptions(false)}
        onOk={() => setOptions(false)}
      >
        <Form layout="vertical">
          <Form.Item label="首尾判断依据">
            <Select
              value={basis}
              onChange={setBasis}
              options={[
                { value: "phrase", label: "连续语段" },
                { value: "sample", label: "整个采样" },
              ]}
            />
          </Form.Item>
          <Checkbox
            checked={cross}
            onChange={(e) => setCross(e.target.checked)}
          >
            允许跨长休止
          </Checkbox>
          <Form.Item label="相邻音块最大间隔（秒，留空不限）">
            <InputNumber min={0} value={gap} onChange={setGap} />
          </Form.Item>
          {mode !== "none" && (
            <>
              <Form.Item label="查询长度（拍）">
                <InputNumber
                  min={1}
                  max={128}
                  value={span}
                  onChange={(v) =>
                    setSpan(Math.max(v || 4, ...notes.map((n) => n.end_beats)))
                  }
                />
              </Form.Item>
              <Form.Item label="绘制网格">
                <Select
                  value={step}
                  onChange={setStep}
                  options={[1, 0.5, 0.25, 0.125].map((v) => ({
                    value: v,
                    label: v + " 拍",
                  }))}
                />
              </Form.Item>
              <Form.Item label="范围">
                <Select
                  value={range}
                  onChange={setRange}
                  options={[
                    { value: "both", label: "整句和连续语段" },
                    { value: "whole", label: "整句" },
                    { value: "segments", label: "连续语段" },
                  ]}
                />
              </Form.Item>
              <Checkbox
                checked={pauses}
                onChange={(e) => setPauses(e.target.checked)}
              >
                允许调整语段之间的休止
              </Checkbox>

            </>
          )}
          <Button onClick={() => setNotes([])}>清空音块</Button>
        </Form>
      </Modal>
    </div>
  );
}
