"""Model resolver discovers installed weights without network."""
from pathlib import Path

from nova_studio.core.model_resolver import ModelResolver


def test_resolver_empty(tmp_path):
    r = ModelResolver(tmp_path / "models")
    r.ensure_dirs()
    assert r.resolve_script_model() is None
    assert r.resolve_tts_voice() is None
    assert r.list_script_models() == []


def test_resolver_finds_and_prefers_15b(tmp_path):
    r = ModelResolver(tmp_path / "models")
    r.ensure_dirs()
    (r.models_dir / "script" / "Qwen2.5-0.5B-Q4.gguf").write_bytes(b"a" * 100)
    (r.models_dir / "script" / "Qwen2.5-1.5B-Q4.gguf").write_bytes(b"b" * 200)
    resolved = r.resolve_script_model()
    assert resolved is not None
    # 1.5B preferred over 0.5B.
    assert "1.5B" in resolved.name
    assert resolved.sha256 and resolved.size_mb >= 0


def test_resolver_falls_back_to_05b(tmp_path):
    r = ModelResolver(tmp_path / "models")
    r.ensure_dirs()
    (r.models_dir / "script" / "Qwen2.5-0.5B-Q4.gguf").write_bytes(b"a" * 100)
    resolved = r.resolve_script_model()
    assert "0.5B" in resolved.name


def test_resolver_tts_voice(tmp_path):
    r = ModelResolver(tmp_path / "models")
    r.ensure_dirs()
    (r.models_dir / "tts" / "v.onnx").write_bytes(b"x")
    (r.models_dir / "tts" / "v.onnx.json").write_text("{}")
    v = r.resolve_tts_voice()
    assert v is not None and v.name == "v.onnx"
