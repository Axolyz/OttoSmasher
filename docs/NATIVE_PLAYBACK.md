# macOS libmpv playback

The Electron Helper uses libmpv for original video, reference stems, sample audio,
rendered auditions, OP/ED review, and the host workflow review player. WaveSurfer
still provides peaks, regions, zoom, overview, spectrum and F0 overlays; its media
clock is supplied by the same native player. This is embedded playback, not an
external mpv window.

## Installation

```sh
.runtime/envs/core/bin/python scripts/setup_player.py
pnpm --dir desktop run build
pnpm --dir desktop start
```

The installer uses project-local micromamba to install mpv 0.41.0 and Node 22
headers into `.runtime/envs/player`, then compiles `desktop/native/player.mm`
into `.runtime/player.node`. Apple Command Line Tools are required; the setup
script avoids the `/usr/bin/clang++` launcher stub. `--build-only` recompiles
without downloading. Run it after editing native code or moving the checkout.
`setup_desktop.sh` also prepares the engine when missing. No global shell or
Python environment changes are made.

The current native view is macOS-specific (Cocoa/OpenGL, ABI-stable N-API).
Windows/Linux view embedding is not implemented. An unavailable native runtime
is an explicit error in Electron, never a silent return to proxy playback.
Browser-only Helper and the explicitly separate historical demo retain web
playback. Plugin-owned arbitrary HTML players are not injected or rewritten;
plugins using the host review/play bridge receive the native player.

## Audio identity and clocks

`/api/samples/{id}/reference` accepts `native: true`. For video sources this
returns a small immutable descriptor URL, source origin, range duration and a
separate waveform URL. It does not encode or copy video. Raw audio picks the
selected container audio stream, converting FFmpeg stream indices to mpv audio
track IDs. A separated track opens as an external audio file with:

```
audio-delay = source range start - selected asset range start
local UI time = mpv source time - source range start
```

The original audio track is disabled before loading an external stem, including
while it is being attached. Missing or changed assets fail explicitly. File
size and modification time are checked against the descriptor before reuse.
Existing residual recipes may still need audio materialization; this is not a
video proxy and is never replaced with raw mix. Saved/rendered audio and its
provenance are unchanged.

Source-range playback has explicit native start/end limits. The WaveSurfer
adapter exposes local time, duration, seek/play/pause/end/error events and keeps
pending seeks until readiness. No extra independent browser decoder plays the
same sound. Native players are released on component disposal/window close.
Subtitle context is drawn below the native picture so it remains visible and
selectable. Embedded/automatically discovered mpv subtitles are disabled to
avoid duplicating or substituting the selected subtitle version.

## UI boundary

Video transport is an Ant Design control bar; click/Space toggles playback and
Left/Right seeks five seconds when the picture has keyboard focus. Native view
geometry follows layout, zoom and scrolling. A view is hidden when outside its
visible pane or beneath an overlapping modal/popup (macOS native views sit above
Chromium). Playback state and selection remain in the shared UI.

Whole-file decoding uses VideoToolbox where supported, with software decode
available in the engine for other codecs. `videotoolbox-copy` observed in the
local validation means hardware decoding with a frame copy, not zero-copy.
Seeking still requires decoding forward from a nearby keyframe; immediate
arbitrary-frame seeking cannot be promised for every source.

## Cache behavior

Native video playback adds only descriptor JSON and optional precomputed
waveform peaks, not full-length converted video or HLS segments. Waveform
preparation does not block opening or seeking video. libmpv has its own bounded
in-memory demux/decode buffers. Prior proxy caches are retained; the migration
does not delete existing files. Analysis, rendered audio and persistent exports
remain separate from disposable playback caches.

## Validation (2026-09-22)

- Minimal Electron/native-view test: real 1920×1080 HEVC Main10/FLAC Kemono Friends
  episode, 1466.01 seconds. Picture visible in embedded view; runtime reported
  `videotoolbox-copy`; seek to 1200 seconds and back to 101 seconds completed.
- BandIt v2 dialogue WAV selected as external audio (`aid=2`, PCM float32), with
  100-second source offset. No video proxy created.
- Integrated Helper: opened the subtitle-free Yuru Yuri episode 03, displayed
  23:56 full duration, native picture and progressing native/WaveSurfer clocks.
- Native audio-only engine smoke test: WAV decode, exact seek and native range-end stop passed.
- Subsequent integrated click-through (sample/OP review and track switching in the final UI) was interrupted by macOS lock screen; it is not claimed as completed.
- Automated tests cover source/stem offsets, container track mapping, unchanged
  media, missing stems, deferred peaks, adapter readiness/seeking, old-generation
  events and IPC ownership/URL restrictions. No model jobs or REAPER retests.

Runtime diagnostics for focused development checks only:
`OTTO_PLAYER_QA=1 pnpm --dir desktop start` writes current engine properties to
`.runtime/player-states.json`. Normal launches do not write this debug file.

Upstream interfaces: [libmpv rendering](https://github.com/mpv-player/mpv/blob/master/include/mpv/render_gl.h),
[mpv command/options reference](https://mpv.io/manual/stable/),
[Electron native window handle](https://www.electronjs.org/docs/latest/api/browser-window#wingetnativewindowhandle).
The conda-forge mpv distribution includes its own license notices; distributing
a packaged app must preserve those and the licenses of bundled dependencies.
