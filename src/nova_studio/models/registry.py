"""Model registry entries (roadmap section 5 + 9).

No model is 'commercially approved' until code, weights, assets, redistribution
terms and use restrictions are checked. The registry records that decision as
evidence so a release can prove it.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ApprovalStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    BLOCKED = "blocked"


class RuntimeKind(str, Enum):
    FFMPEG = "ffmpeg"
    LLAMA_CPP = "llama_cpp"
    PIPER = "piper"
    WHISPER_CPP = "whisper_cpp"
    OPENVINO = "openvino"
    CUDA = "cuda"
    NONE = "none"


class ModelEntry(BaseModel):
    name: str
    capability: str                # script | tts | stt | image | face | video
    runtime: RuntimeKind = RuntimeKind.NONE
    source: str = ""               # where weights come from
    model_hash: str = ""
    license: str = ""
    # Minimum tested requirements the capability manager reads BEFORE
    # benchmarking (roadmap section 4: "read the model's tested requirements").
    min_ram_mb: int = 0
    min_vram_mb: int = 0            # 0 = runs on CPU / shared memory
    requires_cuda: bool = False
    # License gate. Only an explicit APPROVED entry may ship commercially.
    approval: ApprovalStatus = ApprovalStatus.UNREVIEWED
    approval_evidence: str = ""
    notes: str = ""

    @property
    def license_ok(self) -> bool:
        return self.approval == ApprovalStatus.APPROVED


def default_registry() -> list[ModelEntry]:
    """Candidate shortlist from roadmap sections 3 & 9.

    Everything ships UNREVIEWED by default. FFmpeg editing needs no model, so
    the render pipeline does not depend on any entry here being approved.
    """
    return [
        ModelEntry(
            name="Qwen2.5-0.5B-Instruct (GGUF, quantized)",
            capability="script", runtime=RuntimeKind.LLAMA_CPP,
            source="https://github.com/QwenLM/Qwen2.5",
            min_ram_mb=2048,
            license="Check exact model card + quantized redistribution source",
            approval=ApprovalStatus.UNREVIEWED,
        ),
        ModelEntry(
            name="Qwen2.5-1.5B-Instruct (GGUF, quantized)",
            capability="script", runtime=RuntimeKind.LLAMA_CPP,
            source="https://github.com/QwenLM/Qwen2.5",
            min_ram_mb=4096,
            license="Check exact model card + quantized redistribution source",
            approval=ApprovalStatus.UNREVIEWED,
        ),
        ModelEntry(
            name="Piper (voice TBD)",
            capability="tts", runtime=RuntimeKind.PIPER,
            source="https://github.com/OHF-Voice/piper1-gpl",
            min_ram_mb=1024,
            license="Engine GPL-3.0; inspect each voice's terms before bundling",
            approval=ApprovalStatus.UNREVIEWED,
        ),
        ModelEntry(
            name="whisper.cpp (small)",
            capability="stt", runtime=RuntimeKind.WHISPER_CPP,
            source="https://github.com/ggml-org/whisper.cpp",
            min_ram_mb=2048,
            license="Project MIT; review model assets separately",
            approval=ApprovalStatus.UNREVIEWED,
        ),
        ModelEntry(
            name="SadTalker / Wav2Lip (candidate)",
            capability="face", runtime=RuntimeKind.CUDA,
            source="https://github.com/OpenTalker/SadTalker",
            min_ram_mb=8192, min_vram_mb=6144, requires_cuda=True,
            license="Do not ship until code/weights/deps/use cleared",
            approval=ApprovalStatus.BLOCKED,
            approval_evidence="Not cleared for commercial use.",
        ),
    ]
