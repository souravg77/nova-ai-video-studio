"""Offline network policy (roadmap section 5 security layer).

Normal operation makes no network calls. Model downloads are the only path
permitted to reach the network, and only when explicitly enabled. This module
provides a guard used to assert that policy around sensitive operations.
"""
from __future__ import annotations

from dataclasses import dataclass


class NetworkPolicyError(RuntimeError):
    pass


@dataclass
class NetworkPolicy:
    offline_mode: bool = True
    allow_model_downloads: bool = False

    def guard_network(self, purpose: str) -> None:
        """Raise unless the network is permitted for `purpose`.

        Only 'model_download' is ever allowed, and only when both offline_mode
        is lifted and allow_model_downloads is set.
        """
        if purpose == "model_download":
            if self.allow_model_downloads and not self.offline_mode:
                return
            raise NetworkPolicyError(
                "Model download requested but model-download mode is not "
                "enabled. Enable it explicitly; the app stays offline by "
                "default.")
        raise NetworkPolicyError(
            f"Network access for '{purpose}' is not permitted. The app runs "
            f"fully offline during normal operation.")

    def enter_download_mode(self) -> "NetworkPolicy":
        return NetworkPolicy(offline_mode=False, allow_model_downloads=True)
