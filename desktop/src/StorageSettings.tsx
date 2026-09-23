import React, { useEffect, useState } from "react";
import { Alert, App, Button, Collapse, Table, Tooltip, Typography } from "antd";
import { request } from "./Workspace";
const size = (bytes: number) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} GiB` : `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
export default function StorageSettings() {
  const { message } = App.useApp();
  const [storage, setStorage] = useState<any>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    request("/api/ui/storage").then(x => { if (alive) setStorage(x); })
      .catch(e => { if (alive) setError(String(e)); });
    return () => { alive = false; };
  }, []);
  async function clean() {
    setBusy(true); setError("");
    try {
      const r = await request("/api/ui/storage/clean", {});
      setStorage(r.storage);
      message.success(`已清理 ${r.removed_files} 个文件，${size(r.freed_bytes)}；跳过 ${r.skipped_files} 个正在使用或变动的文件`);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return <Collapse style={{ marginBottom: 20 }} items={[{
    key: "cache", label: `存储与缓存${storage ? ` · 可清理 ${size(storage.reclaimable_bytes)}` : ""}`,
    children: <>
      <Typography.Paragraph type="secondary">
        保留原片、字幕、模型、已保存采样、有效分析及正在使用的分离轨。清理后首次试听或查看波形可能重新生成缓存。
      </Typography.Paragraph>
      <Table size="small" pagination={false} rowKey="key" loading={!storage && !error}
        dataSource={storage?.categories || []} columns={[
          { title: "类别", dataIndex: "title" },
          { title: "占用", dataIndex: "total_bytes", render: size },
          { title: "可清理", dataIndex: "reclaimable_bytes", render: size },
        ]} />
      {error && <Alert type="error" showIcon title={error} />}
      <Tooltip title="最近 15 分钟生成的文件暂不清理；有任务运行时不能清理。">
        <Button loading={busy} disabled={!storage || !storage.reclaimable_bytes}
          style={{ marginTop: 12 }} onClick={clean}>清理缓存与闲置结果</Button>
      </Tooltip>
    </>,
  }]} />;
}
