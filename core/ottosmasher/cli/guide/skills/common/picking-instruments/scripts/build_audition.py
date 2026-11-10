#!/usr/bin/env python3
"""Build a local audition page from existing audio and a JSON manifest.

Usage: python build_audition.py review.json
Input shape and examples: references/auditions.md in the installed skill.
Only the standard library is needed; no audio is processed or copied.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote


STYLE = """
:root {font:15px/1.6 system-ui,sans-serif;color:#253a32;background:#f3f5f0}
* {box-sizing:border-box} body {max-width:1240px;margin:auto;padding:28px}
h1 {font-size:30px;margin:0} h2,h3 {margin:0 0 8px} p {margin:8px 0 16px}
a {color:#26644d} small {color:#617267} nav {display:flex;gap:12px;align-items:center;
position:sticky;top:0;padding:12px 0;background:#f3f5f0;z-index:1}
select,button {font:inherit;padding:7px 12px;background:white;border:1px solid #c6d2c3;border-radius:7px}
section {background:white;border:1px solid #dce4d7;border-radius:14px;padding:22px;margin:18px 0}
.cards {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(270px,100%),1fr));gap:16px}
article {background:#f6f8f3;border-radius:10px;padding:16px;overflow-wrap:anywhere}
article:first-child {border-top:3px solid #37775d} audio {width:100%;height:36px;margin:6px 0 12px}
dl {font-size:13px;margin:12px 0} dt {display:inline;color:#617267} dd {display:inline;margin:0}
dd::after {content:'';display:block} details {margin-top:12px} summary {cursor:pointer}
[hidden] {display:none!important} @media(max-width:600px) {body {padding:14px} section {padding:15px}}
"""

PLAYER_JS = """
const players = [...document.querySelectorAll('audio')];
const stop = () => players.forEach(p => p.pause());
document.querySelector('#stop').addEventListener('click', stop);
document.querySelector('#part').addEventListener('change', e => {
  stop();
  document.querySelectorAll('section[data-group]').forEach(section => {
    section.hidden = e.target.value !== 'all' && section.dataset.group !== e.target.value;
  });
});
document.addEventListener('play', e => {
  if (e.target.tagName === 'AUDIO') players.forEach(p => { if (p !== e.target) p.pause(); });
}, true);
"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def audio_url(path: str, directory: Path) -> str:
    media = (directory / path).resolve()
    if not media.is_file():
        raise ValueError(f"Audio file does not exist: {media}")
    try:
        relative = Path(os.path.relpath(media, directory)).as_posix()
        return quote(relative, safe="/")
    except ValueError:  # Windows files on different drives.
        return media.as_uri()


def build_page(document: dict, directory: Path) -> str:
    groups = document["groups"]
    if not groups:
        raise ValueError("Provide at least one group with candidates")
    sections, options = [], ['<option value="all">All parts</option>']
    for index, group in enumerate(groups):
        name = esc(group["name"])
        options.append(f'<option value="{index}">{name}</option>')
        if not group["candidates"]:
            raise ValueError(f"Group has no candidates: {group['name']}")
        cards = []
        for candidate in group["candidates"]:
            ident = esc(candidate["id"])
            label = esc(candidate.get("label", ""))
            facts = "".join(f"<dt>{esc(k)}: </dt><dd>{esc(v)}</dd>"
                            for k, v in candidate.get("facts", {}).items())
            players = []
            for audio in candidate["audio"]:
                url = esc(audio_url(audio["path"], directory))
                caption = esc(audio["label"])
                players.append(f'<div><small>{caption}</small>'
                               f'<audio controls preload="none" aria-label="{name} {ident} {caption}" src="{url}"></audio>'
                               f'<a href="{url}">{caption}</a></div>')
            if not players:
                raise ValueError(f"Candidate has no audio: {candidate['id']}")
            more = ('<details><summary>More audio</summary>' + "".join(players[1:]) + '</details>') if len(players) > 1 else ""
            cards.append(f'<article><h3>{ident} <small>{label}</small></h3><dl>{facts}</dl>'
                         f'{players[0]}<p>{esc(candidate.get("note", ""))}</p>{more}</article>')
        sections.append(f'<section data-group="{index}"><h2>{name}</h2>'
                        f'<p>{esc(group.get("note", ""))}</p><div class="cards">{"".join(cards)}</div></section>')
    title = esc(document.get("title", "Instrument candidates"))
    return (f'<!doctype html><html lang="{esc(document.get("lang", "en"))}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{STYLE}</style></head>'
            f'<body><header><h1>{title}</h1><p>{esc(document.get("note", ""))}</p></header>'
            f'<nav><label for="part">Part</label><select id="part">{"".join(options)}</select>'
            f'<button id="stop" type="button">Stop audio</button></nav><main>{"".join(sections)}</main>'
            f'<script>{PLAYER_JS}</script></body></html>')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    source = args.manifest.resolve()
    output = source.with_suffix(".html")
    if output == source:
        parser.error("Use a JSON input filename; the HTML is written beside it")
    try:
        document = json.loads(source.read_text(encoding="utf-8-sig"))
        page = build_page(document, source.parent)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    output.write_text(page, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
