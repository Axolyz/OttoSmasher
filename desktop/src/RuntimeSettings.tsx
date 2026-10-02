import React, { useState } from "react";
import { Alert, Button, Form, Input, Space, Switch, Table, Tag } from "antd";
import { DraftNumber as InputNumber } from "./DraftNumber";
import { request } from "./Workspace";
export function RuntimeSettings({
  settings,
  onChange,
}: {
  settings: any;
  onChange: (v: any) => void;
}) {
  const [check, setCheck] = useState<any>(null),
    [busy, setBusy] = useState(false),
    [text, setText] = useState("(京子) おはよう"),
    [parsed, setParsed] = useState<any>(null);
  async function probe() {
    setBusy(true);
    try {
      setCheck(await request("/api/library-tools/runtime"));
    } catch (e) {
      setCheck({ error: String(e) });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Form.Item
        label="ONNX 硬件加速"
        tooltip="Windows：DirectML；macOS：CoreML（GPU／神经网络引擎）；关闭则使用 CPU。设备变更用于后续任务。"
      >
        <Switch
          checked={!!settings.onnx_acceleration}
          onChange={(v) => onChange({ ...settings, onnx_acceleration: v })}
        />
      </Form.Item>
      <Form.Item label="DirectML 设备编号（Windows）">
        <InputNumber
          min={0}
          precision={0}
          value={settings.onnx_device_id ?? 0}
          onChange={(v: number) => onChange({ ...settings, onnx_device_id: v })}
        />
      </Form.Item>
      <Button loading={busy} onClick={probe}>
        检测已保存的环境与模型
      </Button>
      {check && (
        <>
          <Alert
            type={check.probe_passed ? "success" : "warning"}
            message={
              check.probe_passed
                ? "运行库探测通过（不代表所有模型已实测）"
                : check.error || check.probe_error || "运行库不可用"
            }
            description={`加速后端：${check.accelerator || "此平台未支持"}；可用：${(check.onnx_providers || []).join("、")}`}
          />
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={check.models || []}
            columns={[
              { title: "模型", dataIndex: "id" },
              {
                title: "文件",
                render: (_: any, r: any) => (
                  <span
                    title={r.files
                      .filter((f: any) => !f.present)
                      .map((f: any) => f.path)
                      .join("\n")}
                  >
                    {r.files_ready ? "就位" : "缺失"}
                  </span>
                ),
              },
              { title: "推理", dataIndex: "inference_status" },
            ]}
          />
        </>
      )}
      <Form.Item label="字幕采样前／后容差（秒）">
        <Space>
          <InputNumber
            min={0}
            max={5}
            step={0.1}
            value={settings.subtitle_padding_before ?? 0.3}
            onChange={(v: number) =>
              onChange({ ...settings, subtitle_padding_before: v })
            }
          />
          <InputNumber
            min={0}
            max={5}
            step={0.1}
            value={settings.subtitle_padding_after ?? 0.3}
            onChange={(v: number) =>
              onChange({ ...settings, subtitle_padding_after: v })
            }
          />
        </Space>
      </Form.Item>
      <Form.Item label="音效字幕整行正则">
        <Input.TextArea
          value={settings.subtitle_event_pattern}
          onChange={(e) =>
            onChange({ ...settings, subtitle_event_pattern: e.target.value })
          }
        />
      </Form.Item>
      <Form.Item label="括号内容提取正则（命名组 content）">
        <Input.TextArea
          value={settings.subtitle_bracket_pattern}
          onChange={(e) =>
            onChange({ ...settings, subtitle_bracket_pattern: e.target.value })
          }
        />
      </Form.Item>
      <Space.Compact style={{ width: "100%" }}>
        <Input value={text} onChange={(e) => setText(e.target.value)} />
        <Button
          onClick={async () => {
            try {
              setParsed(
                await request("/api/preparation/subtitle-rule-preview", {
                  text,
                  settings,
                }),
              );
            } catch (e) {
              setParsed({ error: String(e) });
            }
          }}
        >
          测试规则
        </Button>
      </Space.Compact>
      {parsed && (
        <pre style={{ whiteSpace: "pre-wrap" }}>
          {JSON.stringify(parsed, null, 2)}
        </pre>
      )}
    </>
  );
}
