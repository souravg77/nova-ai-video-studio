"""Offline network policy (roadmap section 5 security layer).

Normal operation makes no network calls. Two paths may reach the network, each
only when the user explicitly enables it: model downloads, and opt-in cloud
generation (e.g. Gemini Omni Flash with the user's own API key). This module
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
    # Opt-in cloud generation. Off by default; NOVA never switches from local
    # to cloud processing on its own.
    allow_cloud_generation: bool = False

    def guard_network(self, purpose: str) -> None:
        """Raise unless the network is permitted for `purpose`.

        'model_download' is allowed only when offline_mode is lifted and
        allow_model_downloads is set; 'cloud_generation' only when offline_mode
        is lifted and allow_cloud_generation is set. Nothing else, ever.
        """
        if purpose == "model_download":
            if self.allow_model_downloads and not self.offline_mode:
                return
            raise NetworkPolicyError(
                "Model download requested but model-download mode is not "
                "enabled. Enable it explicitly; the app stays offline by "
                "default.")
        if purpose == "cloud_generation":
            if self.allow_cloud_generation and not self.offline_mode:
                return
            raise NetworkPolicyError(
                "Cloud generation is switched off. Turn it on in Settings to "
                "send this shot to the cloud provider; NOVA never does so on "
                "its own.")
        raise NetworkPolicyError(
            f"Network access for '{purpose}' is not permitted. The app runs "
            f"fully offline during normal operation.")

    def enter_download_mode(self) -> "NetworkPolicy":
        return NetworkPolicy(offline_mode=False, allow_model_downloads=True,
                             allow_cloud_generation=self.allow_cloud_generation)

    def enable_cloud_generation(self) -> "NetworkPolicy":
        return NetworkPolicy(offline_mode=False,
                             allow_model_downloads=self.allow_model_downloads,
                             allow_cloud_generation=True)
