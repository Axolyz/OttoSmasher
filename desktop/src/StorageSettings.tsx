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
        正式声音共享 LAME VBR V0 音轨，裁切和模型结果保存区间引用。临时音频、波形及试听缓存按最近使用时间回收；默认上限 512 MiB。有效分析和人工编辑保留。
      </Typography.Paragraph>
      {storage && <Typography.Paragraph>日常资料库 {size(storage.daily_bytes)} · 原片、模型和环境不计入；备份及开发验证数据另列。展开类别查看用途、模型和文件类型。</Typography.Paragraph>}
      <Table size="small" pagination={false} rowKey="key" loading={!storage && !error}
        dataSource={storage?.categories || []} columns={[
          { title: "类别", dataIndex: "title", render: (v:string,r:any)=>v+(r.excluded?"（预算外）":"") },
          { title: "文件数", dataIndex: "files" },
          { title: "占用", dataIndex: "total_bytes", render: size },
          { title: "可清理", dataIndex: "reclaimable_bytes", render: size },
          { title: "保留／引用中", dataIndex: "protected_bytes", render: size },
          { title: "近期生成", dataIndex: "recent_bytes", render: (v:number)=>size(v || 0) },
        ]} />
      {!!storage?.source_audio?.length && <><Typography.Paragraph>按原片归属的持久音轨（共享文件只计一次；数据库、通用索引和临时输入见上表）</Typography.Paragraph>
        <Table size="small" rowKey="key" pagination={{pageSize:12}} dataSource={storage.source_audio} columns={[{title:"原片／集数",dataIndex:"title"},{title:"持久音频",dataIndex:"total_bytes",render:size}]}/></>}
      {error && <Alert type="error" showIcon title={error} />}
      <Tooltip title="最近 15 分钟生成的文件暂不清理；有任务运行时不能清理。">
        <Button loading={busy} disabled={!storage || !storage.reclaimable_bytes}
          style={{ marginTop: 12 }} onClick={clean}>清理缓存与闲置结果</Button>
      </Tooltip>
    </>,
  }]} />;
}
