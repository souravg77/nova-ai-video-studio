# P2 — Script → Narration → Render pipeline

Chains three real stages, each gated by an honest capability verdict and
verified by actual output files. If any model, voice, dependency or hardware
capability is missing, the pipeline stops at that stage and reports the
specific blocker + a fallback — it never simulates a later stage.

```
brief ──▶ [1] ScriptAdapter (Qwen2.5 GGUF / llama.cpp)
              └─ parsed scene JSON  (verified: ≥1 parseable scene)
          [2] TTSAdapter (Piper), per scene
              └─ one validated narration WAV  (verified: ffprobe audio)
          [3] Renderer (FFmpeg)
              └─ MP4 with captions + narration  (verified: validate_output)
```

## Installing the models (manual, never automatic)

NOVA never downloads weights on its own. Place files under the workspace
`models/` directory (`%LOCALAPPDATA%/NovaStudio/models` or `$NOVA_STUDIO_HOME/models`):

```
models/
  script/   Qwen2.5-1.5B-Instruct-Q4_K_M.gguf     (0.5B as fallback)
  tts/      en_US-<voice>.onnx  +  en_US-<voice>.onnx.json
  stt/      ggml-<model>.bin    (optional, for subtitles)
```

Recommended starting model (for a CPU-only Intel-iGPU PC):
**Qwen2.5-1.5B-Instruct-GGUF, Q4_K_M** — Apache-2.0 model license (verify the
exact GGUF repo + redistribution), run via llama.cpp on CPU first. Fall back to
**Qwen2.5-0.5B** if memory or speed is tight.

Install the runtime packages in a separate environment:
```
python -m pip install llama-cpp-python     # script model
# Piper: install the piper CLI or `piper-tts`, plus a licensed voice
```

## Checking readiness

```python
studio.pipeline_readiness()
# -> per-stage {ready, state, blocker, model/voice}
```
With no models installed, `script` and `tts` report `ready: false` with the
exact directory to populate; `render` is always ready.

## Running it

```python
job = studio.auto_video(project, brief="A 3-scene teaser about coffee",
                        visuals=[img1, clip1, img2], scenes=3,
                        listener=on_update)
```
Visuals are your imported images/clips (one per scene; a missing one becomes a
captioned slate). Scene durations follow each scene's real narration length.

## Using it from the desktop UI (P2.5)

The main window has an **Auto Video** panel (no terminal needed):
- A **topic/brief** box and an **Auto Video** button.
- A **readiness line** showing, per stage, whether Qwen2.5, Piper and FFmpeg
  are available — with the exact blocker when a model/voice is missing. The
  button is disabled until script + narration are both ready.
- **Check models** re-scans the models directory after you add files.
- A shared **progress bar + stage label** show "Stage 1/3 … 2/3 … 3/3" and the
  render sub-progress; the **Cancel** button stops a running job.
- The final notice distinguishes an honest blocked stage ("Auto Video stopped:
  <blocker>") from a validated success.

## Honesty guarantees (tested)
- A missing script model → stops at stage 1 with "No script model installed",
  no output file created (`tests/p2/test_pipeline_blocked.py`).
- A missing voice → stage 1 succeeds, stops at stage 2 with the TTS blocker.
- Full success produces a real MP4 with a validated audio track
  (`tests/p2/test_pipeline_success.py`).
- Model downloads require explicit consent **and** a storage check
  (`tests/p2/test_download_consent.py`); the default runtime stays offline.
