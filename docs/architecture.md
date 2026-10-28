# Architecture

NOVA is layered so that **capability truth** flows from measured hardware and
benchmarks up to the UI, and work flows down through a job queue to isolated
adapters.

```
┌──────────────────────────────────────────────────────────────┐
│ Desktop UI (PySide6)  ui/main_window.py, app.py                │
│   profile selector · hardware panel · render · honest notices  │
└───────────────┬──────────────────────────────────────────────┘
                │ drives
┌───────────────▼──────────────────────────────────────────────┐
│ Studio facade  core/studio.py                                  │
│   owns store, queue, capability manager, renderer              │
└───┬───────────────┬───────────────┬──────────────┬────────────┘
    │               │               │              │
┌───▼────┐   ┌──────▼──────┐  ┌─────▼─────┐  ┌─────▼──────┐
│Capability│  │ Job queue   │  │ Media     │  │ Project    │
│ manager  │  │ job_queue.py│  │ engine    │  │ store      │
│capability│  │ handlers.py │  │ renderer/ │  │ sqlite_... │
│.py       │  │ (worker thr)│  │ probe/... │  │ asset_reg  │
└───┬──────┘  └─────┬───────┘  └───────────┘  └────────────┘
    │               │
┌───▼──────┐  ┌─────▼────────────────────────────────────────┐
│ Hardware │  │ AI adapters  adapters/{llm,tts,stt,vision,     │
│ detect   │  │ video_generation}.py — one per runtime/model, │
│hardware.py│  │ pinned + isolated; honest availability()      │
│ benchmark│  └───────────────────────────────────────────────┘
└──────────┘
```

## Key modules

| Path | Responsibility |
|------|----------------|
| `config.py` | Paths (user data outside install dir), offline policy, storage floors |
| `models/` | Typed pydantic models: hardware_report, project, job, benchmark, registry |
| `core/hardware.py` | Measured hardware report (PowerShell/CIM on Windows; /proc fallback) |
| `core/capability.py` | Tier detection, profile selection, per-job honest verdict |
| `core/benchmark.py` | Repeatable benchmark harness (median runtime, peak RAM, validation) |
| `core/job_queue.py` | Worker-thread queue; enforces "validated output or it didn't happen" |
| `core/handlers.py` | Render handler + gated AI handlers (verdict before work) |
| `core/recovery.py` | Marks interrupted RUNNING jobs FAILED on startup |
| `core/studio.py` | Facade the UI/CLI drive |
| `media/renderer.py` | FFmpeg assembly: Ken Burns stills, clips, captions, audio mix, export |
| `media/probe.py` / `quality_checks.py` | FFprobe metadata + output validation |
| `storage/sqlite_store.py` | Thread-safe SQLite + JSON manifest persistence |
| `adapters/` | Script/TTS/STT/image/face/video adapters with honest unavailability |
| `ui/main_window.py` | PySide6 window; worker→Qt signal bridge; honest notices |

## Threading & safety
- The job queue runs one worker thread. The SQLite connection uses
  `check_same_thread=False` with a serialising lock.
- AI adapters with heavy/conflicting dependencies are designed to be dispatched
  to separate worker **processes**; the handler map makes this swappable.
- The renderer uses explicit FFmpeg argument lists (no shell string
  interpolation) and escapes all drawtext captions.

## Honesty invariants
1. Capability is computed only in `core/capability.py` from measured data —
   never guessed in the UI.
2. A job reaches `COMPLETED_AND_VALIDATED` only if its declared outputs exist
   and pass validation.
3. Generation adapters return `ok=False` + a reason rather than fabricating
   output.
4. Installed RAM / page file / shared memory / dedicated VRAM are distinct
   fields, and profiles gate on installed RAM and *confirmed* VRAM only.
