# Audio tools

## Connect and try a short clip

Start with the audio-mcp tools exposed by your agent host. If they are absent, `otto setup audio --for other` shows the available connection methods. In audio-mcp 0.4.0, view/analyze/timeline/melody also have CLI commands; transcription uses MCP.

Connect the chosen audio tool through the agent host's MCP support. audio-mcp is the current example; another tool can provide the waveform, measurements or transcription needed by the task. The host manages its connection and dependencies. Otto continues to provide the library, audio exports and time mapping through its CLI.

Check the CLI syntax with:

```sh
uvx --from 'audio-mcp[speech]==0.4.0' audio-mcp view --help
uvx --from 'audio-mcp[speech]==0.4.0' audio-mcp analyze --help
```

Reuse the host connection first. For CLI calls, keep its package version, extras, Python and cache configuration. `uvx` aliases `uv tool run` and reuses isolated cached environments. A missing executable on PATH or an empty `uv tool list` does not establish that a uvx cache is missing: try the existing launch command. Let uv manage the environment; refresh it when upgrading or troubleshooting.

Try the visualization tool on a real short clip and open the returned image. Also try the capabilities the task needs, such as transcribe for subtitle content checks. Note which calls worked and which still need setup. An empty transcript may need a wider window or a check against the original audio.

## Prepare the input

Use `exports.wav` to extract a short asset range and keep its returned mapping, or use ffmpeg on the source path returned by the app. Giving audio-mcp a short file avoids decoding a whole episode for each question. Include the full sentence and enough neighbouring speech to understand it.

First use installs packages. First turbo transcription may download about 1.6 GB, so mention the cost when setting up a new environment. Reuse complete model caches; HF_HUB_OFFLINE=1 is useful once the cache is ready. If a download stops, keep the error and check the network or configured proxy before resuming. Global network settings are for the user to manage.

While setting up audio, continue other preparation. Ask for help with anything your environment cannot provide. `otto status` reports the app's models; external audio tools are checked through their own calls.

## Use the results

Waveforms help locate starts, ends and pauses. Transcripts help check words, though high-pitched cries may be missed and word times are approximate. Alignment refines a window that already contains the right utterance. Use these together with captions and neighbouring speech to decide boundaries and sound ownership; voiceprints can help where needed.
