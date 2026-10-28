# Phase 4 — Three-Photo Identity & Motion Studio

Turns three supplied photos into a short speaking-video sequence using the
selected Phase 3 voice — **only** where the hardware, models, licenses and
consent all allow it. On the current Intel-iGPU target, talking-head
generation is **unsupported** and reported as such; the GPU-free parts (intake,
preparation, gating, consent, provenance) are built and tested now.

## Components (`phase4/`)

| Module | Role | Hardware |
|--------|------|----------|
| `intake.py` | Validate exactly three photos: format, resolution, brightness, face visibility. Report unusable ones; require user approval. Originals never modified. | CPU |
| `identity_prep.py` | Crop/align faces into project-local copies; optional background removal. Preserves originals; honest when alignment/bg-removal isn't available. | CPU |
| `generation_engine.py` | Talking-head engine registry (SadTalker, Wav2Lip) + capability gates. **Blocks** generation on iGPU / low VRAM / missing model / non-commercial license. | gate is CPU; generation needs GPU |
| `provenance.py` | Likeness + voice authorization; records a provenance manifest (hashed source photos, voice, engine version, settings, consent IDs). | CPU |

## P4.1 — Intake
`studio.intake_photos([p1, p2, p3])` returns per-photo validation. A photo is
unusable if it's unreadable, below 256px, too dark/washed-out, or has no
detectable face. If OpenCV's face cascade isn't installed, face visibility is
flagged **unverified** (a warning) — never assumed present. Approval requires
exactly three usable photos.

## P4.2 — Identity preparation
`studio.prepare_identity(sources, project)` writes cropped/aligned 512px copies
to `projects/<id>/identity/`. **The originals are never touched** (verified by
hash in tests). When no face is detected it falls back to a centre crop and
flags the result as **not face-aligned**. Background removal runs only if a
supporting library is installed, otherwise it's reported as skipped.

## P4.3 — Generation engine interface + gates
`studio.generation_registry(installed_ids).decide(engine_id)` returns an honest
verdict: `not_installed`, `unsupported_on_this_pc`, `blocked_by_license`, or
`supported`. Generation requires a **confirmed NVIDIA CUDA GPU** with enough
measured VRAM — Intel shared memory never counts. On the current PC every
talking-head engine resolves to **unsupported**, with the fallback to export a
still-photo video with narration + subtitles. **No fake clip is ever produced.**

## P4.5 — Consent & provenance
`studio.authorize_talking_head(likeness, voice_consent, use)` requires BOTH a
complete, verified likeness-consent record (authorization to use the person's
face) AND a verified voice-consent record, matched to the intended use. Any gap
blocks generation. A `GenerationProvenance` manifest records the hashed source
photos, selected voice, generation engine + version, settings, and both consent
IDs, so a produced clip is traceable to its authorization.

## Build order & hardware reality
Per the roadmap, the still-image-based work (intake, prep, gating, consent) is
complete and GPU-free. The **actual talking-head generation milestone remains
blocked** until a compatible NVIDIA model is installed and real inference is
benchmarked on that hardware. A 24 GB GPU is a target, not a guarantee — model
architecture, VRAM, RAM, drivers, resolution and clip length all matter, and
each must pass a benchmark before a preset is unlocked.

## P4.6 — Photo → still-video export (usable on this hardware)
`phase4/still_video.py` is the honest, CPU-only video workflow the gates point
to. `StillVideoExporter.export(scenes, work_dir, output_path, config,
voice_profile)` runs four stages:

1. **Narration** — optional but honest. With a voice profile it synthesises
   per-scene narration (reusing the Phase 3 `NarrationManager`); if that fails
   it **stops with the blocker** rather than shipping a silent video. Without a
   voice it renders captions-only and says so.
2. **Subtitles** — aligns an SRT to the real narration (or builds one from
   captions), flagging missing/silent audio.
3. **Render** — Ken Burns scenes + narration + music → MP4 at configurable
   resolution / fps / preset (`ExportConfig`). Subtitles are muxed as a soft
   `mov_text` track.
4. **Validation** — confirms the file exists, has a video stream, correct
   duration, audio when narration was requested, a subtitle track when
   expected, and decodes cleanly. Failures are reported, never hidden.

Driven from the UI by **"Make photo video (no GPU needed)"** (enabled once three
photos pass intake) and from code via `studio.photo_video(project, scenes,
config, voice)`, which runs it through the job queue with progress and
cancellation. Originals are never modified; temporary files are cleaned up.

## Verification boundary (unchanged)
Phase 4's tests prove intake/prep/gating/consent/provenance **and the P4.6
still-video export** with real images and (for narration) a real-file Piper
shim. They do **not** prove real talking-head inference — that needs a
compatible GPU and installed model, verified separately. The gates are designed
so that until then, NOVA tells the truth: this PC cannot generate a speaking
video, but it *can* produce a real narrated, subtitled photo video.
