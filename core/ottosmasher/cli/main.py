"""``otto``：命令行调用正在运行的应用（阶段 A）。机器优先：stdout 只写 JSON，进度与提示写 stderr。

退出码：0 成功；1 业务错误（Core 的错误码，或任务 / 检索失败）；2 用法错误、连不上、参数不合命令定义；3 所有者拒绝或没人确认。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..core.errors import ERRORS, CoreError

ROOT = Path(__file__).resolve().parents[3]
GUIDE = Path(__file__).resolve().parent / "guide"
LANGS = ("zh-CN", "en")
TERMINAL_JOB = ("succeeded", "failed", "cancelled", "interrupted")
USAGE_ERRORS = ("bad-request", "unknown-method", "app-not-running", "agent-link-failed", "agent-command-forbidden")
DECLINED = ("agent-confirm-declined", "agent-confirm-timeout")
# 导出文件名里的固定词（与界面 app/renderer/exportWords.ts 同一组文案键）
WORD_KEYS = {
    "original": "track.original", "vocal": "role.vocal", "sfx": "role.sfx", "flatten": "track.flatten", "reimport": "track.reimport",
    "fragment": "export.fragment", "local": "naming.local", "stretch": "export.stretch", "video": "export.video",
    "originalSpeed": "export.originalSpeed",
}


class Exit(Exception):
    def __init__(self, code: int) -> None:
        self.code = code


# ---------------------------------------------------------------- 输出


def json_default(value: Any) -> str:
    # Command schemas describe binary arrays as base64 strings in JSON.
    # LinkClient retains native bytes for Python scripts.
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def out(value: Any, pretty: bool) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=1 if pretty else None, default=json_default) + "\n")
    sys.stdout.flush()


def note(value: dict[str, Any]) -> None:
    sys.stderr.write(json.dumps(value, ensure_ascii=False, default=json_default) + "\n")
    sys.stderr.flush()


def error_wire(code: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    entry = ERRORS.get(code)
    return {"error": {"code": code, "args": args or {}, "message": entry[1] if entry else None}}


def fail(err: CoreError | dict[str, Any], pretty: bool, extra: dict[str, Any] | None = None) -> None:
    code, args = (err.code, err.args_) if isinstance(err, CoreError) else (err.get("code", "internal-error"), err.get("args") or {})
    out({**error_wire(code, args), **(extra or {})}, pretty)
    raise Exit(3 if code in DECLINED else 2 if code in USAGE_ERRORS else 1)


# ---------------------------------------------------------------- 目录（命令、事件、错误码）


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    from ..api import catalog as cat

    return cat.build(cat.default_commands())


def expand(schema: Any, defs: dict[str, Any], depth: int = 0) -> Any:
    """把 $ref 展开（有深度上限，递归类型不会无限展开）。"""
    if isinstance(schema, dict):
        if "$ref" in schema and depth < 6:
            return expand(defs[schema["$ref"].rsplit("/", 1)[-1]], defs, depth + 1)
        return {k: expand(v, defs, depth) for k, v in schema.items()}
    if isinstance(schema, list):
        return [expand(x, defs, depth) for x in schema]
    return schema


# ---------------------------------------------------------------- 连接


def workspace_of(args: argparse.Namespace) -> Path:
    if args.workspace:
        return Path(args.workspace).expanduser()
    env = os.environ.get("OTTO_WORKSPACE")
    if env:
        return Path(env).expanduser()
    return ROOT / "dev-workspace"  # 开发期默认（与 app/main/paths.ts 相同）；发布版的默认位置见 ROADMAP L46


def session_of(args: argparse.Namespace) -> str:
    s = args.session or os.environ.get("OTTO_AGENT_SESSION")
    if s:
        return s
    s = "cli-" + secrets.token_hex(4)
    note({"note": "no session given (--session or OTTO_AGENT_SESSION); this call is recorded under a one-off session", "session": s})
    return s


def connect(args: argparse.Namespace):  # noqa: ANN201
    from .client import LinkClient

    try:
        return LinkClient(workspace_of(args), kind=args.as_, session=session_of(args))
    except CoreError as e:
        fail(e, args.pretty)


@lru_cache(maxsize=4)
def export_words(lang: str) -> dict[str, str] | None:
    path = ROOT / "app" / "renderer" / "i18n" / "locales" / f"{lang}.json"
    try:
        texts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: texts[v] for k, v in WORD_KEYS.items() if v in texts}


def lang_of(args: argparse.Namespace) -> str:
    lang = getattr(args, "lang", None) or os.environ.get("OTTO_LOCALE") or "zh-CN"
    return lang if lang in LANGS else "en"


def read_params(raw: str | None) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if raw == "-":
        raw = sys.stdin.read()
    elif raw.startswith("@"):
        raw = Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("params must be a JSON object")
    return value


# ---------------------------------------------------------------- 等待任务 / 检索 / 视频导出


def _job_of(result: Any) -> dict[str, Any] | None:
    if isinstance(result, dict):
        if {"id", "kind", "status", "channel"} <= set(result):
            return result
        j = result.get("job")
        if isinstance(j, dict) and "id" in j and "status" in j:
            return j
    return None


def wait_job(client, job: dict[str, Any], timeout: float | None, pretty: bool) -> dict[str, Any]:  # noqa: ANN001
    jid = job["id"]
    end = None if timeout is None else time.monotonic() + timeout
    last = job
    while last["status"] not in TERMINAL_JOB:
        left = None if end is None else end - time.monotonic()
        if left is not None and left <= 0:
            out({**error_wire("agent-link-failed", {"reason": f"timed out waiting for job {jid}"}), "job": last}, pretty)
            raise Exit(1)
        ev = client.next_event(left)
        if ev is None:
            continue
        if ev["e"] == "job.updated" and ev["d"]["id"] == jid:
            last = ev["d"]
            note({"event": "job.updated", "id": jid, "status": last["status"], "progress": last.get("progress")})
        elif ev["e"] == "exports.videoDone":
            client.video_done[ev["d"].get("jobId")] = ev["d"]  # 别的事件丢掉（等待期间只关心这个任务）
    return last


def ended_error(result: Any) -> dict[str, Any]:
    """任务 / 检索没有成功：有具体错误就用它，否则按结束状态报。"""
    r = result if isinstance(result, dict) else {}
    job = r.get("job") if isinstance(r.get("job"), dict) else r
    err = job.get("error") or r.get("error")
    if err:
        return error_wire(err.get("code", "internal-error"), err.get("args"))
    if "searchId" in r:
        return error_wire("search-not-done", {"status": r.get("status")})
    return error_wire("job-not-succeeded", {"status": job.get("status")})


def wait_search(client, search_id: str, timeout: float | None, pretty: bool) -> dict[str, Any]:  # noqa: ANN001
    end = None if timeout is None else time.monotonic() + timeout
    st = client.call("search.status", {"searchId": search_id})
    while st["status"] == "running":
        left = None if end is None else end - time.monotonic()
        if left is not None and left <= 0:
            out({**error_wire("agent-link-failed", {"reason": f"timed out waiting for search {search_id}"}), "search": st}, pretty)
            raise Exit(1)
        ev = client.next_event(left)
        if ev is not None and ev["e"] == "search.finished" and ev["d"]["searchId"] == search_id:
            st = ev["d"]
    return st


def follow(client, method: str, result: Any, timeout: float | None, pretty: bool) -> tuple[Any, bool]:  # noqa: ANN001
    """--wait：结果是任务 / 检索 / 视频导出时跟到结束。返回 (输出, 是否成功)。"""
    if isinstance(result, dict) and isinstance(result.get("searchId"), str) and set(result) <= {"searchId"}:
        st = wait_search(client, result["searchId"], timeout, pretty)
        return st, st["status"] == "done"
    job = _job_of(result)
    ref = None
    if job is None and isinstance(result, dict):
        # 只带任务 ID 的（roots.add 的 job、sources.rescan）：取一次当前摘要
        if isinstance(result.get("job"), dict) and "id" in result["job"]:
            ref = result["job"]["id"]
        elif method == "sources.rescan" and set(result) == {"id"}:
            ref = result["id"]
    if ref is not None:
        job = next((j for j in client.call("jobs.list", {"limit": 500}) if j["id"] == ref), None)
    if job is None:
        return result, True
    final = wait_job(client, job, timeout, pretty)
    ok = final["status"] == "succeeded"
    if ok and method in ("exports.video", "hits.video", "exports.videoRange"):
        # 视频片段：成品路径在任务结果里（登记后才写入任务状态）；旧任务没有时再等完成事件，最多 10 秒
        res = final.get("result") or {}
        done = {"jobId": job["id"], **res} if res.get("path") else client.video_done.get(job["id"])
        end = time.monotonic() + 10
        while done is None and time.monotonic() < end:
            ev = client.next_event(max(0.0, end - time.monotonic()))
            if ev is not None and ev["e"] == "exports.videoDone" and ev["d"].get("jobId") == job["id"]:
                done = ev["d"]
        return {"job": final, "video": done}, done is not None
    if isinstance(result, dict) and result is not job:
        return {**result, "job": final}, ok
    return final, ok


# ---------------------------------------------------------------- 子命令


def cmd_status(args: argparse.Namespace) -> None:
    from ..core import agent_link
    from ..store.workspace import Workspace

    ws = workspace_of(args)
    info = agent_link.read_endpoint(Workspace(ws).data)
    if info is None:
        out({"running": False, "workspace": str(ws)}, args.pretty)
        raise Exit(2)
    with connect(args) as c:
        out({"running": True, "workspace": str(ws), "core": c.hello, "session": c.session,
             "catalogVersion": catalog()["catalogVersion"], "sessions": c.call("agent.sessions")}, args.pretty)


def cmd_commands(args: argparse.Namespace) -> None:
    cat = catalog()
    if args.events:
        out([{"name": e["name"], "summary": e["summary"]} for e in cat["events"]], args.pretty)
        return
    rows = []
    for c in cat["commands"]:
        if args.effect and c["effect"] != args.effect:
            continue
        if args.grep and args.grep.lower() not in (c["name"] + " " + c["summary"]).lower():
            continue
        if c["effect"] in ("ui", "app", "dev") and not args.all:
            continue  # 命令行调用不了
        row = {"name": c["name"], "effect": c["effect"], "summary": c["summary"]}
        if "danger" in c:
            row["danger"] = c["danger"]
        rows.append(row)
    out(rows, args.pretty)


def cmd_describe(args: argparse.Namespace) -> None:
    cat = catalog()
    defs = cat["$defs"]
    for c in cat["commands"]:
        if c["name"] == args.name:
            out({**c, "params": expand(c["params"], defs), "result": expand(c["result"], defs),
                 "callable": c["effect"] not in ("ui", "app", "dev")}, args.pretty)
            return
    for e in cat["events"]:
        if e["name"] == args.name:
            out({"event": e["name"], "summary": e["summary"], "payload": expand(e["payload"], defs)}, args.pretty)
            return
    fail(CoreError("unknown-method", method=args.name), args.pretty)


def cmd_errors(args: argparse.Namespace) -> None:
    rows = catalog()["errors"]
    if args.code:
        rows = [e for e in rows if e["code"] == args.code]
    out(rows, args.pretty)


def cmd_call(args: argparse.Namespace) -> None:
    try:
        params = read_params(args.params)
    except (ValueError, OSError) as e:
        fail(CoreError("bad-request", method=args.method, reason=str(e)), args.pretty)
    cmd = next((c for c in catalog()["commands"] if c["name"] == args.method), None)
    if cmd is not None and "words" not in params:
        props = catalog()["$defs"].get(cmd["params"].get("$ref", "").rsplit("/", 1)[-1], {}).get("properties", {})
        if "words" in props:
            words = export_words(lang_of(args))
            if words:
                params["words"] = words
    with connect(args) as c:
        def waiting(ev: dict[str, Any]) -> None:
            d = ev.get("d") or {}
            if ev.get("e") == "agent.confirm" and d.get("actor", {}).get("session") == c.session and d.get("method") == args.method:
                limit = d.get("seconds") or 0
                note({"note": "waiting for the owner to approve this in the app"
                      + (f" (declined after {limit} s)" if limit else " (no time limit; stopping this process withdraws the request)"),
                      "confirmId": d.get("id")})

        res = c.request(args.method, params, on_event=waiting)
        if not res.get("ok"):
            fail(res.get("e") or {}, args.pretty)
        result = res.get("r")
        if args.wait:
            result, ok = follow(c, args.method, result, args.timeout, args.pretty)
            if not ok:
                out({**ended_error(result), "result": result}, args.pretty)
                raise Exit(1)
        out(result, args.pretty)


def cmd_wait(args: argparse.Namespace) -> None:
    with connect(args) as c:
        if args.what == "search":
            st = wait_search(c, args.id, args.timeout, args.pretty)
            if st["status"] != "done":
                out({**ended_error(st), "result": st}, args.pretty)
                raise Exit(1)
            out(st, args.pretty)
            return
        job = next((j for j in c.call("jobs.list", {"limit": 500}) if j["id"] == args.id), None)
        if job is None:
            fail(CoreError("job-not-found", id=args.id), args.pretty)
        final = wait_job(c, job, args.timeout, args.pretty)
        if final["status"] != "succeeded":
            out({**ended_error(final), "result": final}, args.pretty)
            raise Exit(1)
        out(final, args.pretty)


def cmd_events(args: argparse.Namespace) -> None:
    names = args.name or []
    n = 0
    with connect(args) as c:
        end = None if args.timeout is None else time.monotonic() + args.timeout
        while args.count is None or n < args.count:
            left = None if end is None else end - time.monotonic()
            if left is not None and left <= 0:
                return
            ev = c.next_event(left)
            if ev is None:
                continue
            if names and not any(ev["e"] == x or ev["e"].startswith(x.rstrip("*")) for x in names):
                continue
            sys.stdout.write(json.dumps({"event": ev["e"], "data": ev["d"]}, ensure_ascii=False, default=json_default) + "\n")
            sys.stdout.flush()
            n += 1


def guide_topics(lang: str) -> list[Path]:
    return sorted((GUIDE / lang).glob("*.md"))


def cmd_run(args: argparse.Namespace) -> None:
    """用应用自带的 Python 跑 agent 自己的脚本：脚本里 ``LinkClient.from_env()`` 连同一个工作区、记同一个会话（整个脚本一个会话）。"""
    import subprocess

    env = {**os.environ, "OTTO_WORKSPACE": str(workspace_of(args)), "OTTO_AGENT_SESSION": session_of(args), "OTTO_AGENT_KIND": args.as_}
    raise Exit(subprocess.run([sys.executable, args.script, *args.args], env=env).returncode)


def cmd_guide(args: argparse.Namespace) -> None:
    lang = lang_of(args)
    topics = guide_topics(lang)
    if args.skill:
        body = "\n\n".join(p.read_text(encoding="utf-8").strip() for p in topics)
        desc = ("Operate the OttoSmasher app (otomad sample library: sources, subtitles, separation, speech analysis, samples, tags, "
                "rhythm/pitch search, exports) through its `otto` command line while the app is open.")
        sys.stdout.write(f"---\nname: ottosmasher\ndescription: {desc}\n---\n\n{body}\n")
        return
    if args.topic:
        match = [p for p in topics if p.stem == args.topic or p.stem.split("-", 1)[-1] == args.topic]
        if not match:
            out({**error_wire("bad-request", {"method": "guide", "reason": f"no topic {args.topic}"}),
                 "topics": [p.stem.split("-", 1)[-1] for p in topics]}, args.pretty)
            raise Exit(2)
        sys.stdout.write(match[0].read_text(encoding="utf-8"))
        return
    if args.all:
        sys.stdout.write("\n\n".join(p.read_text(encoding="utf-8").strip() for p in topics) + "\n")
        return
    sys.stdout.write(topics[0].read_text(encoding="utf-8").rstrip() + "\n\n")
    sys.stdout.write("Topics: " + ", ".join(p.stem.split("-", 1)[-1] for p in topics[1:]) + "\n")


# ---------------------------------------------------------------- 入口


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", help="workspace folder (default: OTTO_WORKSPACE, else the dev workspace)")
    common.add_argument("--session", help="session id recorded on every change (default: OTTO_AGENT_SESSION)")
    common.add_argument("--as", dest="as_", choices=("agent", "script"), default="agent", help="who is calling (recorded as the actor)")
    common.add_argument("--pretty", action="store_true", help="indent JSON output")
    ap = argparse.ArgumentParser(prog="otto", description="Call the running OttoSmasher app. Start with: otto guide", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[common], help="is the app running; Core version; attached sessions").set_defaults(fn=cmd_status)
    p = sub.add_parser("commands", parents=[common], help="list commands (or events) from the catalog")
    p.add_argument("--effect", choices=("read", "write", "job"))
    p.add_argument("--grep")
    p.add_argument("--events", action="store_true", help="list events instead")
    p.add_argument("--all", action="store_true", help="include interface-only commands (not callable here)")
    p.set_defaults(fn=cmd_commands)
    p = sub.add_parser("describe", parents=[common], help="params / result schema of a command, or payload of an event")
    p.add_argument("name")
    p.set_defaults(fn=cmd_describe)
    p = sub.add_parser("errors", parents=[common], help="error code table")
    p.add_argument("code", nargs="?")
    p.set_defaults(fn=cmd_errors)
    p = sub.add_parser("call", parents=[common], help="call a command: otto call samples.list '{\"limit\": 5}'")
    p.add_argument("method")
    p.add_argument("params", nargs="?", help="JSON object, @file.json, or - for stdin")
    p.add_argument("--wait", action="store_true", help="follow a returned job / search / video export to its end")
    p.add_argument("--timeout", type=float, default=None, help="seconds to wait at most")
    p.add_argument("--lang", choices=LANGS, help="language of fixed words in exported file names")
    p.set_defaults(fn=cmd_call)
    p = sub.add_parser("wait", parents=[common], help="wait for a job or search to finish")
    p.add_argument("what", choices=("job", "search"))
    p.add_argument("id")
    p.add_argument("--timeout", type=float, default=None)
    p.set_defaults(fn=cmd_wait)
    p = sub.add_parser("events", parents=[common], help="print events as JSON lines")
    p.add_argument("--name", action="append", help="event name or prefix* (repeatable)")
    p.add_argument("--count", type=int)
    p.add_argument("--timeout", type=float, default=None)
    p.set_defaults(fn=cmd_events)
    p = sub.add_parser("run", parents=[common], help="run your own Python script with the app's Python (LinkClient.from_env() inside)")
    p.add_argument("script")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("guide", parents=[common], help="the agent guide (concepts, recipes, rules)")
    p.add_argument("topic", nargs="?")
    p.add_argument("--lang", choices=LANGS)
    p.add_argument("--all", action="store_true", help="print every topic")
    p.add_argument("--skill", action="store_true", help="print as a Claude Code skill (SKILL.md)")
    p.set_defaults(fn=cmd_guide)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        args.fn(args)
    except Exit as e:
        return e.code
    except CoreError as e:
        try:
            fail(e, getattr(args, "pretty", False))
        except Exit as x:
            return x.code
    except KeyboardInterrupt:
        return 130
    return 0
