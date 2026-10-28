"""Capability manager: honest verdicts + profile gating (sections 2, 4, 8)."""
from nova_studio.core.capability import CapabilityManager, Profile, Tier
from nova_studio.models.benchmark import BenchmarkOutcome, BenchmarkResult
from nova_studio.models.hardware_report import GpuInfo, GpuVendor, HardwareReport
from nova_studio.models.job import GenerationState, JobKind
from nova_studio.models.registry import (ApprovalStatus, ModelEntry,
                                         RuntimeKind, default_registry)


def _igpu_report():
    return HardwareReport(
        cpu_name="Core i5-12xxx", physical_cores=10, logical_cores=12,
        physical_ram_mb=32000, available_ram_mb=16000,
        gpus=[GpuInfo(name="Intel Iris Xe", vendor=GpuVendor.INTEL)],
        disk_free_mb=200000, disk_total_mb=1_000_000,
        backends_available=["ffmpeg"])


def test_render_always_supported():
    mgr = CapabilityManager(_igpu_report(), registry=default_registry())
    assert mgr.verdict_for(JobKind.RENDER).state == GenerationState.SUPPORTED


def test_video_gen_unsupported_on_igpu():
    mgr = CapabilityManager(_igpu_report(), registry=default_registry())
    v = mgr.verdict_for(JobKind.VIDEO_GEN)
    assert v.state == GenerationState.UNSUPPORTED_ON_THIS_PC
    assert not v.can_attempt
    assert v.suggested_fallback  # must offer a fallback


def test_face_blocked_by_license():
    # SadTalker entry ships BLOCKED in the default registry.
    mgr = CapabilityManager(_igpu_report(), registry=default_registry())
    v = mgr.verdict_for(JobKind.FACE_ANIM)
    # On an iGPU it's unsupported by hardware OR blocked by license; either way
    # it must not be attemptable.
    assert v.state in (GenerationState.BLOCKED_BY_LICENSE,
                       GenerationState.UNSUPPORTED_ON_THIS_PC)
    assert not v.can_attempt


def test_auto_profile_is_balanced_without_benchmarks():
    mgr = CapabilityManager(_igpu_report(), registry=default_registry())
    eff, reason = mgr.select_profile(Profile.AUTO)
    assert eff == Profile.BALANCED
    assert mgr.detected_tier() == Tier.EDITING


def test_script_supported_only_after_benchmark_and_approval():
    report = _igpu_report()
    registry = [ModelEntry(
        name="Qwen tiny", capability="script", runtime=RuntimeKind.LLAMA_CPP,
        min_ram_mb=2048, approval=ApprovalStatus.APPROVED)]
    # Without a passing benchmark -> unsupported.
    mgr = CapabilityManager(report, benchmarks=[], registry=registry)
    assert mgr.verdict_for(JobKind.SCRIPT).state == GenerationState.UNSUPPORTED_ON_THIS_PC
    # With a passing benchmark -> supported.
    bench = [BenchmarkResult(capability="script", backend_path="cpu",
                             outcome=BenchmarkOutcome.PASS)]
    mgr2 = CapabilityManager(report, benchmarks=bench, registry=registry)
    assert mgr2.verdict_for(JobKind.SCRIPT).state == GenerationState.SUPPORTED


def test_unreviewed_license_is_experimental():
    report = _igpu_report()
    registry = [ModelEntry(name="X", capability="script",
                           runtime=RuntimeKind.LLAMA_CPP, min_ram_mb=1024,
                           approval=ApprovalStatus.UNREVIEWED)]
    mgr = CapabilityManager(report, registry=registry)
    assert mgr.verdict_for(JobKind.SCRIPT).state == GenerationState.EXPERIMENTAL


def test_high_vram_tier_requires_confirmed_24gb():
    report = HardwareReport(
        physical_ram_mb=64000,
        gpus=[GpuInfo(name="RTX 4090", vendor=GpuVendor.NVIDIA,
                      dedicated_vram_mb=24576, runtime_confirmed=True)],
        backends_available=["ffmpeg", "torch"])
    mgr = CapabilityManager(report, registry=default_registry())
    assert mgr.detected_tier() >= Tier.NVIDIA_GPU
    assert mgr.detected_tier() == Tier.HIGH_VRAM
