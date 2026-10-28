# NOVA AI Video Studio

Hardware-aware, offline-capable AI video studio for **Windows 11**.

Built to the core principle of its roadmap: **never silently promise a result.**
The app measures the machine, shows the active profile, attempts only
compatible workflows, and gives an honest, actionable explanation when a job
exceeds the PC's tested capabilities.

## What it does today (Phase 1)

- **Hardware report** that distinguishes installed RAM from the page file, and
  Intel *shared* memory from *dedicated* VRAM. A GPU name is never treated as
  proof of capability.
- **Capability manager** that selects the highest profile whose required
  benchmarks actually passed (Auto / Balanced / High / Maximum) and returns an
  honest verdict for every generation job (Supported, Supported-with-limits,
  Experimental, Unsupported-on-this-PC, Blocked-by-license, Failed-at-runtime,
  Completed-and-validated).
- **Editing/export pipeline (FFmpeg)** — the primary supported workflow on any
  machine: assemble imported images (with Ken Burns motion) and video clips,
  add narration, burned-in captions and ducked background music, and export a
  **validated** MP4. No AI model required.
- **Job queue** with queued/running/failed/cancelled/completed states, logs,
  progress, cancellation and crash recovery.
- **SQLite + JSON** project store; projects reopen after restart and are
  portable across PCs.
- **Benchmark suite** (section 3): the render benchmark always runs; AI model
  benchmarks skip cleanly and honestly when their runtimes/weights are absent.
- **AI adapters** (script / TTS / STT / image / face / video) that report
  precise unavailability and **never fake success**.
- **P2 auto-video pipeline** (`core/pipeline.py`): Qwen2.5 script → Piper
  narration → FFmpeg render, each stage gated by an honest verdict and verified
  by real output files. Stops at the first missing model/voice with the exact
  blocker. See `docs/p2_pipeline.md`.
- **Phase 3 Voice Studio** (`voice/`): voice engine registry, pronunciation +
  expression settings (honest "unsupported" flags), scene-by-scene narration
  with single-scene regeneration, SRT subtitle alignment muxed into the MP4,
  and consent-gated voice-cloning safeguards. See `docs/p3_voice_studio.md`.
  A **Voice Studio UI panel** exposes the gallery, auditions, settings
  (disabled when the engine can't do them), a pronunciation editor and
  per-scene regeneration.
- **Phase 4 Identity & Motion Studio** (`phase4/`): three-photo intake +
  validation, face crop/align (originals preserved), talking-head generation
  engine registry with **hardware/license gates that block generation on
  Intel iGPU**, and likeness + voice consent with a provenance manifest. See
  `docs/p4_identity_motion.md`. Talking-head generation stays unsupported on
  this PC — no fake clips.
- **P4.6 photo → still-video export** (`phase4/still_video.py`): the usable
  CPU-only workflow — three approved photos → Ken Burns scenes → Phase 3
  narration → aligned subtitles → validated MP4 (configurable
  resolution/fps/preset), with progress, cancellation and honest blockers.
  UI: "Make photo video (no GPU needed)".
- **PySide6 desktop UI** with profile selector, hardware panel, render controls
  and honest failure notices.
- **Offline by default** — the core flow performs no network calls (verified by
  test).

## The NOVA Studio dashboard

The main app is a full studio **dashboard** (`webapp/`): a dark, modern editor
with a media library, scene list, preview + timeline, and a properties panel
(Ken Burns motion, voice, subtitles, export settings). It runs in a **native
window — no console, no browser chrome** — served by a local Flask backend that
drives the real, tested NOVA engine, so the **Render** button produces a
genuine validated MP4.

Run it from source:

```powershell
python -m pip install -r requirements\webapp.txt
python -m webapp.desktop          # opens the dashboard in a native window
```

## Install on Windows 11 (.exe installer)

Build a double-click installer (`NOVA-Setup.exe`) with one command on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
```

This bundles the dashboard + engine + FFmpeg into
`packaging\Output\NOVA-Setup.exe`, which installs NOVA (windowed, no console)
with Start-Menu/desktop shortcuts. Requires Python 3.10–3.12 and Inno Setup 6 on
the build machine. Full details in `packaging/README.md`. (The `.exe` must be
built on Windows — PyInstaller cannot cross-build it from Linux/macOS.)

## Quick start (Windows, from source)

```powershell
# 1. Verify the real hardware first
powershell -ExecutionPolicy Bypass -File scripts\hardware_check.ps1

# 2. Build the environment (venv + base/UI deps, validates FFmpeg)
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1

# 3. Launch the app
.\.venv\Scripts\Activate.ps1
python -m nova_studio.app

# Headless hardware report only:
python -m nova_studio.core.hardware_cli

# Run benchmarks:
powershell -ExecutionPolicy Bypass -File scripts\benchmark.ps1
```

## Quick start (development / Linux / macOS)

```bash
python -m pip install -r requirements/dev.txt
python -m pip install -r requirements/ui.txt   # for the GUI
PYTHONPATH=src python -m nova_studio.core.hardware_cli
PYTHONPATH=src python -m pytest -q
```

## Capability tiers

| Tier | Condition | Unlocks |
|------|-----------|---------|
| 0 Editing | FFmpeg + disk | import, edit, captions, audio mix, export |
| 1 CPU AI | small model passes CPU/RAM benchmark | script, basic TTS, transcription |
| 2 Intel accel | OpenVINO confirms a supported Intel device + passes tests | faster inference |
| 3 NVIDIA GPU | confirmed CUDA GPU + enough measured VRAM | approved CUDA models |
| 4 High VRAM | 24 GB+ dedicated VRAM + models pass benchmark | larger visual models |

Editing/export is available at **every** tier. AI generation is always gated by
a measured benchmark **and** a license approval.

## Honesty guarantees (enforced in code + tests)

- No output is labelled "completed and validated" unless the output file exists
  and passes an FFprobe validation (`media/quality_checks.py`,
  `core/job_queue.py`).
- AI video / avatar generation on an Intel-iGPU machine returns the honest
  "unsupported on this PC" report with fallbacks — it never returns a fake clip
  (`adapters/video_generation.py`, `tests/unit/test_adapters.py`).
- Installed RAM, page file, shared memory and dedicated VRAM are reported
  distinctly (`models/hardware_report.py`, `tests/unit/test_hardware_report.py`).
- A model is only commercially usable once its registry entry is `approved`
  with recorded evidence (`models/registry.py`, `licenses/MODEL_APPROVALS.md`).

## Repository layout

See `docs/architecture.md`. User data lives in `%LOCALAPPDATA%/NovaStudio`
(or `$NOVA_STUDIO_HOME`), never inside the install directory. Model weights,
user photos, footage and generated videos must **not** be committed to source
control.

## Licensing

Every shipped dependency and model must be reviewed before a commercial
release. See `licenses/` and `docs/model_matrix.md`. Free-to-download does not
mean commercially usable.
