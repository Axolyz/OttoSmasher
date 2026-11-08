import { existsSync, mkdtempSync, readFileSync, readlinkSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { OTTO_SHIM_MARK, ensureOttoLink, ottoShim, windowsPathConflict } from "./otto-link";

const dir = () => mkdtempSync(join(tmpdir(), "otto-link-"));

describe.skipIf(process.platform === "win32")("ensureOttoLink：链接", () => {
  it("没有就建（连同目录），已经对的不动", () => {
    const d = dir();
    const link = join(d, "local", "bin", "otto");
    expect(ensureOttoLink("/app/otto", link, false)).toBe("installed");
    expect(readlinkSync(link)).toBe("/app/otto");
    expect(ensureOttoLink("/app/otto", link, false)).toBe("current");
  });
  it("自己的旧位置、失效的链接：换成新的", () => {
    const d = dir();
    const old = join(d, "OttoSmasher-old");
    writeFileSync(old, "");
    const link = join(d, "otto");
    symlinkSync(old, link);
    expect(ensureOttoLink("/new/otto", link, false)).toBe("installed");
    expect(readlinkSync(link)).toBe("/new/otto");
    const dangling = join(d, "otto2");
    symlinkSync("/gone/otto", dangling);
    expect(ensureOttoLink("/new/otto", dangling, false)).toBe("installed");
  });
  it("别的程序不动：普通文件、指向还在的别的工具的链接", () => {
    const d = dir();
    const file = join(d, "otto");
    writeFileSync(file, "other");
    expect(ensureOttoLink("/new/otto", file, false)).toBe("conflict");
    expect(readFileSync(file, "utf8")).toBe("other");
    const tool = join(d, "another-tool");
    writeFileSync(tool, "");
    const link = join(d, "otto2");
    symlinkSync(tool, link);
    expect(ensureOttoLink("/new/otto", link, false)).toBe("conflict");
    expect(readlinkSync(link)).toBe(tool);
  });
});

describe("ensureOttoLink：Windows 转发脚本", () => {
  it("没有就写，换了位置就改，别人的同名文件不动", () => {
    const d = dir();
    const link = join(d, "otto.cmd");
    expect(ensureOttoLink("C:\\应用\\otto.cmd", link, true)).toBe("installed");
    expect(readFileSync(link, "utf8")).toBe(ottoShim("C:\\应用\\otto.cmd"));
    expect(ensureOttoLink("C:\\应用\\otto.cmd", link, true)).toBe("current");
    expect(ensureOttoLink("D:\\挪了\\otto.cmd", link, true)).toBe("installed");
    expect(readFileSync(link, "utf8")).toContain("D:\\挪了\\otto.cmd");
    expect(readFileSync(link, "utf8").startsWith(OTTO_SHIM_MARK)).toBe(true);
    const other = join(d, "other.cmd");
    writeFileSync(other, "@echo other");
    expect(ensureOttoLink("C:\\应用\\otto.cmd", other, true)).toBe("conflict");
    expect(existsSync(other) && readFileSync(other, "utf8")).toBe("@echo other");
  });
});

it("Windows PATH：只看第一个结果，支持大小写和转发脚本，保留别的命令", () => {
  const target = "C:/Apps/OttoSmasher/bin/otto.cmd";
  const link = "C:/Users/a/WindowsApps/otto.cmd";
  expect(windowsPathConflict("c:/APPS/ottosmasher/bin/otto.cmd\r\n", target, link)).toBeNull();
  expect(windowsPathConflict(`${link}\r\n${target}`, target, link)).toBeNull();
  expect(windowsPathConflict(`C:/old/otto.cmd\r\n${target}`, target, link)).toBe("C:/old/otto.cmd");
  expect(windowsPathConflict("", target, null)).toBeNull();
});
