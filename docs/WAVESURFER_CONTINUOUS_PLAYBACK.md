# WaveSurfer controls and continuous source review

2026-09-21. WaveSurfer.js is pinned to 7.12.12. The core sample, alignment,
quantization and time-map operations are unchanged.

## Shared controls

The cutter, sample inspector, source-track comparison, sound candidate review,
OP/ED review, and short rendered auditions share the WaveSurfer playback UI.
Regions owns selection handles and read-only annotations; Hover shows source-clock
positions; Timeline, Zoom and optional Minimap provide navigation. Zoom uses the
upstream wheel behavior: vertical wheel zooms, horizontal scrolling pans. Linear
and exponential curves and accumulation thresholds 0/5/15 are selectable and
remembered locally. The previous Shift-wheel customization is removed.

Selection and annotations have separate identities. Selecting or dragging a range
never deletes model phones or OP/ED labels. Clicking phones selects measured
ranges; Shift-click works in either direction. Dragging across annotations creates
a free selection without snapping back to the clicked annotation. Subtitle ranges
are explicitly labeled as subtitle boundaries, not measured phone boundaries.

Playback, selection audition/loop, fit-to-window, fit-to-selection and overview are
shared controls. F0 with twelve-tone reference lines and the rhythm mapping diagram
remain domain-specific overlays. The phone text/source table is collapsible.
No recording, volume automation or multi-track arrangement features are introduced.

## Continuous playback and spectra

The source browser requests the entire source range by default, rather than
restricting its media URL to the first minute. Initial edit selection may still be
60 seconds; it does not limit playback. The source-track reviewer also defaults to
full coverage. Selected stems must cover the requested range; there is no mixed
source fallback. Changing the cutter reference retains source playhead and playing
state where the new track has coverage. Source subtitles remain on source seconds.

Original HEVC/FLAC media uses a seekable H.264/AAC proxy with faststart. The complete
proxy is prepared once and served using HTTP byte ranges. This is not progressive
playback while the first proxy is still encoding: the UI shows a preparation state.
Raw review reuses the existing proxy without generating an extra full WAV and remux.

WaveSurfer uses precomputed peaks, not a full decoded episode AudioBuffer. Detailed
spectra are requested only on demand, at most 30 seconds each. The backend decodes
that bounded interval from the actual selected audio and computes the STFT; reduced
waveform peaks are never fed to FFT. Display data is fixed to a -90 to 0 dB range,
with linear/logarithmic/Mel frequency display options. Short-file spectra scroll
and zoom with the primary waveform. Long-file spectral detail displays a labeled
bounded window whose clicks seek the continuous player; it does not replace its
media URL. This detail window is refreshed explicitly, not on every playback frame.

`waveform()` responses include `visualization_key`. New read-only display routes:
- `GET /api/helper/visualizations/{key}/detail?start=...&end=...`: local seconds in
  the waveform's range; validates bounds, file fingerprint and the 30-second cap.
- `GET /api/helper/visualizations/{key}/spectrum`: WaveSurfer-compatible cached data.

Descriptors bind the source path, audio stream and range server-side. These routes
accept no arbitrary client file path and register no library samples or model
analyses. Visual caches can be deleted independently of persistent media.

## Validation

- 32 distinct focused Python tests passed across media visualization, source browser,
  sample provenance and sound workflows. Includes actual range-response handling,
  a 1,201-second waveform, bounded FFT, source-window frequency identity and stale
  source rejection. Existing dependency deprecation warnings remain.
- TypeScript compilation and Vite production build passed.
- Real episode 02 proxy: 1,466.01 seconds (24:26), first proxy plus full waveform
  preparation measured 46.16 seconds on this machine; this is not a universal speed
  guarantee.
- Headless installed Chrome loaded the real source-browser UI, played naturally
  across 59.5 and 1,199.5 seconds, and opened the on-demand frequency display.
  No JavaScript or media errors in that run. This checks continuity at the old
  boundary and beyond 20 minutes; it is not a 24-minute uninterrupted wall-clock soak.
- Real analyzed sample displayed 12 phone regions and F0, supported reverse
  Shift-selection, and rendered a spectral view without JavaScript errors.
- Local evidence: `.runtime/wavesurfer-ui-validation.json`,
  `.runtime/wavesurfer-sample-validation.json`, and screenshots next to them.
- No model batch, REAPER check, or unrelated full regression was run.
