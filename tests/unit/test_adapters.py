"""Adapters report honest unavailability and never fake success."""
from nova_studio.adapters.llm import ScriptAdapter, template_script
from nova_studio.adapters.tts import TTSAdapter
from nova_studio.adapters.stt import STTAdapter
from nova_studio.adapters.vision import ImageGenAdapter
from nova_studio.adapters.video_generation import VideoGenAdapter


def test_script_adapter_unavailable_without_model():
    a = ScriptAdapter(model_path=None)
    av = a.availability()
    assert av.available is False
    assert "llama-cpp-python" in av.reason or "GGUF" in av.reason
    # run() must return ok=False, not raise or fake a script.
    r = a.run({"brief": "x"})
    assert r.ok is False


def test_video_gen_never_fakes_output():
    a = VideoGenAdapter()
    r = a.run({})
    assert r.ok is False
    assert r.outputs == []
    assert "no" in r.message.lower() or "not" in r.message.lower()


def test_image_gen_experimental_disabled():
    a = ImageGenAdapter()
    assert a.availability().available is False
    assert a.run({}).ok is False


def test_template_script_is_labelled_non_ai():
    out = template_script("A teaser", n_scenes=4)
    assert out["source"] == "template"
    assert len(out["scenes"]) == 4


def test_tts_and_stt_unavailable_cleanly():
    assert TTSAdapter().availability().available is False
    assert STTAdapter().availability().available is False
