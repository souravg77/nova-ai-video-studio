# Model & capability matrix

How each requested output maps to a capability, its honest default status on
the **target system** (Intel Core i5 12th gen · Intel integrated graphics ·
32 GB memory · local/offline), and the fallback offered when it can't run.

| Requested output | Capability | Default on target PC | Gate | Fallback offered |
|------------------|-----------|----------------------|------|------------------|
| Script / storyboard | script | Supported *after* a small quantized model passes CPU benchmark | benchmark + license | Template skeleton (clearly non-AI) or manual script |
| Narration (TTS) | tts | Supported after model/voice license test | benchmark + voice license | Import a recorded narration; or silent track + captions |
| Subtitles (STT) | stt | Supported after small model test | benchmark | Import an existing .srt/.vtt |
| Imported footage → video | render | **Primary supported workflow** | none (FFmpeg) | — (this *is* the reliable path) |
| Still-photo motion | render (Ken Burns) | Supported | none | Static still if motion disabled |
| AI image generation | image | Experimental / disabled | approved model + benchmark | Import an image; lower resolution |
| Talking-head animation | face | **Unsupported / blocked by license** | CUDA + VRAM + approved model | Motion-animated still; imported footage |
| Photorealistic text/image-to-video | video | **Unsupported on this PC** | CUDA + measured VRAM + approved model | Imported footage; motion still; shorter low-res test |

## What "Maximum" means
Maximum = *try the highest tested configuration this machine supports*, not
*always generate*. If the request exceeds tested capability the app shows the
exact blocker and a suggested fallback **before** spending significant
resources, and never silently lowers quality or claims footage was created.

## Future 24 GB+ NVIDIA target
24 GB VRAM is a useful target, not a universal guarantee. Model architecture,
quantization, frame resolution, frame count, temporal context and system RAM
all affect feasibility. The app reads a model's tested requirements, then
benchmarks it on the actual GPU before unlocking a preset.
