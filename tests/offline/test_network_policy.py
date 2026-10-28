"""Network policy: offline by default; downloads only when explicitly enabled."""
import pytest

from nova_studio.security.offline_mode import NetworkPolicy, NetworkPolicyError


def test_default_blocks_all_network():
    p = NetworkPolicy()
    with pytest.raises(NetworkPolicyError):
        p.guard_network("telemetry")
    with pytest.raises(NetworkPolicyError):
        p.guard_network("model_download")


def test_download_mode_permits_only_downloads():
    p = NetworkPolicy().enter_download_mode()
    p.guard_network("model_download")  # no raise
    with pytest.raises(NetworkPolicyError):
        p.guard_network("telemetry")
