"""``otto``：命令行调用正在运行的应用（阶段 A）。机器优先：stdout 只写 JSON，进度与提示写 stderr。

退出码：0 成功；1 业务错误（Core 的错误码，或任务 / 检索失败）；2 用法错误、连不上、参数不合命令定义；3 所有者拒绝或没人确认。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import instances, skills
from .. import resources
from ..core.errors import ERRORS, CoreError

GUIDE = Path(__file__).resolve().parent / "guide"
LANGS = ("zh-CN", "en")
TERMINAL_JOB = ("succeeded", "failed", "cancelled", "interrupted")
USAGE_ERRORS = ("bad-request", "unknown-method", "app-not-running", "agent-link-failed", "agent-command-forbidden")
DECLINED = ("agent-confirm-declined", "agent-confirm-timeout")
# 原始能力的任务命令 → 读结果的命令（--wait 时自动读出）
PRIMITIVE_RESULTS = {"speech.align": "speech.alignResults", "text.analyze": "text.analyzeResults", "f0.track": "f0.trackResults"}
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
    # 正在运行的同一种应用用的工作区；都没开就是默认的（与 app/main/paths.ts 相同：源码运行 = dev-workspace，发布版 = ~/Documents/OttoSmasher Workspace）
    return instances.workspace_of_running() or resources.default_workspace()


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
    path = resources.root() / "app" / "renderer" / "i18n" / "locales" / f"{lang}.json"
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
    if method in PRIMITIVE_RESULTS and (ok or (final.get("error") or {}).get("code") == "job-all-items-failed"):
        # 原始能力的任务：结果在任务目录里，跟着读出来（逐条；单条失败写在条目里，全部失败时也读出原因）
        rows: list[Any] = []
        while True:
            page = client.call(PRIMITIVE_RESULTS[method], {"jobId": job["id"], "offset": len(rows), "limit": 200})
            rows += page
            if len(page) < 200:
                break
        return {"job": final, "results": rows}, ok
    if isinstance(result, dict) and result is not job:
        return {**result, "job": final}, ok
    return final, ok


# ---------------------------------------------------------------- 子命令


def cmd_status(args: argparse.Namespace) -> None:
    from ..core import agent_link
    from ..store.workspace import Workspace

    ws = workspace_of(args)
    info = agent_link.read_endpoint(Workspace(ws).data)
    where = {"app": str(instances.app_location()), "build": instances.build(), "runningApps": instances.running()}
    if info is None:
        out({"running": False, "workspace": str(ws), **where, "hint": "run `otto open` to start the app", "environment": environment(args, ws, None)}, args.pretty)
        raise Exit(2)
    with connect(args) as c:
        out({"running": True, "workspace": str(ws), **where, "core": c.hello, "session": c.session,
             "catalogVersion": catalog()["catalogVersion"], "sessions": c.call("agent.sessions"), "environment": environment(args, ws, c)}, args.pretty)


def cmd_open(args: argparse.Namespace) -> None:
    """打开应用并等它能连上；已经开着就什么也不做（所有者 2026-10-25 同意，2026-11-04 做）。打开的是带界面的正常应用。"""
    from ..core import agent_link
    from ..store.workspace import Workspace

    ws = workspace_of(args)
    data = Workspace(ws).data
    base = {"workspace": str(ws), "app": str(instances.app_location())}
    if agent_link.read_endpoint(data) is not None:
        out({"opened": False, "running": True, **base}, args.pretty)
        return
    explicit = bool(args.workspace or os.environ.get("OTTO_WORKSPACE"))
    try:
        instances.launch(ws if explicit else None)
    except (OSError, subprocess.CalledProcessError) as e:
        out({**error_wire("agent-link-failed", {"reason": f"could not start the app: {e}"}), **base}, args.pretty)
        raise Exit(2) from e
    end = time.monotonic() + args.timeout
    while agent_link.read_endpoint(data) is None:
        if time.monotonic() >= end:
            out({**error_wire("agent-link-failed", {"reason": f"the app did not become ready in {args.timeout:g} s"}), **base}, args.pretty)
            raise Exit(2)
        time.sleep(0.25)
    out({"opened": True, "running": True, **base}, args.pretty)


def environment(args: argparse.Namespace, ws: Path, c: Any) -> dict[str, Any]:
    """开工前的环境：otto 的位置、模型、PyMSS Studio、用户有没有 playbook、有哪些 skill。缺什么就在 hints 里说怎么补。"""
    env: dict[str, Any] = {"otto": otto_command()}
    hints: list[str] = []
    if c is not None:
        try:
            env["models"] = {m["model"]: m["state"] for m in c.call("models.status")["files"]}
            if any(v != "ready" for v in env["models"].values()):
                hints.append("some models are not ready: ask the user to open Settings > Environment & models")
        except CoreError:
            pass
        try:
            st = c.call("studio.status")
            env["pymssStudio"] = bool(st.get("ok"))
            if not st.get("ok"):
                hints.append("PyMSS Studio is not available: separation will not run; ask the user to install it")
        except CoreError:
            pass
    env["playbook"] = str(playbook_path(ws)) if playbook_path(ws).is_file() else None
    try:
        skills.sync(ws, skills_lang(args))
        rows = skills.listing(ws)
        updates = [u for r in rows for u in r["update"]]
        env["skills"] = {"path": str(skills.skills_dir(ws)), "names": [r["name"] for r in rows], "updates": updates}
        if updates:
            hints.append("newer built-in skill files are waiting next to the user's edited copies (*.new): offer to merge them")
    except OSError:
        pass
    env["hints"] = hints
    return env


def cmd_commands(args: argparse.Namespace) -> None:
    cat = catalog()
    if args.events:
        out([{"name": e["name"], "summary": e["summary"]} for e in cat["events"]], args.pretty)
        return
    rows = []
    for c in cat["commands"]:
        if args.effect and c["effect"] != args.effect:
            continue
        if args.layer and c.get("layer", "library") != args.layer:
            continue
        if args.grep and args.grep.lower() not in (c["name"] + " " + c["summary"]).lower():
            continue
        if c["effect"] in ("ui", "app", "dev") and not args.all:
            continue  # 命令行调用不了
        row = {"name": c["name"], "effect": c["effect"], "layer": c.get("layer", "library"), "summary": c["summary"]}
        if "danger" in c:
            row["danger"] = c["danger"]
        rows.append(row)
    if not rows and args.grep and any(ch in args.grep for ch in "|*^$()[]"):
        note({"note": "--grep matches one plain substring, not a regular expression"})
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
                note({"note": "waiting for the user to approve this in the app"
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


def guide_topics() -> list[Path]:
    """说明书：只有英文一份（给 agent 看；所有者 2026-11-04）。"""
    return sorted((GUIDE / "reference").glob("*.md"))


def cmd_run(args: argparse.Namespace) -> None:
    """用应用自带的 Python 跑 agent 自己的脚本：脚本里 ``LinkClient.from_env()`` 连同一个工作区、记同一个会话（整个脚本一个会话）。"""
    import subprocess

    env = {**os.environ, "OTTO_WORKSPACE": str(workspace_of(args)), "OTTO_AGENT_SESSION": session_of(args), "OTTO_AGENT_KIND": args.as_}
    raise Exit(subprocess.run([sys.executable, args.script, *args.args], env=env).returncode)


def playbook_path(ws: Path) -> Path:
    """用户自己的约定（主题 ``playbook``）：放在工作区里，应用更新不覆盖、换 agent 工具也照样用。"""
    return ws / "Agent" / "playbook.md"


def otto_command() -> str:
    """agent 该怎么叫 otto：开发版 = 仓库里的 tools/otto；发布版的启动器见 ROADMAP L46。"""
    dev = resources.root() / ("bin" if resources.packaged() else "tools") / ("otto.cmd" if sys.platform == "win32" else "otto")
    return str(dev) if dev.is_file() else "otto"


def skills_lang(args: argparse.Namespace) -> str:
    """第一次把 skill 复制进工作区时用什么语言：--lang / OTTO_LOCALE，其次正在运行的应用的界面语言，其次系统语言。之后语言不再变（skills.sync）。"""
    lang = getattr(args, "lang", None) or os.environ.get("OTTO_LOCALE")
    if lang in LANGS:
        return lang
    for info in instances.running():
        if info.get("build") == instances.build() and info.get("locale") in LANGS:
            return info["locale"]
    import locale

    system = locale.getlocale()[0] or ""
    return "en" if system and not system.lower().startswith("zh") else "zh-CN"


def sync_skills(args: argparse.Namespace) -> dict[str, Any] | None:
    """把内置 skill 同步到工作区；写不进去（只读、磁盘满）时在 stderr 说一声，不挡别的事。"""
    try:
        return skills.sync(workspace_of(args), skills_lang(args))
    except OSError as e:
        note({"note": f"could not update the skills folder: {e}"})
        return None


def print_skills(args: argparse.Namespace) -> None:
    ws = workspace_of(args)
    sync_skills(args)
    rows = skills.listing(ws)
    sys.stdout.write(f"Skills: procedures for a few specific tasks. They live in {skills.skills_dir(ws)} and the user may edit them. Read one only when your task matches its description; most tasks need none.\n")
    for r in rows:
        extra = " (a newer built-in version is next to it as .new; offer to merge it)" if r["update"] else ""
        sys.stdout.write(f"- {r['name']}: {r['description']}{extra}\n  {r['path']}\n")
    if not rows:
        sys.stdout.write("(none)\n")


def cmd_guide(args: argparse.Namespace) -> None:
    lang = lang_of(args)
    topics = guide_topics()
    names = [p.stem.split("-", 1)[-1] for p in topics]
    if args.topic in ("skills", "notes"):  # notes = 旧版的第二层，已经装好的入口 skill 还可能这么叫
        print_skills(args)
        return
    if args.topic == "playbook":
        f = playbook_path(workspace_of(args))
        if f.is_file():
            sys.stdout.write(f"<!-- {f} -->\n" + f.read_text(encoding="utf-8"))
        else:
            sys.stdout.write(f"<!-- {f} does not exist yet: the user has no playbook. `otto setup playbook` creates it from this template. -->\n"
                             + (GUIDE / "playbook" / f"{lang}.md").read_text(encoding="utf-8"))
        return
    if args.topic:
        match = [p for p in topics if p.stem == args.topic or p.stem.split("-", 1)[-1] == args.topic]
        if match:
            sys.stdout.write(match[0].read_text(encoding="utf-8"))
            return
        ws = workspace_of(args)
        sync_skills(args)
        f = skills.skills_dir(ws) / args.topic / "SKILL.md"
        if f.is_file():
            sys.stdout.write(f"<!-- {f} -->\n" + f.read_text(encoding="utf-8"))
            return
        out({**error_wire("bad-request", {"method": "guide", "reason": f"no topic {args.topic}"}),
             "topics": names + ["skills", "playbook"], "skills": [r["name"] for r in skills.listing(ws)]}, args.pretty)
        raise Exit(2)
    if args.all:
        sys.stdout.write("\n\n".join(p.read_text(encoding="utf-8").strip() for p in topics) + "\n")
        return
    sys.stdout.write(topics[0].read_text(encoding="utf-8").rstrip() + "\n\n")
    sys.stdout.write("Topics: " + ", ".join(names[1:]) + ", skills, playbook\n\n")
    print_skills(args)


AUDIO_PKG = "audio-mcp[speech]==0.4.0"


def cmd_setup(args: argparse.Namespace) -> None:
    """安装帮手：``playbook`` 在工作区生成用户的约定模板；``skills`` 同步并检查工作区里的 skill；``audio`` 只打印接音频工具的命令 / 配置（写用户配置的事由用户决定）。"""
    lang = lang_of(args)
    if args.what == "skills":
        report = sync_skills(args) or {}
        from ..core.settings import SPECS

        cat = catalog()
        known = {c["name"] for c in cat["commands"]} | {e["name"] for e in cat["events"]} | set(SPECS)
        ws = workspace_of(args)
        out({**report, "skills": skills.listing(ws), "unknownCommands": skills.unknown_commands(ws, known)}, args.pretty)
        return
    if args.what == "playbook":
        f = playbook_path(workspace_of(args))
        if f.is_file():
            out({"playbook": str(f), "created": False}, args.pretty)
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text((GUIDE / "playbook" / f"{lang}.md").read_text(encoding="utf-8"), encoding="utf-8")
        out({"playbook": str(f), "created": True}, args.pretty)
        return
    # audio：只打印。audio-mcp 的转写只有经 MCP 才能用；它的命令行能做 analyze / view / melody 等
    env = {"AUDIO_MCP_WHISPER_MODEL": "turbo"}
    plans = {
        "claude-code": {"run": f'claude mcp add audio -s user -e AUDIO_MCP_WHISPER_MODEL=turbo -- uvx --from "{AUDIO_PKG}" audio-mcp'},
        "codex": {"file": str(Path.home() / ".codex" / "config.toml"),
                  "append": f'[mcp_servers.audio]\ncommand = "uvx"\nargs = ["--from", "{AUDIO_PKG}", "audio-mcp"]\nenv = {{ AUDIO_MCP_WHISPER_MODEL = "turbo" }}\n'},
        "other": {"mcpStdio": {"command": "uvx", "args": ["--from", AUDIO_PKG, "audio-mcp"], "env": env},
                  "withoutMcp": f'uvx --from "{AUDIO_PKG}" audio-mcp analyze|view|melody|timeline <file>  (no transcription without MCP)'},
    }
    which = args.for_ or "other"
    out({"tool": "audio-mcp", "needs": "uv (uvx) on PATH; the first use downloads the package and the Whisper model (about 1.6 GB, CPU only)",
         "for": which, **plans[which]}, args.pretty)


def cmd_session(args: argparse.Namespace) -> None:
    """回来接着干：这个会话提交的任务（状态、结果摘要）和改过的资料。"""
    s = args.session or os.environ.get("OTTO_AGENT_SESSION")
    if not s:
        out(error_wire("bad-request", {"method": "session", "reason": "set OTTO_AGENT_SESSION or --session"}), args.pretty)
        raise Exit(2)
    with connect(args) as c:
        jobs = [j for j in c.call("jobs.list", {"limit": 500}) if (j.get("actor") or {}).get("session") == s]
        edits = c.call("edits.history", {"session": s, "limit": 200})
    keep = ("id", "kind", "status", "progress", "error", "items", "result", "created_at", "finished_at")  # result：视频路径、检索结果等
    out({"session": s,
         "jobs": [{k: j[k] for k in keep if k in j} for j in jobs],
         "running": sum(1 for j in jobs if j["status"] in ("queued", "running")),
         "edits": {"count": len(edits), "latest": edits[:10]}}, args.pretty)


# ---------------------------------------------------------------- 入口


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", help="workspace folder (default: OTTO_WORKSPACE, else the one the running app uses, else the default)")
    common.add_argument("--session", help="session id recorded on every change (default: OTTO_AGENT_SESSION)")
    common.add_argument("--as", dest="as_", choices=("agent", "script"), default="agent", help="who is calling (recorded as the actor)")
    common.add_argument("--pretty", action="store_true", help="indent JSON output")
    ap = argparse.ArgumentParser(prog="otto", description="Call the running OttoSmasher app. Start with: otto guide", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", parents=[common], help="is the app running; Core version; attached sessions").set_defaults(fn=cmd_status)
    p = sub.add_parser("open", parents=[common], help="start the app if it is not running and wait until it is ready")
    p.add_argument("--timeout", type=float, default=120.0, help="seconds to wait (default 120)")
    p.set_defaults(fn=cmd_open)
    p = sub.add_parser("commands", parents=[common], help="list commands (or events) from the catalog")
    p.add_argument("--effect", choices=("read", "write", "job"))
    p.add_argument("--layer", choices=("library", "primitive"), help="library = business commands on the library; primitive = compute only, no library changes")
    p.add_argument("--grep", help="case-insensitive plain substring of the name and summary (not a regular expression)")
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
    p = sub.add_parser("guide", parents=[common], help="the reference for agents (concepts, commands, rules); `otto guide skills` lists the editable procedures, `otto guide <skill>` prints one, `otto guide playbook` prints the user's conventions")
    p.add_argument("topic", nargs="?")
    p.add_argument("--lang", choices=LANGS, help="language of the skills copied into a new workspace and of the playbook template; the reference is English only")
    p.add_argument("--all", action="store_true", help="print every reference topic")
    p.set_defaults(fn=cmd_guide)
    p = sub.add_parser("setup", parents=[common], help="helpers: the user's playbook template, check the skills folder, how to connect an audio tool")
    p.add_argument("what", choices=("audio", "playbook", "skills"))
    p.add_argument("--for", dest="for_", choices=("claude-code", "codex", "other"))
    p.add_argument("--lang", choices=LANGS)
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("session", parents=[common], help="this session's jobs and changes (to pick up after a long job)")
    p.set_defaults(fn=cmd_session)
    return ap


def main(argv: list[str] | None = None) -> int:
    # 输出是给 agent 读的 JSON，一律 UTF-8：Windows 被管道接走时默认用系统编码，遇到写不了的文字（工作区路径、日文）直接崩
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
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
