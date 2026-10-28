"""Full P2 pipeline success path with real output files (via shims).

Exercises the real code: Qwen output parsing -> per-scene Piper narration ->
FFmpeg render -> validation. The shims produce genuine JSON and WAV/MP4 files;
nothing in the pipeline's verification is bypassed.
"""
import pytest

from nova_studio.adapters.llm import ScriptAdapter
from nova_studio.adapters.tts import TTSAdapter
from nova_studio.core.capability import CapabilityManager
from nova_studio.core.pipeline import AutoVideoPipeline
from nova_studio.media.probe import probe
from nova_studio.models.hardware_report import HardwareReport
from nova_studio.models.registry import default_registry

pytestmark = pytest.mark.export  # needs ffmpeg


def _cap(installed):
    report = HardwareReport(cpu_name="x", physical_ram_mb=32000,
                            backends_available=["ffmpeg"])
    return CapabilityManager(report, registry=default_registry(),
                             installed_capabilities=installed)


def test_full_pipeline_produces_validated_video(
        tmp_path, stub_llama, fake_gguf, fake_piper_voice, fake_piper_cli,
        assets):
    cap = _cap(installed={"script", "tts"})
    pipe = AutoVideoPipeline(
        cap,
        script_adapter=ScriptAdapter(model_path=str(fake_gguf)),
        tts_adapter=TTSAdapter(voice_path=str(fake_piper_voice)))

    out = tmp_path / "auto.mp4"
    stages_seen = []
    result = pipe.run(
        {"brief": "A 3-scene teaser about coffee",
         "scenes": 3,
         "visuals": [str(assets["img"]), str(assets["clip"]), str(assets["img"])],
         "width": 640, "height": 360, "fps": 24, "preset": "ultrafast",
         "work_dir": str(tmp_path / "work"),
         "output_path": str(out)},
        progress=lambda p, m: stages_seen.append(m))

    assert result.ok, result.blocker
    assert out.exists()
    # Every stage completed and validated.
    names = {s.name: s.ok for s in result.stages}
    # Core stages must all pass; a subtitles stage (Phase 3) may also be
    # present and must pass when present.
    assert names.get("script") is True
    assert names.get("tts") is True
    assert names.get("render") is True
    assert all(ok for ok in names.values())
    # The output is a real, playable video with an audio (narration) track.
    info = probe(out)
    assert info.ok and info.has_video and info.has_audio
    assert info.duration_s and info.duration_s > 3  # 3 scenes, >=2s each


def test_pipeline_without_visuals_uses_captioned_slates(
        tmp_path, stub_llama, fake_gguf, fake_piper_voice, fake_piper_cli):
    cap = _cap(installed={"script", "tts"})
    pipe = AutoVideoPipeline(
        cap,
        script_adapter=ScriptAdapter(model_path=str(fake_gguf)),
        tts_adapter=TTSAdapter(voice_path=str(fake_piper_voice)))
    out = tmp_path / "noviz.mp4"
    result = pipe.run(
        {"brief": "No visuals provided", "scenes": 2, "visuals": [],
         "width": 640, "height": 360, "fps": 24, "preset": "ultrafast",
         "work_dir": str(tmp_path / "w"), "output_path": str(out)})
    assert result.ok, result.blocker
    assert out.exists()
