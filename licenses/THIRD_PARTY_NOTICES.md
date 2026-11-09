# Third-party notices

This file collects attribution and license notices for bundled components.
Populate it fully before any commercial release.

## Runtime dependencies (installed via pip)
- **pydantic** — MIT License.
- **platformdirs** — MIT License.
- **PySide6 / Qt for Python** — LGPLv3 / commercial. If you distribute the app,
  comply with the chosen licensing path (dynamic linking, offer of source for
  LGPL components, or a commercial Qt license). Include the Qt notices.

## Bundled tools
- **FFmpeg / FFprobe** — shipped next to `NOVA-Studio.exe` by the Windows
  installer. The build is a static Windows build ("essentials" build from
  gyan.dev, installed on the CI runner through the Chocolatey `ffmpeg`
  package, or downloaded from gyan.dev / BtbN as a fallback). These builds
  enable GPL components (for example libx264), so the bundled binaries are
  distributed under the **GNU General Public License v3**. Its full text is
  installed as `ffmpeg-licenses\LICENSE.txt`. FFmpeg is a separate program
  that NOVA runs as a subprocess; it is not linked into NOVA.
  - Source code for the exact FFmpeg version shipped is available from
    https://ffmpeg.org/download.html and from the build provider
    (https://www.gyan.dev/ffmpeg/builds/). Before a commercial release,
    record the exact build, its enabled components (`ffmpeg -buildconf`)
    and keep a copy of the corresponding source to honour the GPL's
    source-availability terms. See https://ffmpeg.org/legal.html.

## Models (none bundled by default)
No model weights or voices are included in source control. Each must be added
in a controlled stage and recorded in `MODEL_APPROVALS.md` with its license.

---
Add the full verbatim license texts here (or under `licenses/third_party/`)
for every component actually shipped.
