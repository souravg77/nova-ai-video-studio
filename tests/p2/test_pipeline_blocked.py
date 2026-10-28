"""Pipeline reports the SPECIFIC blocker, never simulates success."""
from pathlib import Path

from nova_studio.core.capability import CapabilityManager
from nova_studio.core.pipeline import AutoVideoPipeline
from nova_studio.models.hardware_report import HardwareReport
from nova_studio.models.registry import default_registry


def _cap(installed):
    report = HardwareReport(cpu_name="x", physical_ram_mb=32000,
                            backends_available=["ffmpeg"])
    return CapabilityManager(report, registry=default_registry(),
                             installed_capabilities=installed)


def test_blocks_at_script_when_no_model(tmp_path):
    cap = _cap(installed=set())  # nothing installed
    pipe = AutoVideoPipeline(cap)
    result = pipe.run({"brief": "A teaser", "scenes": 3,
                       "work_dir": str(tmp_path / "w"),
                       "output_path": str(tmp_path / "out.mp4")})
    assert result.ok is False
    assert result.blocked_stage == "script"
    assert "script model" in result.blocker.lower()
    # No output file fabricated.
    assert not Path(tmp_path / "out.mp4").exists()
    # Must offer a fallback.
    assert result.suggested_fallback


def test_blocks_at_tts_when_script_ok_but_no_voice(tmp_path, stub_llama,
                                                   fake_gguf):
    from nova_studio.adapters.llm import ScriptAdapter
    from nova_studio.adapters.tts import TTSAdapter
    # script installed, tts not.
    cap = _cap(installed={"script"})
    pipe = AutoVideoPipeline(
        cap,
        script_adapter=ScriptAdapter(model_path=str(fake_gguf)),
        tts_adapter=TTSAdapter(voice_path=None))
    result = pipe.run({"brief": "A teaser", "scenes": 2,
                       "work_dir": str(tmp_path / "w"),
                       "output_path": str(tmp_path / "out.mp4")})
    assert result.ok is False
    assert result.blocked_stage == "tts"
    # Stage 1 (script) must have succeeded first.
    script_stage = next(s for s in result.stages if s.name == "script")
    assert script_stage.ok is True
    assert not Path(tmp_path / "out.mp4").exists()
