"""用户辞典（规格 08 §8.2.4、16 R10.2）。"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.lang.ja import dictionary as dic


def test_line_rules():
    entries, errors = dic.parse("京子\tキョーコ\n")
    assert [(e.surface, e.reading) for e in entries] == [("京子", "キョーコ")] and errors == []
    # 重复表记报“第 2 行”；平假名读音报错；空行忽略；缺 Tab
    _, errors = dic.parse("京子\tキョーコ\n京子\tキョウコ\n\n歳納\tとしのう\n無タブ\n")
    assert errors == [
        {"line": 2, "reason": "dict-duplicate", "first": 1},
        {"line": 4, "reason": "dict-reading-not-katakana"},
        {"line": 5, "reason": "dict-format"},
    ]
    _, errors = dic.parse("\tキ\n" + "あ" * 201 + "\tア\nあ\t" + "ア" * 201 + "\nい\tア・イ\n")
    assert [e["reason"] for e in errors] == ["dict-surface-empty", "dict-surface-too-long", "dict-reading-too-long", "dict-reading-not-katakana"]
    with pytest.raises(CoreError) as e:
        dic.check("京子\tキョーコ\n京子\tキョウコ")
    assert e.value.code == "dictionary-invalid" and e.value.args_["line"] == 2


def test_content_name_and_csv():
    assert dic.content_name("") is None and dic.content_name("\n\n") is None
    a = dic.content_name("歳納\tトシノウ\n")
    assert a and a.startswith("user-") and a == dic.content_name("歳納\tトシノウ")
    assert dic.version_of(a) == a.removesuffix(".dic") and dic.version_of(None) == "none"
    csv = dic.to_csv(dic.check('歳納\tトシノウ\na,b\tエービー\n'))
    assert csv.splitlines()[0] == '歳納,"","",1,名詞,一般,*,*,*,*,歳納,トシノウ,トシノウ,0/4,*'
    assert csv.splitlines()[1].startswith('"a,b","","",1,')


def test_compile_and_reading_is_used(tmp_path: Path):
    code = (
        "import sys, json\n"
        "from pathlib import Path\n"
        "from ottosmasher.lang.ja import dictionary as dic, openjtalk\n"
        "out = Path(sys.argv[1]) / 'u.dic'\n"
        "name = dic.compile_to('歳納\\tトシノウ\\n', out)\n"
        "pj = openjtalk.load()\n"
        "m = pj.g2p_mapping('歳納京子', use_tsqyomi=False, normalize_mode='None', jtalk=dic.jtalk_for(out))\n"
        "print(json.dumps({'name': name, 'first': m[0]['pron']}, ensure_ascii=False))\n"
    )
    r = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=120, check=True)
    # 编译进度不能混进 stdout（任务进程的 stdout 是事件通道）
    assert r.stdout.strip().splitlines() == [r.stdout.strip()]
    assert '"first": "トシノウ"' in r.stdout


# ---------------------------------------------------------------- 经 Core 进程：保存 = 编译任务 + 原子启用（可撤销、版本冲突拒绝）

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))


def _wait_job(c, jid, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = next(x for x in c.call("jobs.list")["r"] if x["id"] == jid)
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.2)
    raise AssertionError("job timeout")


def _dict_setting(c):
    return c.call("settings.list")["r"]["frontend.user_dictionary"]


def test_save_compile_enable_conflict_undo(tmp_path: Path):
    from test_core_process import CoreProc

    root = tmp_path / "ws"
    c = CoreProc(root)
    try:
        s0 = _dict_setting(c)
        assert s0["value"] == {"text": "", "compiled": None} and s0["version"] == 0
        bad = c.call("dictionary.save", text="京子\tきょうこ", version=0)
        assert bad["e"]["code"] == "dictionary-invalid" and bad["e"]["args"]["line"] == 1
        chk = c.call("dictionary.check", text="京子\tキョーコ\n京子\tキョーコ")["r"]
        assert chk == {"entries": 1, "errors": [{"line": 2, "reason": "dict-duplicate", "first": 1}]}

        j = _wait_job(c, c.call("dictionary.save", text="歳納\tトシノウ\n", version=0)["r"]["id"])
        assert j["status"] == "succeeded", j
        s1 = _dict_setting(c)
        name = s1["value"]["compiled"]
        assert s1["value"]["text"] == "歳納\tトシノウ\n" and name.startswith("user-") and s1["version"] == 1
        assert (root / "Data" / "Dictionary" / name).is_file()

        # 编辑期间被改过（拿旧版本保存）→ 拒绝，当前辞典不变
        j = _wait_job(c, c.call("dictionary.save", text="京子\tキョーコ\n", version=0)["r"]["id"])
        assert j["status"] == "failed" and j["error"]["code"] == "edit-conflict"
        assert _dict_setting(c)["value"]["compiled"] == name

        # 不能绕过编译直接写设置
        r = c.call("edits.apply", batch={"ops": [{"entity": "setting", "id": "frontend.user_dictionary", "version": 1, "fields": {"value": {"text": "京子\tキョーコ", "compiled": None}}}]})
        assert r["e"]["code"] == "edit-invalid" and r["e"]["args"]["reason"] == "dict-not-compiled"

        # 撤销 → 回到空辞典；旧产物还在
        u = c.call("edits.undo")["r"]
        assert u["label"]["args"]["of"] == "dictionary-save"
        assert _dict_setting(c)["value"] == {"text": "", "compiled": None}
        assert (root / "Data" / "Dictionary" / name).is_file()
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=15)


MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))


def test_preview_with_draft_dictionary(tmp_path: Path):
    from test_core_process import CoreProc

    if not (MODELS / "tsqyomi" / "model.onnx").exists():
        pytest.skip("tsqyomi weights not in dev-workspace/Models")
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    c = CoreProc(root)
    try:
        j = _wait_job(c, c.call("dictionary.preview", sentence="歳納京子が来た。", text="歳納\tトシノウ")["r"]["id"])
        assert j["status"] == "succeeded", j
        res = j["result"]
        assert res["words"][0] == {"text": "歳納", "reading": "トシノウ", "mapped": True}
        assert res["dictionary"].startswith("user-")
        # 没有草稿 = 当前辞典（空）
        j = _wait_job(c, c.call("dictionary.preview", sentence="京子が何か来た。")["r"]["id"])
        assert j["result"]["dictionary"] == "none" and j["result"]["phonemes"][:5] == ["ky", "o", "o", "k", "o"]
        # 预览顺带交回 tsqyomi 的实测记录（句子里有多读音字「何」才会用到模型）
        assert any(p["model"] == "tsqyomi" and p["status"] == "passed" for p in c.call("models.status")["r"]["probes"])
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=15)
