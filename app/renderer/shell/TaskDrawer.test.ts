import { describe, expect, it } from "vitest";
import type { JobSummary } from "../api/types";
import { jobDeviceText } from "./TaskDrawer";

const base = { kind: "separate", device: { accelerate: false, directml_device: 0 } } as JobSummary;

describe("job device display", () => {
  it("does not present the ONNX CPU switch as the separation device", () => {
    const label = jobDeviceText({ ...base, separationDevice: { requested: "auto", deviceId: 0 } });
    expect(label).toContain("自动");
    expect(label).toContain("PyMSS Studio");
    expect(label).not.toContain("CPU");
    expect(jobDeviceText({ ...base, separationDevice: { requested: "mps", deviceId: 0 } })).toContain("MPS");
    expect(jobDeviceText({ ...base, separationDevice: { requested: "cuda", deviceId: 2 } })).toContain("CUDA（设备 2）");
  });
  it("keeps missing separation settings unknown, and ONNX tasks unchanged", () => {
    expect(jobDeviceText(base)).toContain("未知");
    expect(jobDeviceText({ ...base, kind: "speech.analyze" })).toBe("设备：CPU");
    expect(jobDeviceText({ ...base, separationDevice: { requested: "cpu", deviceId: 0 } })).toBe("分离设备设置：CPU");
  });
});
