import { DraftNumber as InputNumber } from "./DraftNumber";
import React, { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Modal,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import { request } from "./Workspace";
const api = (p: string, b?: any) => request("/api/preparation" + p, b);
export function TrackRoles({
  sourceId,
  report,
}: {
  sourceId: string;
  report: (e: any) => void;
}) {
  const [tracks, setTracks] = useState<any[]>([]);
  const load = () =>
    api("/roles?source_id=" + encodeURIComponent(sourceId))
      .then(setTracks)
      .catch(report);
  useEffect(() => {
    void load();
  }, [sourceId]);
  async function change(t: any, roles: string[], defaults: string[]) {
    try {
      setTracks(
        await api("/roles", {
          source_id: sourceId,
          asset_id: t.id,
          roles,
          defaults: defaults.filter((r) => roles.includes(r)),
        }),
      );
    } catch (e) {
      report(e);
    }
  }
  return (
    <div>
      <p>
        同角色音轨共享区间标签；默认轨用于后续字幕采样，已有采样和分析不会换轨。
      </p>
      <Table
        size="small"
        rowKey="id"
        dataSource={tracks}
        pagination={{ pageSize: 8 }}
        columns={[
          {
            title: "声音资产",
            render: (_: any, t: any) => (
              <span title={t.path}>
                {t.title} · 轨 {t.stream} · {t.start?.toFixed(1)}–
                {t.end?.toFixed(1)}s
              </span>
            ),
          },
          {
            title: "角色",
            render: (_: any, t: any) => (
              <Select
                mode="multiple"
                style={{ minWidth: 160 }}
                value={t.roles}
                options={[
                  { value: "speech", label: "人声" },
                  { value: "effects", label: "音效" },
                ]}
                onChange={(v) => change(t, v, t.defaults)}
              />
            ),
          },
          {
            title: "默认",
            render: (_: any, t: any) => (
              <Space>
                {t.roles.map((r: string) => (
                  <Checkbox
                    key={r}
                    checked={t.defaults.includes(r)}
                    onChange={(e) =>
                      change(
                        t,
                        t.roles,
                        e.target.checked
                          ? [...t.defaults, r]
                          : t.defaults.filter((v: string) => v !== r),
                      )
                    }
                  >
                    {r === "speech" ? "人声" : "音效"}
                  </Checkbox>
                ))}
              </Space>
            ),
          },
        ]}
      />
    </div>
  );
}
export function SubtitleSamples({
  sourceId,
  kind,
  onClose,
  onSaved,
  report,
}: {
  sourceId: string;
  kind: string;
  onClose: () => void;
  onSaved: () => void;
  report: (e: any) => void;
}) {
  const [plan, setPlan] = useState<any>(null),
    [selected, setSelected] = useState<React.Key[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [start, setStart] = useState<number | null>(null),
    [end, setEnd] = useState<number | null>(null);
  const scope = () => ({
    source_id: sourceId,
    kind,
    ...(start !== null ? { start } : {}),
    ...(end !== null ? { end } : {}),
  });
  async function preview() {
    setBusy(true);
    setError("");
    try {
      const p = await api("/subtitle-samples", scope());
      setPlan(p);
      setSelected(
        p.rows.filter((r: any) => r.status === "ready").map((r: any) => r.id),
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void preview();
  }, [sourceId, kind]);
  async function save() {
    setBusy(true);
    try {
      const body = { ...scope(), selected_ids: selected };
      await api("/subtitle-samples", {
        ...body,
        token: plan.token,
        apply: true,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(String(e));
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      width={850}
      title={kind === "event" ? "从字幕导入音效采样" : "从字幕导入台词语音"}
      onCancel={onClose}
      onOk={save}
      okText={`创建 ${selected.length} 项`}
      confirmLoading={busy}
      okButtonProps={{ disabled: !selected.length }}
    >
      <Space wrap>
        <InputNumber
          placeholder="起始秒（不限）"
          value={start}
          onChange={(v: number | null) => {
            setStart(v);
            setPlan(null);
            setSelected([]);
          }}
          min={0}
        />
        <InputNumber
          placeholder="结束秒（不限）"
          value={end}
          onChange={(v: number | null) => {
            setEnd(v);
            setPlan(null);
            setSelected([]);
          }}
          min={0}
        />
        <Button onClick={preview}>预览范围</Button>
      </Space>
      <p>
        可勾选字幕分批创建；默认前后各扩展 0.3
        秒，可在设置中调整。已导入、已删除和 OP/ED 排除项不会重复创建。
      </p>
      {error && <Alert type="error" message={error} />}
      <Table
        size="small"
        rowKey="id"
        dataSource={plan?.rows || []}
        scroll={{ y: 300 }}
        rowSelection={{
          selectedRowKeys: selected,
          onChange: setSelected,
          getCheckboxProps: (r: any) => ({ disabled: r.status !== "ready" }),
        }}
        columns={[
          { title: "名称", dataIndex: "title" },
          {
            title: "采样区间",
            render: (_: any, r: any) =>
              `${r.start.toFixed(3)}–${r.end.toFixed(3)}`,
          },
          {
            title: "状态",
            render: (_: any, r: any) => (
              <Tag>
                {
                  (
                    {
                      ready: "待创建",
                      imported: "已导入",
                      deleted: "已删除",
                      excluded: "OP/ED 排除",
                      outside: "轨道范围外",
                      empty: "无有效名称",
                    } as any
                  )[r.status]
                }
              </Tag>
            ),
          },
        ]}
      />
    </Modal>
  );
}

export function SubtitleMarkers({
  sourceIds,
  onClose,
  onSaved,
  report,
}: {
  sourceIds: string[];
  onClose: () => void;
  onSaved: () => void;
  report: (e: any) => void;
}) {
  const [plans, setPlans] = useState<any[]>([]),
    [selected, setSelected] = useState<React.Key[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [start, setStart] = useState<number | null>(null),
    [end, setEnd] = useState<number | null>(null);
  useEffect(() => {
    setBusy(true);
    Promise.all(sourceIds.map((source_id) => api("/preview", { source_id })))
      .then((p) => {
        setPlans(p);
        setSelected(
          p.flatMap((v) =>
            v.rows
              .filter((r: any) => r.status !== "invalid")
              .map((r: any) => v.source_id + ":" + r.ordinal),
          ),
        );
      })
      .catch((e) => setError(String(e)))
      .finally(() => setBusy(false));
  }, [sourceIds]);
  const rows = plans
    .flatMap((p) =>
      p.rows.map((r: any) => ({
        ...r,
        source_id: p.source_id,
        id: p.source_id + ":" + r.ordinal,
      })),
    )
    .filter(
      (r) =>
        (start === null || r.end > start) && (end === null || r.start < end),
    );
  async function save() {
    setBusy(true);
    try {
      for (const p of plans) {
        const ordinals = rows
          .filter((r) => r.source_id === p.source_id && selected.includes(r.id))
          .map((r) => r.ordinal);
        if (!ordinals.length) continue;
        if (p.op_review === "pending")
          await api("/configure", {
            source_id: p.source_id,
            op_review: "skipped",
          });
        await api("/import", {
          source_id: p.source_id,
          token: p.token,
          ordinals,
        });
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(String(e));
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      width={850}
      title="导入字幕标记"
      onCancel={onClose}
      onOk={save}
      confirmLoading={busy}
      okButtonProps={{ disabled: !rows.some((r) => selected.includes(r.id)) }}
      okText="导入勾选标记"
    >
      <p>
        只保存标记，不创建采样。可分批勾选，也可限定时间范围；未标记的 OP/ED
        本次按暂时跳过检查处理。
      </p>
      <Space>
        <InputNumber
          placeholder="起始秒（不限）"
          min={0}
          value={start}
          onChange={setStart}
        />
        <InputNumber
          placeholder="结束秒（不限）"
          min={0}
          value={end}
          onChange={setEnd}
        />
      </Space>
      {error && <Alert type="error" message={error} />}
      <Table
        size="small"
        rowKey="id"
        scroll={{ y: 350 }}
        dataSource={rows}
        rowSelection={{
          selectedRowKeys: selected,
          preserveSelectedRowKeys: true,
          onChange: setSelected,
          getCheckboxProps: (r: any) => ({ disabled: r.status === "invalid" }),
        }}
        columns={[
          { title: "原文", dataIndex: "text" },
          {
            title: "区间",
            render: (_: any, r: any) =>
              `${r.start.toFixed(3)}–${r.end.toFixed(3)}`,
          },
          {
            title: "状态",
            render: (_: any, r: any) =>
              r.status === "excluded"
                ? "OP/ED 标记（采样时跳过）"
                : r.status === "invalid"
                  ? "无效范围"
                  : "可导入",
          },
        ]}
      />
    </Modal>
  );
}
