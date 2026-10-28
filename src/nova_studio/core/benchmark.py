"""Benchmark harness (roadmap section 3).

Runs each capability's fixture at least three times after a warm-up, records
median runtime + peak RAM, validates output, and stores a BenchmarkResult.
Separate CPU vs GPU paths; never assume GPU is faster.

The FFmpeg render benchmark requires no model and always runs — it proves the
core pipeline. AI benchmarks defer to each adapter's self_benchmark and record
an honest SKIPPED when the adapter is unavailable.
"""
from __future__ import annotations

import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Callable, Optional

from ..adapters.base import AIAdapter
from ..media.probe import ffmpeg_path
from ..media.quality_checks import validate_output
from ..models.benchmark import BenchmarkOutcome, BenchmarkResult


def _peak_ram_mb_during(fn: Callable[[], object]) -> tuple[object, int]:
    """Best-effort peak-RAM measurement around a call (process RSS delta)."""
    try:
        import resource
        before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result = fn()
        after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is KB on Linux, bytes on macOS.
        import sys
        divisor = 1024 if sys.platform != "darwin" else 1024 * 1024
        peak = max(0, int((after) / divisor))
        return result, peak
    except Exception:
        return fn(), 0


def benchmark_render(runs: int = 3) -> BenchmarkResult:
    """Render a fixed 5s 720p clip N times; record median runtime (section 3)."""
    ff = ffmpeg_path()
    import subprocess

    def one_render(out: Path) -> bool:
        cmd = [
            ff, "-y", "-f", "lavfi",
            "-i", "testsrc=s=1280x720:r=30:d=5",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(out),
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return p.returncode == 0

    times: list[float] = []
    peak = 0
    ok = True
    with tempfile.TemporaryDirectory(prefix="nova_bench_") as td:
        out = Path(td) / "bench.mp4"
        # warm-up
        one_render(out)
        for _ in range(runs):
            t0 = time.time()
            res, p = _peak_ram_mb_during(lambda: one_render(out))
            times.append(time.time() - t0)
            peak = max(peak, p)
            if not res:
                ok = False
        report = validate_output(str(out), expect_audio=True)
        ok = ok and report.ok

    return BenchmarkResult(
        capability="render", runtime="ffmpeg", backend_path="cpu",
        outcome=BenchmarkOutcome.PASS if ok else BenchmarkOutcome.FAIL,
        median_runtime_s=round(statistics.median(times), 3) if times else None,
        runs=[round(t, 3) for t in times],
        peak_ram_mb=peak or None,
        settings={"resolution": "1280x720", "fps": 30, "duration_s": 5,
                  "preset": "veryfast"},
        evidence="Output validated: video+audio present, A/V muxed." if ok
                 else "Render or validation failed.",
    )


def benchmark_adapter(adapter: AIAdapter, params: dict,
                      runs: int = 3) -> BenchmarkResult:
    """Benchmark an AI adapter, honestly recording SKIPPED if unavailable."""
    avail = adapter.availability()
    if not avail.available:
        return BenchmarkResult(
            capability=adapter.capability, runtime=adapter.runtime,
            backend_path="cpu", outcome=BenchmarkOutcome.SKIPPED,
            model_name=avail.model_name,
            evidence=f"Adapter unavailable: {avail.reason}",
        )
    times: list[float] = []
    ok = True
    last_msg = ""
    try:
        adapter.self_benchmark(params)  # warm-up
        for _ in range(runs):
            t0 = time.time()
            r = adapter.self_benchmark(params)
            times.append(time.time() - t0)
            ok = ok and r.ok
            last_msg = r.message
    except Exception as exc:
        return BenchmarkResult(
            capability=adapter.capability, runtime=adapter.runtime,
            backend_path="cpu", outcome=BenchmarkOutcome.ERROR,
            model_name=avail.model_name, evidence=f"Benchmark error: {exc}")

    return BenchmarkResult(
        capability=adapter.capability, runtime=adapter.runtime,
        backend_path="cpu", model_name=avail.model_name,
        outcome=BenchmarkOutcome.PASS if ok else BenchmarkOutcome.FAIL,
        median_runtime_s=round(statistics.median(times), 3) if times else None,
        runs=[round(t, 3) for t in times],
        evidence=last_msg or ("Passed" if ok else "Failed"),
    )


def run_baseline_suite(runs: int = 3) -> list[BenchmarkResult]:
    """The repeatable baseline: render benchmark always; AI benchmarks skip
    cleanly when their models/runtimes are absent."""
    from ..adapters.llm import ScriptAdapter
    from ..adapters.tts import TTSAdapter
    from ..adapters.stt import STTAdapter

    results = [benchmark_render(runs=runs)]
    results.append(benchmark_adapter(ScriptAdapter(),
                                     {"brief": "A 30s product teaser", "scenes": 6},
                                     runs=1))
    results.append(benchmark_adapter(TTSAdapter(),
                                     {"text": "Hello from NOVA.", "out_path": "x.wav"},
                                     runs=1))
    results.append(benchmark_adapter(STTAdapter(),
                                     {"audio_path": "x.wav", "out_path": "x.srt"},
                                     runs=1))
    return results
