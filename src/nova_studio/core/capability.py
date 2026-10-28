"""Capability manager (roadmap sections 2, 4, 8).

Turns a measured HardwareReport + benchmark results + model registry into:
  * a detected hardware tier (0..4),
  * an honest verdict for any requested generation job, and
  * the highest profile whose required tests actually passed.

Core rule: capability is NEVER inferred from a GPU name or advertised shared
memory. It comes from measured RAM/VRAM, confirmed runtimes, passed benchmarks
and an approved license.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional

from ..models.benchmark import BenchmarkResult
from ..models.hardware_report import HardwareReport
from ..models.job import GenerationState, JobKind
from ..models.registry import ApprovalStatus, ModelEntry


class Profile(str, Enum):
    AUTO = "auto"
    BALANCED = "balanced"
    HIGH = "high"
    MAXIMUM = "maximum"


class Tier(IntEnum):
    EDITING = 0       # FFmpeg + disk: import/edit/caption/mix/export
    CPU_AI = 1        # small model passes CPU/RAM benchmark
    INTEL_ACCEL = 2   # OpenVINO/Intel device confirmed + passes tests
    NVIDIA_GPU = 3    # compatible CUDA GPU + enough measured VRAM
    HIGH_VRAM = 4     # 24 GB+ dedicated VRAM + models pass benchmark


HIGH_VRAM_FLOOR_MB = 24 * 1024


@dataclass
class Verdict:
    """Honest answer for a requested generation capability (section 8)."""
    state: GenerationState
    blocker: str = ""
    suggested_fallback: str = ""

    @property
    def can_attempt(self) -> bool:
        return self.state in (
            GenerationState.SUPPORTED,
            GenerationState.SUPPORTED_WITH_LIMITS,
            GenerationState.EXPERIMENTAL,
        )


class CapabilityManager:
    def __init__(
        self,
        report: HardwareReport,
        benchmarks: Optional[list[BenchmarkResult]] = None,
        registry: Optional[list[ModelEntry]] = None,
        installed_capabilities: Optional[set[str]] = None,
    ) -> None:
        self.report = report
        self.benchmarks = benchmarks or []
        self.registry = registry or []
        # Capabilities whose model/voice files are actually present on disk
        # (e.g. {"script", "tts"}). None means "don't check installation here"
        # — used by callers that only reason about hardware/license/benchmark.
        self.installed_capabilities = installed_capabilities

    # ------------------------------------------------------------------
    # Benchmark lookup
    # ------------------------------------------------------------------
    def _passed(self, capability: str, backend_path: Optional[str] = None) -> bool:
        for b in self.benchmarks:
            if b.capability == capability and b.passed:
                if backend_path is None or b.backend_path == backend_path:
                    return True
        return False

    # ------------------------------------------------------------------
    # Tier detection (roadmap section 4)
    # ------------------------------------------------------------------
    def detected_tier(self) -> Tier:
        tier = Tier.EDITING  # FFmpeg availability checked by renderer separately

        if self._passed("script", backend_path="cpu") or self._passed("tts", "cpu"):
            tier = Tier.CPU_AI

        intel_ok = ("openvino-cpu" in self.report.backends_available
                    and self._passed("script"))
        if intel_ok:
            tier = max(tier, Tier.INTEL_ACCEL)

        if self.report.has_nvidia_cuda:
            gpu = self.report.best_gpu
            vram = gpu.dedicated_vram_mb if gpu else 0
            if vram and vram > 0:
                tier = max(tier, Tier.NVIDIA_GPU)
                if vram >= HIGH_VRAM_FLOOR_MB:
                    tier = max(tier, Tier.HIGH_VRAM)
        return tier

    # ------------------------------------------------------------------
    # Profile selection (roadmap section 2 — Auto picks highest PASSED)
    # ------------------------------------------------------------------
    def select_profile(self, requested: Profile) -> tuple[Profile, str]:
        """Return the effective profile + a reason string.

        Editing/export is always available at every profile. AI generation is
        gated. Auto resolves to the highest profile whose required tests pass.
        """
        tier = self.detected_tier()

        if requested == Profile.AUTO:
            if tier >= Tier.NVIDIA_GPU:
                return Profile.HIGH, (
                    f"Auto: GPU tier {int(tier)} detected; editing/export at "
                    f"1080p plus AI modules that passed benchmark.")
            if tier >= Tier.CPU_AI:
                return Profile.BALANCED, (
                    "Auto: CPU AI benchmarks passed; script/TTS plus full "
                    "editing/export. No reliable GPU generation path.")
            return Profile.BALANCED, (
                "Auto: CPU-first. Editing/export supported; AI generation "
                "not yet benchmarked, so it stays gated.")

        # Explicit profiles keep editing/export; AI capability still gated.
        reason = {
            Profile.BALANCED: "Balanced: light script model, lightweight TTS, "
                              "720p preview, efficient FFmpeg presets.",
            Profile.HIGH: "High: editing + more effects + 1080p export. AI "
                          "video modules only if their benchmark passed.",
            Profile.MAXIMUM: "Maximum: highest tested editing/export settings. "
                             "AI generation blocked unless benchmark passes.",
        }.get(requested, "")
        return requested, reason

    # ------------------------------------------------------------------
    # Per-capability honest verdict (roadmap section 8)
    # ------------------------------------------------------------------
    def _registry_for(self, capability: str) -> Optional[ModelEntry]:
        entries = [m for m in self.registry if m.capability == capability]
        # Prefer an approved + lightest entry.
        entries.sort(key=lambda m: (m.approval != ApprovalStatus.APPROVED,
                                    m.min_vram_mb, m.min_ram_mb))
        return entries[0] if entries else None

    def verdict_for(self, kind: JobKind) -> Verdict:
        # Editing/export is always supported — no model required.
        if kind == JobKind.RENDER:
            return Verdict(GenerationState.SUPPORTED)

        cap_map = {
            JobKind.SCRIPT: "script", JobKind.TTS: "tts", JobKind.STT: "stt",
            JobKind.IMAGE_GEN: "image", JobKind.FACE_ANIM: "face",
            JobKind.VIDEO_GEN: "video",
        }
        capability = cap_map.get(kind)
        if capability is None:
            return Verdict(GenerationState.SUPPORTED)

        # Installation check: if the caller told us which capabilities have
        # their weights on disk, a missing file is an immediate, precise
        # blocker — reported BEFORE license/benchmark so the user sees the real
        # reason ("no model installed") rather than a vaguer downstream failure.
        if (self.installed_capabilities is not None
                and capability in ("script", "tts", "stt")
                and capability not in self.installed_capabilities):
            friendly = {"script": "script model (Qwen2.5 GGUF)",
                        "tts": "narration voice (Piper)",
                        "stt": "transcription model (whisper.cpp)"}[capability]
            return Verdict(
                GenerationState.UNSUPPORTED_ON_THIS_PC,
                blocker=f"No {friendly} is installed. Add the model files to "
                        f"the models/{capability} directory (nothing is "
                        f"downloaded automatically).",
                suggested_fallback=self._fallback_for(capability),
            )

        entry = self._registry_for(capability)
        if entry is None:
            no_model_blocker = {
                "video": "Photorealistic AI text/image-to-video is not "
                         "available on this PC. The installed Intel integrated "
                         "GPU and current benchmark do not meet any approved "
                         "model's tested requirements. No AI video clip was "
                         "generated.",
                "face": "Talking-head/face animation is not available on this "
                        "PC. No approved model has passed the current hardware "
                        "benchmark. No avatar clip was generated.",
            }.get(capability, f"No model registered for '{capability}' on this PC.")
            return Verdict(
                GenerationState.UNSUPPORTED_ON_THIS_PC,
                blocker=no_model_blocker,
                suggested_fallback=self._fallback_for(capability),
            )

        # License gate first (section 9).
        if entry.approval == ApprovalStatus.BLOCKED:
            return Verdict(
                GenerationState.BLOCKED_BY_LICENSE,
                blocker=f"'{entry.name}' is not approved for commercial use. "
                        f"{entry.approval_evidence}",
                suggested_fallback=self._fallback_for(capability),
            )
        if entry.approval != ApprovalStatus.APPROVED:
            return Verdict(
                GenerationState.EXPERIMENTAL,
                blocker=f"'{entry.name}' license is unreviewed; treat output "
                        f"as experimental and do not ship commercially.",
                suggested_fallback=self._fallback_for(capability),
            )

        # Hardware requirement check — measured, not advertised.
        if entry.requires_cuda and not self.report.has_nvidia_cuda:
            return Verdict(
                GenerationState.UNSUPPORTED_ON_THIS_PC,
                blocker=f"'{entry.name}' requires a confirmed NVIDIA CUDA GPU; "
                        f"none is active on this PC.",
                suggested_fallback=self._fallback_for(capability),
            )
        if entry.min_vram_mb > 0:
            vram = self.report.max_dedicated_vram_mb
            if vram < entry.min_vram_mb:
                return Verdict(
                    GenerationState.UNSUPPORTED_ON_THIS_PC,
                    blocker=f"'{entry.name}' needs {entry.min_vram_mb} MB "
                            f"dedicated VRAM; measured {vram} MB. Intel shared "
                            f"memory does not count as VRAM.",
                    suggested_fallback=self._fallback_for(capability),
                )
        if entry.min_ram_mb > self.report.physical_ram_mb:
            return Verdict(
                GenerationState.UNSUPPORTED_ON_THIS_PC,
                blocker=f"'{entry.name}' needs {entry.min_ram_mb} MB RAM; "
                        f"installed {self.report.physical_ram_mb} MB.",
                suggested_fallback=self._fallback_for(capability),
            )

        # Benchmark gate — the model must actually have passed on this machine.
        if not self._passed(capability):
            return Verdict(
                GenerationState.UNSUPPORTED_ON_THIS_PC,
                blocker=f"'{entry.name}' has not passed the current hardware "
                        f"benchmark on this PC. No output will be promised "
                        f"until it does.",
                suggested_fallback=self._fallback_for(capability),
            )

        return Verdict(GenerationState.SUPPORTED)

    @staticmethod
    def _fallback_for(capability: str) -> str:
        if capability in ("video", "face"):
            return ("Export using imported footage, create a motion-animated "
                    "still, or test a shorter low-resolution clip.")
        if capability == "image":
            return "Import an existing image, or retry at lower resolution."
        if capability == "script":
            return "Write the script manually, or try a smaller model."
        if capability == "tts":
            return "Import a recorded narration track instead."
        if capability == "stt":
            return "Import an existing subtitle/caption file."
        return "Use imported assets instead of generation."
