import { useListSelection } from "./ListSelection";
import React, { useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Splitter,
  Table,
  Tag,
  Tabs,
  Checkbox,
} from "antd";
import { PlusOutlined, MoreOutlined, SearchOutlined } from "@ant-design/icons";
import { Cutter } from "./main";
import { request } from "./Workspace";
import { OpeningMarkers } from "./OpeningMarkers";
import { Help, useSavedState, uiDefault } from "./Ui";
const api = (p: string, b?: any) => request("/api/preparation" + p, b);
export function SourcesWorkspace({
  active,
  target,
  materialIds,
  onMessage,
  onRefresh,
  onSample,
  onFile,
}: {
  active: boolean;
  target: any;
  materialIds: string[];
  onMessage: (x: any) => void;
  onRefresh: () => void;
  onSample: (id: string) => void;
  onFile: (p: string) => void;
}) {
  const { modal } = App.useApp();
  const [viewport, setViewport] = useState(window.innerHeight);
  useEffect(() => {
    const resize = () => setViewport(window.innerHeight);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const [sources, setSources] = useState<any[]>([]),
    [ids, setIds] = useState<string[]>([]),
    [toolIds, setToolIds] = useState<string[]>([]),
    [contextSource, setContextSource] = useState<any>(null),
    [sid, setSid] = useSavedState("ui.source.selected", ""),
    [current, setCurrent] = useState<any>(null),
    [text, setText] = useState(""),
    [busy, setBusy] = useState(false),
    [dialog, setDialog] = useState(""),
    [importIds, setImportIds] = useState<string[]>([]),
    [importSpeakers, setImportSpeakers] = useSavedState(
      "ui.import-speakers",
      false,
    ),
    [editing, setEditing] = useState<any>({}),
    [paths, setPaths] = useState(""),
    [markers, setMarkers] = useState<any>(null),
    [analysisScope, setAnalysisScope] = useState<any>(null),
    [report, setReport] = useState<any>(null),
    [backends, setBackends] = useState<string[]>([
      uiDefault("phone_backend", "narabas"),
    ]),
    [vocal, setVocal] = useState(() =>
      uiDefault("vocal_model", "becruily_deux"),
    );
  useEffect(() => {
    if (dialog === "analysis") {
      setVocal(uiDefault("vocal_model", "becruily_deux"));
      setBackends([uiDefault("phone_backend", "narabas")]);
    }
  }, [dialog]);
  const loadGeneration = useRef(0);
  const load = async () => {
    const generation = ++loadGeneration.current;
    const r = await api("");
    if (generation === loadGeneration.current) {
      setSources(r.sources);
      const available = new Set(r.sources.map((s: any) => s.id));
      // The jobs listener survives source selection changes. Reconcile against
      // current state, never the sid captured when that listener was installed.
      setCurrent((current: any) =>
        current && !available.has(current.source_id) ? null : current,
      );
      setSid((selected: string) => available.has(selected) ? selected : "");
    }
    return r.sources;
  };
  useEffect(() => {
    if (!active) return;
    const refresh = () => {
      void load().catch(onMessage);
    };
    refresh();
    window.addEventListener("otto:jobs-updated", refresh);
    return () => window.removeEventListener("otto:jobs-updated", refresh);
  }, [active]);
  const run = async (f: () => Promise<any>) => {
    setBusy(true);
    try {
      return await f();
    } catch (e) {
      onMessage(e);
    } finally {
      setBusy(false);
    }
  };
  async function browse(id: string) {
    const r = await request("/api/samples/source-browser", { source_id: id });
    setCurrent(r);
    setSid(id);
  }
  useEffect(() => {
    run(async () => { const rows = await load(); if (sid && rows.some((s: any) => s.id === sid)) await browse(sid); });
  }, []);
  useEffect(() => {
    if (target?.material_id)
      run(async () => {
        const r = await request("/api/samples/" + target.material_id);
        if(target.hit_range && r.audio_asset?.root_knots) {
          const knots=r.audio_asset.root_knots;
          const map=(t:number)=>{ let i=0;while(i<knots.length-2&&knots[i+1][0]<t)i++;const a=knots[i],b=knots[i+1];return a[1]+(t-a[0])*(b[1]-a[1])/(b[0]-a[0]); };
          r.start=map(target.hit_range[0]);r.end=map(target.hit_range[1]);
        }
        setCurrent(r);
        setSid(r.source_id);
      });
    else if (target?.source_id) run(() => browse(target.source_id));
  }, [target]);
  useEffect(() => {
    const f = (e: Event) => {
      setAnalysisScope((e as CustomEvent).detail);
      setDialog("analysis");
    };
    window.addEventListener("otto:analysis-dialog", f);
    return () => window.removeEventListener("otto:analysis-dialog", f);
  }, []);
  useEffect(() => {
    if (dialog === "analysis" && analysisScope) {
      let live = true;
      api("/analysis", { ...analysisScope, backends, vocal_model: vocal })
        .then((r) => {
          if (live) setReport(r);
        })
        .catch((e) => {
          if (live) setReport({ error: String(e) });
        });
      return () => {
        live = false;
      };
    }
  }, [dialog, analysisScope, backends, vocal]);
  async function add(list: string[]) {
    if (!list.length) return;
    const r = await api("/register", { paths: list });
    await load();
    setIds([]);
    await browse(r.source_ids[0]);
    setDialog("");
    onRefresh();
    const updated = await api("");
    const first = updated.sources.find((s: any) => s.id === r.source_ids[0]);
    setEditing({
      ...first,
      subtitle_path:
        first?.preparation?.subtitle_path || first?.subtitle_path || "",
    });
    setDialog("metadata");
  }
  async function pick() {
    if (window.ottoDesktop) await add(await window.ottoDesktop.pick());
    else setDialog("add");
  }
  async function edit(s: any) {
    setEditing({
      ...s,
      subtitle_path: s.preparation?.subtitle_path || s.subtitle_path || "",
    });
    setDialog("metadata");
  }
  const selected = sources.find((s) => s.id === sid);
  const rows = sources.filter((s) =>
    (s.work + " " + s.title + " " + s.episode)
      .toLowerCase()
      .includes(text.toLowerCase()),
  );
  const selection = useListSelection(
    ids,
    setIds,
    rows.map((s) => s.id),
  );
  const scopeIds = ids;
  useEffect(() => {
    if (!active) selection.finish();
  }, [active]);
  async function importSub(s: any) {
    const r = await api("/import-direct", {
      source_id: s.id,
      import_speakers: importSpeakers,
    });
    await load();
    onRefresh();
    onMessage(
      `台词已登记：${r.ready} 条，排除 ${r.excluded} 条；重复条目自动跳过`,
    );
  }
  async function detect() {
    const r = await api("/music-markers", { source_ids: scopeIds });
    setMarkers(r);
    await load();
    onRefresh();
    setDialog("markers");
  }
  const deleteSources = (selected: string[]) => {
    if (!selected.length) return;
    modal.confirm({title: `删除 ${selected.length} 个原片登记？`, content: "删除关联字幕、分析与音轨登记，保留磁盘原始文件。有采样引用的原片需先删除采样。", okText: "删除", okButtonProps: {danger: true},
      onOk: async () => { await api("/delete", {ids: selected});
        if (selected.includes(sid)) { window.dispatchEvent(new Event("otto:pause-media")); setCurrent(null); setSid(""); }
        selection.finish(); await load(); onRefresh(); } });
  };
  const menu = (s: any) => [
    ...selection.menu(s.id),
    {key: "delete", label: "删除原片", danger: true, onClick: () => deleteSources(ids.includes(s.id) ? ids : [s.id])},
    { key: "metadata", label: "作品、字幕与音轨…", onClick: () => edit(s) },
    {
      key: "import",
      label: "导入字幕为台词",
      disabled: !s.subtitle_path && !s.preparation?.subtitle_path,
      onClick: () => {
        setImportIds([s.id]);
        setDialog("import");
      },
    },
    {
      key: "markers",
      label: "从字幕识别 OP / ED",
      onClick: () => {
        setToolIds([s.id]);
        run(async () => {
          setMarkers(await api("/music-markers", { source_ids: [s.id] }));
          await load();
          setDialog("markers");
        });
      },
    },
    {
      key: "opening",
      label: "参考帧 / 手动标记…",
      onClick: () => {
        setToolIds([s.id]);
        setDialog("opening");
      },
    },
    {
      key: "analyse",
      label: "准备语音分析…",
      onClick: () => {
        setAnalysisScope({ source_ids: [s.id] });
        setDialog("analysis");
      },
    },
  ];
  return (
    <div className="sources-stage">
      <div className="studio-toolbar">
        <h2>原片</h2>
        <Input
          prefix={<SearchOutlined />}
          placeholder="搜索作品 / 集数"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => run(pick)}
        >
          添加原片
        </Button>
        <Button onClick={() => selection.select(rows.map((s: any) => s.id))}>全选</Button>
        {ids.length > 0 && <Button danger onClick={() => deleteSources(ids)}>删除</Button>}
        {selection.enabled && (
          <>
            {ids.length > 0 && (
              <Dropdown
                menu={{
                  items: [
                    {
                      key: "markers",
                      label: "从字幕识别 OP / ED",
                      disabled: !scopeIds.length,
                      onClick: () => run(detect),
                    },
                    {
                      key: "opening",
                      label: "参考帧 / 手动标记",
                      disabled: !scopeIds.length,
                      onClick: () => {
                        setToolIds(ids);
                        setDialog("opening");
                      },
                    },
                    {
                      key: "analysis",
                      label: "准备所选范围语音分析",
                      disabled: !scopeIds.length,
                      onClick: () => {
                        setAnalysisScope({ source_ids: scopeIds });
                        setDialog("analysis");
                      },
                    },
                    {
                      key: "import",
                      label: "导入所选原片字幕",
                      disabled: !scopeIds.length,
                      onClick: () => {
                        setImportIds(scopeIds);
                        setDialog("import");
                      },
                    },
                  ],
                }}
              >
                <Button icon={<MoreOutlined />}>
                  所选 {scopeIds.length} 项
                </Button>
              </Dropdown>
            )}
            <Button type="text" onClick={selection.finish}>
              退出多选
            </Button>
          </>
        )}
        <Help>
          添加原片不创建采样。没有字幕也可浏览、选区、分离、拉平和导出。字幕导入会跳过已标记的
          OP / ED 和重复条目。
        </Help>
      </div>
      <Splitter className="source-split">
        <Splitter.Panel defaultSize="30%" min={260}>
          <Dropdown
            trigger={["contextMenu"]}
            menu={{ items: contextSource ? menu(contextSource) : [] }}
          >
            <div
              onKeyDown={(e) => {
                if ((e.target as HTMLElement).closest("input,textarea")) return;
                if (e.key === "Escape") selection.finish();
                if (["Delete", "Backspace"].includes(e.key)) { e.preventDefault(); deleteSources(ids.length ? ids : sid ? [sid] : []); }
                if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") { e.preventDefault(); selection.select(rows.map((s: any) => s.id)); }
              }}
              tabIndex={-1}
            >
              <Table
                rowKey="id"
                size="small"
                pagination={false}
                dataSource={rows}
                scroll={{ y: Math.max(220, viewport - 200) }}
                rowClassName={(s) =>
                  selection.enabled
                    ? ids.includes(s.id)
                      ? "multi-selected-row"
                      : ""
                    : s.id === sid
                      ? "selected-row"
                      : ""
                }
                onRow={(s) => ({
                  onClick: (e) => {
                    if (!selection.click(s.id, e)) run(() => browse(s.id));
                  },
                  onContextMenu: () => setContextSource(s),
                })}
                columns={[
                  {
                    title: "作品 / 集数",
                    render: (_: any, s: any) => (
                      <div className="sample-title">
                        <strong title={s.title}>
                          {s.work || s.title}
                          {s.episode ? " · " + s.episode : ""}
                        </strong>
                        <div className="tag-line">
                          <Tag>
                            {s.subtitle_path || s.preparation?.subtitle_path
                              ? `${s.cues} 句`
                              : "无字幕"}
                          </Tag>
                          {s.analyzed > 0 && (
                            <Tag color="blue">{s.analyzed} 已分析</Tag>
                          )}
                          {s.regions.length > 0 && (
                            <Tag color="green">OP/ED {s.regions.length}</Tag>
                          )}
                          {s.media_type && <Tag>{s.media_type}</Tag>}
                        </div>
                      </div>
                    ),
                  },
                ]}
              />
            </div>
          </Dropdown>
        </Splitter.Panel>
        <Splitter.Panel min={430}>
          <div className="source-player-scroll">
            {current ? (
              <Cutter
                material={current}
                onSave={(id) =>
                  run(async () => {
                    const r = await request("/api/samples/" + id);
                    if (r.pool === "source-browser") {
                      setCurrent(r);
                      setSid(r.source_id);
                    } else onSample(id);
                  })
                }
                onMessage={onMessage}
                onFile={onFile}
                onImport={() => run(pick)}
              />
            ) : (
              <Empty description="添加或选择原片，即可开始播放与截取" />
            )}
          </div>
        </Splitter.Panel>
      </Splitter>
      <Modal
        title="导入字幕台词"
        open={dialog === "import"}
        onCancel={() => setDialog("")}
        okText="导入"
        confirmLoading={busy}
        onOk={() =>
          run(async () => {
            for (const id of importIds)
              await importSub(sources.find((s) => s.id === id));
            setDialog("");
          })
        }
      >
        <p>
          导入 {importIds.length} 个原片的字幕，自动跳过已登记台词与排除范围。
        </p>
        <Checkbox
          checked={importSpeakers}
          onChange={(e) => setImportSpeakers(e.target.checked)}
        >
          根据字幕括号登记说话人
        </Checkbox>
        <Help>
          标签注明来自字幕。多人或群体保留参与者与文字片段，不推断先后时间或自动拆句；音效说明不作为角色名。
        </Help>
      </Modal>
      <Modal
        title="添加原片"
        open={dialog === "add"}
        onCancel={() => setDialog("")}
        confirmLoading={busy}
        onOk={() =>
          run(() =>
            add(
              paths
                .split("\n")
                .map((x) => x.trim())
                .filter(Boolean),
            ),
          )
        }
      >
        <Input.TextArea
          rows={5}
          placeholder="每行一个本机媒体绝对路径"
          value={paths}
          onChange={(e) => setPaths(e.target.value)}
        />
      </Modal>
      <Modal
        title="作品与输入设置"
        open={dialog === "metadata"}
        onCancel={() => setDialog("")}
        confirmLoading={busy}
        onOk={() =>
          run(async () => {
            const base = sources.find((s) => s.id === editing.id);
            const value = { ...base, ...editing };
            await request("/api/ui/source-labels", {
              source_id: value.id,
              work: value.work,
              episode: value.episode,
              media_type: value.media_type,
            });
            await api("/configure", {
              source_id: value.id,
              ...(value.subtitle_path
                ? { subtitle_path: value.subtitle_path }
                : {}),
              audio_stream: value.audio_stream,
            });
            await load();
            setDialog("");
            onRefresh();
          })
        }
      >
        <Form layout="vertical">
          {["work", "episode", "media_type"].map((k, i) => (
            <Form.Item
              key={k}
              label={["作品名", "集数", "来源类型（可选）"][i]}
            >
              <Input
                value={
                  editing[k] ?? sources.find((s) => s.id === editing.id)?.[k]
                }
                placeholder={
                  k === "media_type" ? "例如 动画 / 真人 / 游戏" : ""
                }
                onChange={(e) =>
                  setEditing({ ...editing, [k]: e.target.value })
                }
              />
            </Form.Item>
          ))}
          <Form.Item label="字幕（可选）">
            <Space.Compact style={{ width: "100%" }}>
              <Input
                value={
                  editing.subtitle_path ??
                  sources.find((s) => s.id === editing.id)?.preparation
                    ?.subtitle_path
                }
                onChange={(e) =>
                  setEditing({ ...editing, subtitle_path: e.target.value })
                }
              />
              <Button
                onClick={() =>
                  run(async () => {
                    const path =
                      await window.ottoDesktop?.pickFile?.("subtitle");
                    if (path) setEditing({ ...editing, subtitle_path: path });
                  })
                }
              >
                选择文件
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item label="分析音轨">
            <Select
              value={
                editing.audio_stream ??
                sources.find((s) => s.id === editing.id)?.audio_stream
              }
              options={(
                sources.find((s) => s.id === editing.id)?.tracks || []
              ).map((t: any) => ({
                value: t.index,
                label: `${t.index} · ${t.tags?.language || "未标语言"} · ${t.tags?.title || t.codec_name}`,
              }))}
              onChange={(v) => setEditing({ ...editing, audio_stream: v })}
            />
          </Form.Item>
          <Help>
            作品和来源类型会实时传递给已有与新建派生采样；采样上的本地覆盖优先。无须导入字幕即可截取。
          </Help>
        </Form>
      </Modal>
      <Modal
        title="OP / ED 标记"
        open={dialog === "opening"}
        onCancel={() => {
          setDialog("");
          load();
          onRefresh();
        }}
        footer={null}
        width={1080}
      >
        <OpeningMarkers sourceIds={toolIds} onMessage={onMessage} />
      </Modal>
      <Modal
        title="字幕音乐区间"
        open={dialog === "markers"}
        onCancel={() => setDialog("")}
        footer={<Button onClick={() => setDialog("")}>完成</Button>}
        width={800}
      >
        <Table
          rowKey="source_id"
          pagination={false}
          dataSource={markers?.sources || []}
          columns={[
            { title: "原片", dataIndex: "title" },
            {
              title: "识别",
              render: (_: any, r: any) =>
                r.pairs.map((p: any, i: number) => (
                  <div key={i}>
                    {p.kind.toUpperCase()} · {p.start.toFixed(2)}–
                    {p.end.toFixed(2)}s{" "}
                    {!r.automatic && (
                      <Button
                        size="small"
                        onClick={() =>
                          run(async () => {
                            await request("/api/library-tools/openings/confirm", {
                              source_id: r.source_id,
                              ...p,
                              evidence: { method: "subtitle-rule-reviewed" },
                            });
                            await load();
                            onRefresh();
                            onMessage("标记已确认");
                          })
                        }
                      >
                        确认此区间
                      </Button>
                    )}
                  </div>
                )),
            },
            {
              title: "状态",
              render: (_: any, r: any) =>
                r.automatic ? (
                  <Tag color="green">规则识别 · 已应用 / 已存在</Tag>
                ) : (
                  <span>{r.errors.join("；") || "未发现成对标记"}</span>
                ),
            },
          ]}
        />
      </Modal>
      <Modal
        title="准备语音分析"
        open={dialog === "analysis"}
        onCancel={() => setDialog("")}
        confirmLoading={busy}
        okText="补齐缺失分析"
        okButtonProps={{ disabled: !report?.total || !!report?.error }}
        onOk={() =>
          run(async () => {
            const j = await api("/analysis", {
              ...analysisScope,
              backends,
              vocal_model: vocal,
              run: true,
            });
            onMessage("任务已排队，可在右上角查看进度");
            setDialog("");
          })
        }
      >
        <Form layout="vertical">
          <Form.Item label="人声模型">
            <Select
              value={vocal}
              onChange={setVocal}
              options={[
                { value: "becruily_deux", label: "becruily Deux" },
                { value: "bs_roformer_voc_hyperacev2", label: "HyperACE" },
              ]}
            />
          </Form.Item>
          <Form.Item label="音素模型">
            <Checkbox.Group
              value={backends}
              onChange={(v) => setBackends(v as string[])}
              options={[

                { value: "narabas", label: "narabas" },
                { value: "phonetic", label: "HubertFA" },
                { value: "pydomino", label: "pydomino（末位备选）" },
              ]}
            />
          </Form.Item>
          {report?.error ? (
            <Alert type="error" title={report.error} />
          ) : (
            <>
              <p>{report?.total ?? "…"} 条台词</p>
              {report?.dependencies?.map((d: any) => (
                <div key={d.name}>
                  <Tag color={d.ready ? "green" : "red"}>
                    {d.ready ? "环境已找到" : "缺失"}
                  </Tag>
                  {d.label || d.name}
                  {d.error && <Alert type="error" title={d.error} />}
                </div>
              ))}
            </>
          )}
          <Help>
            环境检查仅确认解释器存在，不代表模型推理已通过。只处理明确选定范围；复用已有结果，模型串行运行。无字幕素材可直接截取、分离及全选区拉平，音素与节奏分析才需要文本。
          </Help>
        </Form>
      </Modal>
    </div>
  );
}
