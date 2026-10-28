# Phase 3 — Voice Studio

Turns the Phase 2 scene script into consistent, expressive narration with
synchronized subtitles, and gates voice cloning behind consent + authorization.
Local-first: missing models produce a clear blocker, never an automatic
download.

## Components

| Module | Role |
|--------|------|
| `voice/engine.py` | `VoiceEngine` interface + `EngineCapabilities`; Piper (local) and XTTS-v2 (cloning, non-commercial) engines. Reports real availability. |
| `voice/registry.py` | `VoiceRegistry` / `VoiceGallery` — installed engines, their voices (language, quality, license), capabilities. |
| `voice/expression.py` | Pronunciation dictionary + expression settings (speed, pause, emphasis, emotion). Applies what the engine supports; reports the rest as **unsupported**. |
| `voice/subtitles.py` | SRT alignment from **real** per-scene audio durations; flags missing/silent/clipped/too-short audio. |
| `voice/narration.py` | Scene-by-scene narration with a consistent voice; **regenerate one scene** without redoing others; validates each WAV. |
| `voice/cloning.py` | Consent records + `evaluate_cloning()` safeguards + auditable `ConsentLog`. Blocks on any gap. |

## P3.1 — Voice library & auditions
`studio.voice_gallery()` returns each engine's status: available (runtime +
voice present), capabilities, and per-voice language/quality/license. An engine
with no runtime installed is reported unavailable with the reason — never shown
as usable.

## P3.3 — Expression & pronunciation
`resolve_expression(text, settings, caps, pron)` returns the concrete text +
engine params to send, plus `applied` and `unsupported` lists. Piper supports
speed (`length_scale`), sentence pause, and pronunciation rewrites; it does
**not** support per-word emphasis or emotion — those are reported unsupported,
not silently ignored.

## P3.2 — Scene narration & regeneration
`NarrationManager.generate_all(texts, dir)` makes one validated WAV per scene
with a consistent `VoiceProfile`. `regenerate_scene(scenes, index, dir,
new_text=…)` re-synthesises a single scene and leaves every other scene's audio
byte-for-byte unchanged.

## P3.4 — Subtitle synchronization
`align_subtitles(scene_audios)` builds SRT cues timed to the real narration and
returns validation flags. `write_srt(...)` emits the file. The renderer muxes
it into the MP4 as a soft `mov_text` track (`RenderSpec.subtitle_srt_path`), and
the pipeline runs a **subtitles** stage between narration and render — if any
scene's audio is missing/silent, the stage fails with the exact scene flagged
and the pipeline stops rather than shipping misaligned subs.

## P3.5 — Cloning safeguards
`evaluate_cloning(engine_id, record, intended_use)` returns a decision that is
`allowed=True` **only** when: the engine is an approved cloning engine, its
license permits the intended use (XTTS-v2 is **non-commercial** — commercial
cloning is always blocked), a complete consent record exists (speaker identity,
authorization evidence, permitted use), and verification is `verified`. Every
decision is appended to an auditable `ConsentLog`.

## Verification boundary (unchanged)
Phase 3's tests prove the **structure, alignment, validation and safeguards**
using real audio files (subtitles, cloning, expression are model-free) and a
real-file Piper shim for narration. **Real Qwen2.5 + Piper inference still needs
to run on your Windows PC** before declaring production readiness — install the
runtimes and a licensed voice, then the same code paths run unchanged.
