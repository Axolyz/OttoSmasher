// 与 Core 命令返回值对应的类型（阶段 1 手写；之后由 Core 的命令定义生成）。

export interface SettingEntry {
  value: unknown;
  default: unknown;
  version: number;
  group: string;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "interrupted";

export interface JobSummary {
  id: string;
  kind: string;
  channel: "model" | "light";
  status: JobStatus;
  affects: Record<string, string[]>;
  progress: { stage: string; done: number; total: number; percent: number | null; code: string; args: Record<string, unknown> } | null;
  error: { code: string; args: Record<string, unknown> } | null;
  result: unknown;
  device: { accelerate: boolean; directml_device: number };
  retry_of: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface EditLabel {
  code: string;
  args: Record<string, unknown>;
}

export interface ModelFileStatus {
  path: string;
  role: "weight" | "support";
  state: "ok" | "missing" | "size-mismatch" | "sha-mismatch" | "unverified";
}

export interface ModelsStatus {
  models_dir: string;
  support_dir: string;
  files: Array<{ model: string; state: "ready" | "missing" | "mismatch" | "unverified"; files: ModelFileStatus[]; url: string }>;
  runtime: { onnxruntime: { loadable: boolean; version?: string; providers?: string[]; error?: string } };
  probes: Array<{ model: string; status: string }>;
}

export interface Hello {
  version: string;
  workspace: string;
  schema_version: number;
  interrupted_on_start: number;
  dev: boolean;
}
