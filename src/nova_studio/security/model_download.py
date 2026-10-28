"""Consented model download (P2).

Downloads are NEVER automatic. A download requires:
  1. an explicit consent flag from the user, and
  2. a storage preflight that confirms enough free space.

This module only *describes* and *gates* downloads; it performs the actual
fetch only when consent is given and space is available. The default NOVA
runtime stays fully offline.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.preflight import check_model_download_space
from .offline_mode import NetworkPolicy, NetworkPolicyError


# Recommended starting model for a CPU-only Intel-iGPU PC (roadmap + user).
RECOMMENDED_SCRIPT_MODEL = {
    "name": "Qwen2.5-1.5B-Instruct-GGUF (Q4_K_M)",
    "capability": "script",
    "approx_size_gb": 1.1,
    "license": "Apache-2.0 (verify exact GGUF repo + redistribution)",
    "runtime": "llama.cpp",
    "fallback": "Qwen2.5-0.5B-Instruct-GGUF (Q4_K_M) if memory/speed is tight",
    "notes": "CPU inference first; test acceleration separately.",
}


@dataclass
class DownloadPlan:
    name: str
    url: str
    dest: str
    approx_size_gb: float
    license: str


@dataclass
class DownloadDecision:
    allowed: bool
    reason: str
    plan: Optional[DownloadPlan] = None


def plan_download(name: str, url: str, dest_dir: str | Path,
                  approx_size_gb: float, license: str,
                  workspace: str | Path,
                  consented: bool) -> DownloadDecision:
    """Decide whether a download may proceed. Never fetches here."""
    if not consented:
        return DownloadDecision(
            False,
            "Model download requires explicit consent. NOVA never downloads "
            "model weights automatically.")
    pf = check_model_download_space(Path(workspace), approx_size_gb)
    if not pf.ok:
        return DownloadDecision(False, pf.message)
    dest = Path(dest_dir) / Path(url).name
    return DownloadDecision(
        True, "Consent given and space available.",
        DownloadPlan(name=name, url=url, dest=str(dest),
                     approx_size_gb=approx_size_gb, license=license))


def execute_download(decision: DownloadDecision,
                     policy: NetworkPolicy) -> Path:
    """Perform a consented download. Raises if not allowed or offline.

    Uses urllib only inside this explicitly-permitted path; the rest of the app
    never touches the network.
    """
    if not decision.allowed or decision.plan is None:
        raise NetworkPolicyError(decision.reason)
    # This guard raises unless the policy is in download mode.
    policy.guard_network("model_download")

    import urllib.request
    plan = decision.plan
    dest = Path(plan.dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(plan.url) as resp, tmp.open("wb") as f:  # noqa: S310
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(dest)
    return dest
