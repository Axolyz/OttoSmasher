"""试听助手只整理已有音频：链接可靠、内容转义、候选数量由任务决定。"""
from __future__ import annotations

import importlib.util
import json
import wave
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import pytest

from ottosmasher.cli.main import GUIDE


SCRIPT = GUIDE / "skills" / "common" / "picking-instruments" / "scripts" / "build_audition.py"
spec = importlib.util.spec_from_file_location("instrument_audition", SCRIPT)
audition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audition)


class Players(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "audio":
            self.sources.append(dict(attrs)["src"])


def test_manifest_builds_a_page_with_resolvable_local_audio(tmp_path, capsys):
    audio = tmp_path / "声 音 #1&'.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x01" * 1600)
    candidate = {"id": "C01", "label": "a <bright>", "note": "A & B </script>",
                 "facts": {"root MIDI": 72}, "audio": [{"label": "原切片", "path": audio.name}]}
    doc = {"title": "选择 <音色>", "groups": [
        {"name": "Lead", "candidates": [candidate]},
        {"name": "Kick", "candidates": [candidate, {**candidate, "id": "C02"}]},
    ]}
    source = tmp_path / "review.json"
    source.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8-sig")
    assert audition.main([str(source)]) == 0
    output = source.with_suffix(".html")
    assert str(output) in capsys.readouterr().out
    page = output.read_text(encoding="utf-8")
    players = Players()
    players.feed(page)
    assert len(players.sources) == 3
    assert all((output.parent / unquote(url)).samefile(audio) for url in players.sources)
    assert "a &lt;bright&gt;" in page and "A &amp; B &lt;/script&gt;" in page
    assert audio.read_bytes().startswith(b"RIFF")  # 展示不会改原切片。


def test_missing_media_is_reported_before_writing_a_page(tmp_path, capsys):
    source = tmp_path / "review.json"
    source.write_text(json.dumps({"groups": [{"name": "Bass", "candidates": [
        {"id": "C01", "audio": [{"label": "Original", "path": "missing.wav"}]}]}]}))
    with pytest.raises(SystemExit):
        audition.main([str(source)])
    assert "Audio file does not exist" in capsys.readouterr().err
    assert not source.with_suffix(".html").exists()
