# Third-party runtime and model notices

OttoSmasher's own source is GPL-3.0-or-later; see LICENSE. Third-party software retains its own license and copyright notices. Model weights are not included in application builds.

The build scripts and pinned dependency manifests are part of the source distribution. Python package metadata/license files and conda package metadata are retained in the runtime archives. Rubber Band's original COPYING and README accompany its executable under `core/share/licenses/rubberband`.

| Component | Source and license information |
|---|---|
| Electron and Chromium | https://github.com/electron/electron ; packaged Electron LICENSE and LICENSES.chromium.html |
| Python | https://www.python.org/downloads/source/ ; Python Software Foundation license |
| libmpv 0.41.0 | https://github.com/mpv-player/mpv/tree/v0.41.0 ; GPL-2.0-or-later, with component exceptions described upstream |
| Windows libmpv build | Exact release URL and SHA-256: scripts/setup_player_windows.py; build recipes https://github.com/shinchiro/mpv-winbuild-cmake |
| FFmpeg | https://ffmpeg.org/releases/ ; builds in this project include GPL components; actual version/build recorded in conda-meta |
| Rubber Band 4.0.0 | https://breakfastquay.com/files/releases/rubberband-4.0.0.tar.bz2 ; GPL-2.0-or-later; official executable archive pinned by scripts/setup_rubberband.py |
| conda-forge binary packages | Package URLs, versions and builds in conda-meta; recipes at https://github.com/conda-forge |
| Frontend dependencies | desktop/pnpm-lock.yaml; notices in upstream npm packages |
| Python core dependencies | pyproject.toml and runtime site-packages/*.dist-info |

No model license is replaced by the application's GPL license. Model and inference-source acquisition remains separate and explicit. A formal release must also provide the corresponding third-party source/build material required by the actual distributed binaries; experimental Actions artifacts are not a claim that release compliance, signing or platform acceptance has been completed.
