# Preprocessing skills for otoMAD material

Two standalone [Agent Skills](https://agentskills.io/specification) for preprocessing Japanese speech material such as anime. They need no app, and work with any agent that can run commands, such as Claude Code or Codex.

| Skill | What it does |
|---|---|
| `preparing-subtitles` | Cleans subtitles, fixes timing, splits two-person cues, labels speakers with voiceprints (experimental), and makes timed subtitles when there are none (tools not settled). Run the whole workflow or a single step |
| `finding-op-ed` | Compares audio across episodes to find opening and ending songs |

## Install

Copy the folders you need from `en/` (English) or `zh-CN/` (Chinese) to where your agent reads skills, such as `.claude/skills/` or `.agents/skills/` in a project.

## What you need

- **An audio inspection tool:** such as [audio-mcp](https://pypi.org/project/audio-mcp/). Agents that cannot hear rely on it to judge sound.
- **ffmpeg.**
- **A forced aligner:** for `preparing-subtitles`. The numbers were measured with [pydomino](https://github.com/DwangoMediaVillage/pydomino), which supports Japanese only.
- **Separated vocals:** recommended, for example from PyMSS Studio.
- **uv:** for the voiceprint script used in speaker labeling. The first run downloads PyTorch and the model, a few hundred MB.

## Before you use them

These methods come from the author's own exploration, mainly on a few anime series. Treat the numbers as a reference and recalibrate for another show. Results are not guaranteed, so check what matters by hand.

They come from [OttoSmasher](https://github.com/Axolyz/OttoSmasher), which connects these workflows to a sample library and human review.

## License

The skills and scripts in this folder are released under the [MIT License](LICENSE). The model downloaded by the voiceprint script and its dependencies have their own licenses.
