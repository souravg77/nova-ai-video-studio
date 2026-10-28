# Support matrix

| Platform | Hardware report | Editing/export | AI generation |
|----------|-----------------|----------------|---------------|
| Windows 11 (primary target) | PowerShell/CIM — installed RAM, GPU, driver, disk | FFmpeg pipeline | Tier-gated; add models in controlled stages |
| Linux / macOS (development) | /proc + shutil + nvidia-smi fallback | FFmpeg pipeline | Tier-gated |

## Phase 1 "definition of done" status

| Requirement | Status |
|-------------|--------|
| User can create and reopen a project | ✅ (SQLite store; integration test) |
| Import a video, image and audio file | ✅ (asset registry + probe; rejects bad input) |
| Show actual hardware, active profile, and why | ✅ (hardware CLI + capability manager) |
| Render a 60s sample from footage with narration + subtitles | ✅ (renderer; export tests; A/V validated) |
| Fail a benchmark safely and say what it can't do | ✅ (honest verdicts; adapter tests) |
| No output labelled "generated" unless files exist and validate | ✅ (job queue + quality_checks) |
| Runs without internet using installed assets | ✅ (offline test blocks sockets) |

## Known constraints in the build/CI sandbox
- PySide6 cannot be installed in the offline CI sandbox, so the GUI is
  validated by compile-check + a headless logic harness. On Windows,
  `build_windows.ps1` installs it and `python -m nova_studio.app` launches the
  full window.
- Benchmarks reflect the CI machine; re-run on the target PC for real figures.
