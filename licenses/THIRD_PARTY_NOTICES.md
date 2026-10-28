# Third-party notices

This file collects attribution and license notices for bundled components.
Populate it fully before any commercial release.

## Runtime dependencies (installed via pip)
- **pydantic** — MIT License.
- **platformdirs** — MIT License.
- **PySide6 / Qt for Python** — LGPLv3 / commercial. If you distribute the app,
  comply with the chosen licensing path (dynamic linking, offer of source for
  LGPL components, or a commercial Qt license). Include the Qt notices.

## External tools (not bundled by default)
- **FFmpeg / FFprobe** — license depends on the exact build (GPL or LGPL, codec
  components vary). If you bundle a build, include its license text and the
  list of enabled components. See https://ffmpeg.org/legal.html.

## Models (none bundled by default)
No model weights or voices are included in source control. Each must be added
in a controlled stage and recorded in `MODEL_APPROVALS.md` with its license.

---
Add the full verbatim license texts here (or under `licenses/third_party/`)
for every component actually shipped.
