# Model & dependency approval tracker

**Policy:** No model or redistributable may be marked "commercially approved"
until its code, weights, assets, redistribution terms, attribution obligations
and use restrictions have been checked. Store the approval decision and
evidence with the release. *Free-to-download does not mean commercially usable.*

Status values: `unreviewed` · `approved` · `blocked`

| Component | Candidate | Capability | License to verify | Status | Evidence / notes |
|-----------|-----------|------------|-------------------|--------|------------------|
| Desktop UI | PySide6 / Qt for Python | ui | LGPL/commercial; review dynamic linking + distribution | unreviewed | Choose and comply with a licensing path before shipping |
| Script LLM | Qwen2.5-1.5B-Instruct GGUF Q4_K_M (0.5B fallback) | script | Model Apache-2.0; verify exact GGUF repo + quantized redistribution | unreviewed | Recommended P2 starter for CPU-only Intel-iGPU PC; run via llama.cpp |
| Local TTS | Piper | tts | Engine GPL-3.0 upstream; **each voice** has its own terms | unreviewed | Inspect every bundled voice separately |
| Alt TTS | Kokoro | tts | Exact release + weights + voice assets + deps | unreviewed | — |
| Speech recognition | whisper.cpp | stt | Project MIT; model assets reviewed separately | unreviewed | — |
| Inference | OpenVINO | runtime | Runtime notices + redistributables + device reqs | unreviewed | — |
| Media | FFmpeg | render | Exact build flags, GPL/LGPL components, codecs, notices | unreviewed | Include required notices if bundled |
| Visual workflows | ComfyUI | image | App license **plus every node and model** | unreviewed | — |
| Face animation | SadTalker / Wav2Lip | face | Code + weights + deps + intended commercial use | **blocked** | Do not ship until fully cleared |
| Voice cloning | XTTS-v2 (Coqui) | voice-clone | Published license is **non-commercial** | **blocked for commercial** | Personal/internal cloning only with a verified consent record; never commercial |
| Talking-head | SadTalker | face/motion | Code + weights + deps + intended use | **blocked** | Needs confirmed NVIDIA CUDA + ≥6 GB VRAM; not cleared for commercial; requires likeness+voice consent |
| Lip-sync | Wav2Lip | face/motion | Code + weights + deps + intended use | **blocked** | Needs confirmed NVIDIA CUDA + ≥4 GB VRAM; not cleared for commercial; requires likeness+voice consent |

## Official references
- OpenVINO system requirements: https://docs.openvino.ai/2026/about-openvino/release-notes-openvino/system-requirements.html
- Intel Windows ML support: https://www.intel.com/content/www/us/en/developer/articles/guide/windows-ml-support.html
- Qwen2.5: https://github.com/QwenLM/Qwen2.5
- Piper: https://github.com/OHF-Voice/piper1-gpl
- Kokoro: https://github.com/hexgrad/kokoro
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- FFmpeg licensing: https://ffmpeg.org/legal.html
- ComfyUI: https://github.com/Comfy-Org/ComfyUI
- SadTalker: https://github.com/OpenTalker/SadTalker
- Wav2Lip: https://github.com/Rudrabha/Wav2Lip
