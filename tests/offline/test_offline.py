"""Offline guarantees (roadmap section 7, milestone 8).

The editing/export pipeline and all capability logic must work with no network.
We verify (a) config defaults to offline, and (b) importing the modules and
running the render + capability path performs no socket connections.
"""
import socket

import pytest

from nova_studio import config


def test_offline_by_default():
    cfg = config.AppConfig()
    assert cfg.offline_mode is True
    assert cfg.allow_model_downloads is False


def test_core_flow_makes_no_network_calls(app_config, assets, monkeypatch):
    """Block all outbound sockets, then run the core render flow."""
    real_socket = socket.socket

    class _Blocked(real_socket):  # type: ignore
        def connect(self, *a, **k):
            raise AssertionError("Network access attempted in offline flow!")
        def connect_ex(self, *a, **k):
            raise AssertionError("Network access attempted in offline flow!")

    monkeypatch.setattr(socket, "socket", _Blocked)

    import threading
    from nova_studio.core.studio import Studio
    from nova_studio.models.project import Scene
    from nova_studio.models.job import JobState

    s = Studio(app_config)
    try:
        p = s.new_project("OfflineTest")
        img = s.import_media(p, str(assets["img"]))
        p.target_width, p.target_height, p.target_fps = 640, 360, 24
        p.add_scene(Scene(title="A", visual_asset_id=img.id, duration_s=1,
                          motion_effect="kenburns"))
        s.save_project(p)
        done = threading.Event(); box = {}
        s.render_project(p, listener=lambda j: (box.__setitem__("j", j),
                                                done.set()) if j.state in (
            JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED) else None,
            preset="ultrafast")
        assert done.wait(timeout=90)
        assert box["j"].state == JobState.COMPLETED
    finally:
        s.shutdown()
