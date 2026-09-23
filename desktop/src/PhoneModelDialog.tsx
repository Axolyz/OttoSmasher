import React, { useEffect, useState } from "react";
import { Modal, Select, Space, Tag, Button, List, Alert } from "antd";
import { request } from "./Workspace";
export default function PhoneModelDialog({
  ids,
  close,
  changed,
  onError,
}: {
  ids: string[];
  close: () => void;
  changed: () => void;
  onError: (e: any) => void;
}) {
  const [backend, setBackend] = useState("narabas"),
    [data, setData] = useState<any>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    setData(null);
    request("/api/samples/phone-models", { ids, backend })
      .then((x) => {
        if (active) setData(x);
      })
      .catch(onError);
    return () => {
      active = false;
    };
  }, [ids, backend]);
  const apply = async (action: string) => {
    setBusy(true);
    try {
      await request("/api/samples/phone-models", { ids, backend, action });
      changed();
      window.dispatchEvent(new Event("otto:speech-index-changed"));
      close();
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      title="切换音素模型"
      onCancel={close}
      footer={
        <Space>
          <Button onClick={close}>取消</Button>
          <Button
            disabled={!data}
            loading={busy}
            onClick={() => apply("analyze")}
          >
            分析缺失项并切换
          </Button>
          <Button
            type="primary"
            disabled={!data}
            loading={busy}
            onClick={() => apply("switch")}
          >
            切换已有结果
          </Button>
        </Space>
      }
    >
      <Select
        value={backend}
        onChange={setBackend}
        style={{ width: "100%" }}
        options={[

          { value: "narabas", label: "narabas" },
          { value: "phonetic", label: "HubertFA" },
          { value: "pydomino", label: "pydomino（末位备选）" },
        ]}
      />
      {data && (
        <>
          <Space style={{ marginTop: 16 }}>
            <Tag color="green">有效 {data.ready.length}</Tag>
            <Tag>缺失 {data.missing.length}</Tag>
            <Tag color="red">失败 {data.failed.length}</Tag>
            <Tag>不适用 {data.ineligible.length}</Tag>
          </Space>
          <Alert
            type="info"
            title="缺失或失败项保留当前模型；分析成功后才切换。绑定音源不变。"
          />
          <List
            size="small"
            dataSource={[...data.missing, ...data.failed, ...data.ineligible]}
            style={{ maxHeight: 260, overflow: "auto" }}
            renderItem={(x: any) => <List.Item>{x.title}</List.Item>}
          />
        </>
      )}
    </Modal>
  );
}
