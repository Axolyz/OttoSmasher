import { VideoPlayer } from "./NativePlayer";
import {
  Button,
  Dropdown,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tabs,
  Alert,
} from "antd";
import { Help } from "./Ui";
import React, { useEffect, useRef, useState } from "react";
import { request } from "./Workspace";
import { ask } from "./main";
import { audioTimeline } from "./AudioTimeline";
export function OpeningMarkers({
  onMessage,
  sourceIds,
}: {
  onMessage: (x: any) => void;
  sourceIds?: string[];
}) {
  const [dialog, setDialog] = useState(""),
    [scanStart, setScanStart] = useState(0),
    [scanEnd, setScanEnd] = useState<number | null>(null),
    [manualSource, setManualSource] = useState("");
  const [sources, setSources] = useState<any[]>([]),
    [ids, setIds] = useState<string[]>(sourceIds || []),
    [image, setImage] = useState("");
  const [duration, setDuration] = useState(90),
    [offset, setOffset] = useState(0),
    [kind, setKind] = useState("op");
  const [state, setState] = useState<any>({ regions: [], scans: [] }),
    [job, setJob] = useState(""),
    [scanId, setScanId] = useState("");
  const [preview, setPreview] = useState<any>(null),
    [edits, setEdits] = useState<Record<string, number[]>>({});
  const [manualStart, setManualStart] = useState(0);
  const video = useRef<HTMLVideoElement>(null),
    wave = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (sourceIds?.length) {
      setIds(sourceIds);
      setManualSource(sourceIds[0]);
    }
  }, [JSON.stringify(sourceIds)]);
  const refresh = () =>
    request("/api/library-tools/openings/state").then(setState).catch(onMessage);
  useEffect(() => {
    request("/api/preparation").then((x) =>
      setSources(
        x.sources.map((s: any) => ({
          ...s,
          title: s.work + (s.episode ? " · " + s.episode : ""),
        })),
      ),
    );
    refresh();
  }, []);
  useEffect(() => {
    if (!job) return;
    const timer = setInterval(async () => {
      try {
        const j = (await request("/api/helper/jobs")).find(
          (x: any) => x.id === job,
        );
        if (!j) return;
        if (["succeeded", "failed", "cancelled"].includes(j.status)) {
          setJob("");
          refresh();
          setScanId(job);
          onMessage(j.error || "参考帧扫描完成，候选需人工确认");
        }
      } catch (e) {
        onMessage(e);
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [job]);
  useEffect(() => {
    if (!preview?.waveform || !video.current || !wave.current) return;
    const w = audioTimeline({
      container: wave.current,
      visualizationKey: preview.waveform.visualization_key,
      media: video.current,
      peaks: preview.waveform.peaks,
      duration: preview.duration,
      origin: preview.origin,
      minPxPerSec: 80,
    });
    return () => w.destroy();
  }, [preview]);
  useEffect(() => {
    if (!preview?.waveform_url || preview.waveform) return;
    let stale = false;
    request(preview.waveform_url)
      .then((waveform) => {
        if (!stale) setPreview((p: any) => (p ? { ...p, waveform } : p));
      })
      .catch(onMessage);
    return () => {
      stale = true;
    };
  }, [preview?.url]);
  const scan = state.scans.find((x: any) => x.id === scanId) || state.scans[0];
  async function review(c: any, a: number, b: number, tail = false) {
    try {
      const r = await request("/api/samples/source-browser", {
        source_id: c.source_id,
      });
      const start = tail ? Math.max(0, b - 4) : Math.max(0, a - 3),
        end = Math.min(r.source_duration, tail ? b + 3 : a + 7);
      const p = await request(`/api/samples/${r.id}/reference`, {
        start,
        end,
        role: "raw",
      });
      setPreview({ ...p, title: c.title });
    } catch (e) {
      onMessage(e);
    }
  }
  async function confirm(c: any) {
    try {
      await request("/api/library-tools/openings/confirm", {
        ...c,
        evidence: { scan_id: scan?.id, similarity: c.similarity },
      });
      await refresh();
      onMessage("标记已保存");
    } catch (e) {
      onMessage(e);
    }
  }
  return (
    <div className="opening-markers">
      <div className="studio-toolbar compact">
        <Select
          mode="multiple"
          style={{ minWidth: 240, flex: 1 }}
          maxTagCount={2}
          placeholder="选择原片"
          value={ids}
          onChange={setIds}
          options={sources.map((s) => ({ value: s.id, label: s.title }))}
        />
        <Button
          type="primary"
          disabled={!ids.length || !!job}
          onClick={() => setDialog("scan")}
        >
          {job ? "扫描中…" : "参考帧扫描…"}
        </Button>
        <Button
          disabled={!ids.length}
          onClick={() => {
            setManualSource(ids[0]);
            setDialog("manual");
          }}
        >
          手动标记…
        </Button>
        <Help>
          标记排除自动台词登记、批量语音分析、角色分析和音效候选；手动截取、整轨分离和原片播放仍可用。撤销标记不会删除已有采样。
        </Help>
      </div>
      <Tabs
        items={[
          {
            key: "saved",
            label: `已有标记 (${state.regions.length})`,
            children: (
              <Table
                size="small"
                rowKey="id"
                dataSource={state.regions.filter(
                  (r: any) => !ids.length || ids.includes(r.source_id),
                )}
                pagination={{ pageSize: 8 }}
                columns={[
                  { title: "原片", dataIndex: "title", ellipsis: true },
                  {
                    title: "类型",
                    dataIndex: "kind",
                    width: 65,
                    render: (v) => v.toUpperCase(),
                  },
                  {
                    title: "时间",
                    width: 165,
                    render: (_, r: any) =>
                      `${r.start.toFixed(2)}–${r.end.toFixed(2)}s`,
                  },
                  {
                    title: "来源",
                    dataIndex: "origin",
                    width: 120,
                    render: (v) => (
                      <Tag>
                        {v === "subtitle-rule" ? "字幕规则" : "人工确认"}
                      </Tag>
                    ),
                  },
                  {
                    title: "",
                    width: 150,
                    render: (_, r: any) => (
                      <Space>
                        <Button
                          size="small"
                          onClick={() => review(r, r.start, r.end)}
                        >
                          查看
                        </Button>
                        <Button
                          size="small"
                          onClick={async () => {
                            try {
                              await request("/api/library-tools/openings/remove", {
                                id: r.id,
                              });
                              refresh();
                            } catch (e) {
                              onMessage(e);
                            }
                          }}
                        >
                          撤销
                        </Button>
                      </Space>
                    ),
                  },
                ]}
              />
            ),
          },
          {
            key: "candidates",
            label: "扫描候选",
            children: (
              <>
                <Select
                  value={scan?.id}
                  style={{ width: 300, marginBottom: 12 }}
                  onChange={setScanId}
                  options={state.scans.map((s: any) => ({
                    value: s.id,
                    label:
                      s.id.slice(0, 8) + " · " + s.candidates.length + " 候选",
                  }))}
                />
                <Table
                  rowKey={(_, i) => String(i)}
                  size="small"
                  dataSource={scan?.candidates || []}
                  pagination={{ pageSize: 8 }}
                  columns={[
                    { title: "原片", dataIndex: "title", ellipsis: true },
                    {
                      title: "相似度",
                      dataIndex: "similarity",
                      width: 80,
                      render: (v) => v.toFixed(3),
                    },
                    {
                      title: "范围",
                      width: 225,
                      render: (_, c: any, i: number) => {
                        const k = scan.id + ":" + i,
                          [a, b] = edits[k] || [c.start, c.end];
                        return (
                          <Space>
                            <InputNumber
                              size="small"
                              value={a}
                              step={0.01}
                              onChange={(v) =>
                                setEdits({ ...edits, [k]: [v || 0, b] })
                              }
                            />
                            <InputNumber
                              size="small"
                              value={b}
                              step={0.01}
                              onChange={(v) =>
                                setEdits({ ...edits, [k]: [a, v || 0] })
                              }
                            />
                          </Space>
                        );
                      },
                    },
                    {
                      title: "审核",
                      width: 210,
                      render: (_, c: any, i: number) => {
                        const [a, b] = edits[scan.id + ":" + i] || [
                          c.start,
                          c.end,
                        ];
                        return (
                          <Space>
                            <Button
                              size="small"
                              onClick={() => review(c, a, b)}
                            >
                              开头
                            </Button>
                            <Button
                              size="small"
                              onClick={() => review(c, a, b, true)}
                            >
                              结尾
                            </Button>
                            <Button
                              size="small"
                              type="primary"
                              onClick={() =>
                                confirm({ ...c, start: a, end: b })
                              }
                            >
                              确认
                            </Button>
                          </Space>
                        );
                      },
                    },
                  ]}
                />
                {scan?.failures.map((f: any) => (
                  <Alert
                    key={f.source_id}
                    type="warning"
                    title={f.title}
                    description={f.reason}
                  />
                ))}
              </>
            ),
          },
        ]}
      />
      {preview && (
        <>
          <div className="studio-toolbar compact">
            <span>
              {preview.title} · {preview.origin.toFixed(2)}s
            </span>
            <span className="toolbar-spacer" />
            <Button onClick={() => setPreview(null)}>关闭预览</Button>
          </div>
          <VideoPlayer
            ref={video}
            src={preview.url}
            controls
            style={{ maxHeight: 300, width: "100%" }}
          />
          <div ref={wave} />
        </>
      )}
      <Modal
        title={dialog === "scan" ? "参考帧扫描" : "手动标记范围"}
        open={!!dialog}
        onCancel={() => setDialog("")}
        okText={dialog === "scan" ? "开始扫描" : "保存标记"}
        onOk={async () => {
          try {
            if (dialog === "scan") {
              const j = await request("/api/library-tools/openings/scan", {
                image,
                source_ids: ids,
                duration,
                reference_offset: offset,
                kind,
                scan_start: scanStart,
                scan_end: scanEnd,
              });
              setJob(j.id);
              onMessage("参考帧扫描已排队；扫描结果需要审核");
            } else
              await confirm({
                source_id: manualSource,
                start: manualStart,
                end: manualStart + duration,
                kind,
              });
            setDialog("");
          } catch (e) {
            onMessage(e);
          }
        }}
        okButtonProps={{ disabled: dialog === "scan" && !image }}
      >
        <Form layout="vertical">
          {dialog === "scan" ? (
            <>
              <Form.Item label="参考图片">
                <Input
                  type="file"
                  accept="image/*"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) {
                      const reader = new FileReader();
                      reader.onload = () => setImage(String(reader.result));
                      reader.readAsDataURL(f);
                    }
                  }}
                />
                {image && (
                  <img
                    src={image}
                    style={{ maxWidth: 200, maxHeight: 110, marginTop: 8 }}
                  />
                )}
              </Form.Item>
              <Form.Item label="参考帧距片头偏移（秒）">
                <InputNumber
                  min={0}
                  value={offset}
                  onChange={(v) => setOffset(v || 0)}
                />
              </Form.Item>
              <Form.Item label="扫描范围（秒；结束留空为全片）">
                <Space>
                  <InputNumber
                    min={0}
                    value={scanStart}
                    onChange={(v) => setScanStart(v || 0)}
                  />
                  <InputNumber min={0} value={scanEnd} onChange={setScanEnd} />
                </Space>
              </Form.Item>
              <Help>
                逐帧索引可复用；首次需要解码，之后参考帧查询复用缓存。已知大致位置时缩小范围更快。
              </Help>
            </>
          ) : (
            <>
              <Form.Item label="原片">
                <Select
                  value={manualSource}
                  onChange={setManualSource}
                  options={sources
                    .filter((s) => ids.includes(s.id))
                    .map((s) => ({ value: s.id, label: s.title }))}
                />
              </Form.Item>
              <Form.Item label="开始秒">
                <InputNumber
                  min={0}
                  value={manualStart}
                  onChange={(v) => setManualStart(v || 0)}
                />
                <Button
                  onClick={() =>
                    review(
                      { source_id: manualSource },
                      manualStart,
                      manualStart + duration,
                    )
                  }
                >
                  查看
                </Button>
              </Form.Item>
            </>
          )}
          <Form.Item label="用途">
            <Select
              value={kind}
              onChange={setKind}
              options={[
                { value: "op", label: "OP" },
                { value: "ed", label: "ED" },
              ]}
            />
          </Form.Item>
          <Form.Item label="长度（秒）">
            <InputNumber
              min={0.1}
              max={900}
              value={duration}
              onChange={(v) => setDuration(v || 90)}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
