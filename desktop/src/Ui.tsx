import React, { useState } from "react";
import {
  Button,
  Input,
  Select,
  Checkbox,
  Modal,
  Tooltip,
  theme,
  ConfigProvider,
  App,
} from "antd";
import { InfoCircleOutlined } from "@ant-design/icons";
import zhCN from "antd/locale/zh_CN";
export function UiRoot({ children }: { children: React.ReactNode }) {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: [theme.darkAlgorithm, theme.compactAlgorithm],
        token: {
          colorPrimary: "#79b8ff",
          colorBgBase: "#14171c",
          borderRadius: 6,
          fontSize: 13,
          controlHeight: 30,
        },
        components: {
          Table: { cellPaddingBlock: 8 },
          Layout: { headerBg: "#171b21", siderBg: "#171b21" },
        },
      }}
    >
      <App>{children}</App>
    </ConfigProvider>
  );
}
export function Help({ children }: { children: React.ReactNode }) {
  return (
    <Tooltip title={children}>
      <InfoCircleOutlined
        tabIndex={0}
        className="help-icon"
        aria-label="说明"
      />
    </Tooltip>
  );
}
// Transitional adapters preserve native event contracts while all built-in pages share Ant controls.
export function UButton({
  children,
  className,
  ...p
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <Button
      {...(p as any)}
      className={className}
      type={className?.split(" ").includes("active") ? "primary" : "default"}
    >
      {children}
    </Button>
  );
}
export function USelect({
  children,
  onChange,
  value,
  defaultValue,
  ...p
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const opts: any[] = [];
  const visit = (nodes: React.ReactNode) =>
    React.Children.forEach(nodes, (n) => {
      if (!React.isValidElement(n)) return;
      const x = n.props as any;
      if (n.type === "option")
        opts.push({
          value: String(x.value ?? x.children),
          label: x.children,
          disabled: x.disabled,
        });
      else visit(x.children);
    });
  visit(children);
  return (
    <Select
      {...(p as any)}
      value={value == null ? undefined : String(value)}
      defaultValue={defaultValue == null ? undefined : String(defaultValue)}
      options={opts}
      onChange={(v) =>
        onChange?.({ target: { value: v }, currentTarget: { value: v } } as any)
      }
      popupMatchSelectWidth={false}
    />
  );
}
export function UInput({
  type,
  onChange,
  onBlur,
  ...p
}: React.InputHTMLAttributes<HTMLInputElement>) {
  if (type === "checkbox")
    return <Checkbox {...(p as any)} onChange={onChange as any} />;
  if (type === "file" || type === "range" || type === "radio")
    return <input {...p} type={type} onChange={onChange} onBlur={onBlur} />;
  return (
    <Input {...(p as any)} type={type} onChange={onChange} onBlur={onBlur} />
  );
}
export function UTextArea(
  p: React.TextareaHTMLAttributes<HTMLTextAreaElement>,
) {
  return (
    <Input.TextArea {...(p as any)} autoSize={{ minRows: 2, maxRows: 8 }} />
  );
}
export function UDetails({
  children,
  open: _open,
  ...props
}: React.DetailsHTMLAttributes<HTMLDetailsElement>) {
  const [open, setOpen] = useState(false);
  const nodes = React.Children.toArray(children);
  const summary = nodes.find(
    (n) => React.isValidElement(n) && n.type === "summary",
  ) as React.ReactElement<any> | undefined;
  return (
    <>
      <Button type="text" onClick={() => setOpen(true)} className="detail-link">
        {summary?.props.children || "更多设置"}…
      </Button>
      <Modal
        title={summary?.props.children}
        open={open}
        onCancel={() => setOpen(false)}
        footer={<Button onClick={() => setOpen(false)}>完成</Button>}
        width={760}
      >
        <div className={props.className}>
          {nodes.filter((n) => n !== summary)}
        </div>
      </Modal>
    </>
  );
}
export function useSavedState<T>(
  key: string,
  initial: T,
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const [v, sv] = useState<T>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(key) || "null") ?? initial;
    } catch {
      return initial;
    }
  });
  return [
    v,
    (x) =>
      sv((prev) => {
        const next = typeof x === "function" ? (x as any)(prev) : x;
        sessionStorage.setItem(key, JSON.stringify(next));
        return next;
      }),
  ];
}

export function uiDefault(key: string, fallback: any) {
  try {
    return (
      JSON.parse(localStorage.getItem("otto.ui.settings") || "{}")[key] ??
      fallback
    );
  } catch {
    return fallback;
  }
}
