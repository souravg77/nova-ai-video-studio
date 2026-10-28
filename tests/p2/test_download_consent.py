"""Model downloads require explicit consent + space; never automatic."""
from nova_studio.security.model_download import plan_download, execute_download
from nova_studio.security.offline_mode import NetworkPolicy, NetworkPolicyError

import pytest


def test_no_consent_blocks(tmp_path):
    d = plan_download("m", "https://example/m.gguf", tmp_path, 1.0,
                      "Apache-2.0", workspace=tmp_path, consented=False)
    assert d.allowed is False
    assert "consent" in d.reason.lower()


def test_consent_but_no_space_blocks(tmp_path, monkeypatch):
    # Force the space check to report insufficient space.
    import nova_studio.security.model_download as md

    class _PF:
        ok = False
        message = "Only 1 GB free; needs 20 GB."
    monkeypatch.setattr(md, "check_model_download_space", lambda *a, **k: _PF())
    d = plan_download("m", "https://example/m.gguf", tmp_path, 1.0,
                      "Apache-2.0", workspace=tmp_path, consented=True)
    assert d.allowed is False


def test_execute_blocked_without_download_mode(tmp_path, monkeypatch):
    import nova_studio.security.model_download as md

    class _PF:
        ok = True
        message = "ok"
    monkeypatch.setattr(md, "check_model_download_space", lambda *a, **k: _PF())
    d = plan_download("m", "https://example/m.gguf", tmp_path, 1.0,
                      "Apache-2.0", workspace=tmp_path, consented=True)
    assert d.allowed is True
    # Default policy is offline; execution must refuse network.
    with pytest.raises(NetworkPolicyError):
        execute_download(d, NetworkPolicy())
