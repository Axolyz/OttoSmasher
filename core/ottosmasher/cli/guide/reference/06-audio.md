# Verify audio tools

## Discover before asking

Check your exposed tools for audio-mcp, then inspect `otto setup audio --for other` if absent. Existing host MCP access is preferable. CLI tools (view/analyze/timeline/melody) can work without a host MCP connection. Transcription in audio-mcp 0.4.0 requires MCP; the subtitle skill provides `scripts/audio_probe.py`, a small stdio client usable from any agent without editing host configuration. Discover its actual path from `otto guide preparing-subtitles`.

```sh
uv run /path/to/scripts/audio_probe.py requests.json results.json
```

For CLI, get actual syntax first:
```sh
uvx --from 'audio-mcp[speech]==0.4.0' audio-mcp view --help
uvx --from 'audio-mcp[speech]==0.4.0' audio-mcp analyze --help
```

The helper saves returned images beside the JSON output and prints their paths. Open these with your image viewer; summary numbers are not visual inspection.

Run view on a real short clip and run the capabilities required for the task (for subtitle content checks, also transcribe). Report each as verified / unavailable / untested. A working view does not verify transcription. An empty transcript is a successful call with no recognized words, not proof of silence.

## Prepare short input

Use `exports.wav` on a short asset range, preserving its returned mapping, or ffmpeg on the exact source path returned by the app. Pass the extracted file to audio-mcp rather than a whole episode plus start/end: the upstream tool may decode the full episode before slicing. Content checks need a complete sentence and adjacent context; tiny phoneme windows are unreliable ASR inputs.

First use installs packages; first turbo transcription may download roughly 1.6 GB. Explain this before starting a large new download when its cost matters. Reuse an existing verified cache; offline runs use HF_HUB_OFFLINE=1 only when the model is already complete. On download failures preserve the error, check network/proxy or a user-approved model path, and resume normally. Do not blindly change global proxy settings or assemble unverified model caches.

If capabilities are missing, continue independent preparation and ask only for what cannot be supplied in your environment. Permission to do work does not permit escaping a denied sandbox. The app's status checks its own models, not the agent's external MCP server.

## Use evidence together

Waveforms and energy help identify suspicious cuts; they cannot identify the speaker or which sentence a tail belongs to. ASR checks whether content is present, may omit high-pitched cries or hallucinate, and its timestamps are approximate. Alignment fits the supplied text into a window even when the wrong sound is there. Use the actual curve, original captions, full-sentence content, neighbouring speech and optional alignment/voiceprints together. A/B windows with more/less context can help, but ASR differences alone are not proof.
