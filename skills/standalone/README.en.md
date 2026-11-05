# Preprocessing skills for otoMAD material

Five standalone [Agent Skills](https://agentskills.io/specification) for preprocessing Japanese speech material such as anime. They need no app, and work with any agent that can run commands, such as Claude Code or Codex.

| Skill | What it does |
|---|---|
| `cleaning-subtitles` | Cleans subtitles: spoken words only, one person per cue |
| `retiming-subtitles` | Fixes subtitle timing against speech, including other releases |
| `labeling-speakers` | Labels lines by speaker with voiceprints (experimental) |
| `transcribing-without-subtitles` | Makes timed subtitles for material with none (tools not settled) |
| `finding-op-ed` | Compares audio across episodes to find opening and ending songs |

Cleaning, splitting and speaker labeling work best in one pass; `cleaning-subtitles` gives the order.

## Install

Copy the folders you need from `en/` (English) or `zh-CN/` (Chinese) to where your agent reads skills, such as `.claude/skills/` or `.agents/skills/` in a project.

## What you need

- **An audio inspection tool:** such as [audio-mcp](https://pypi.org/project/audio-mcp/). Agents that cannot hear rely on it to judge sound.
- **ffmpeg.**
- **A forced aligner:** for `cleaning-subtitles`, `retiming-subtitles` and `labeling-speakers`. The numbers were measured with [pydomino](https://github.com/DwangoMediaVillage/pydomino), which supports Japanese only.
- **Separated vocals:** recommended, for example from PyMSS Studio.
- **uv:** for the voiceprint script in `labeling-speakers`. The first run downloads PyTorch and the model, a few hundred MB.

## Before you use them

These methods come from the author's own exploration, mainly on a few anime series. Treat the numbers as a reference and recalibrate for another show. Results are not guaranteed, so check what matters by hand.

They come from [OttoSmasher](https://github.com/Axolyz/OttoSmasher), which connects these workflows to a sample library and human review.
