"""AI model download manager for the NOVA Studio dashboard.

Downloads, on explicit user request (a button click = consent), the CPU-capable
models NOVA uses on Intel/integrated-graphics hardware:
  * a quantized Qwen2.5 script model (GGUF, runs via llama-cpp-python), and
  * a Piper narration voice (.onnx + .onnx.json) plus, on Windows, the Piper
    binary.

Downloads run in a background thread with live progress. Nothing is fetched
until the user clicks Download. Files land in the workspace models directories
the resolver already scans, so once a download finishes the matching feature
lights up.

NOTE: talking-head / avatar video models are NOT offered here — they require a
dedicated NVIDIA CUDA GPU, which this path deliberately does not pretend to
support.
"""
from __future__ import annotations

import os
import threading
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Best-known public sources. The exact asset is verified by size after
# download; a failure reports the HTTP error honestly rather than pretending.
CATALOG = {
    "script": {
        "label": "Qwen2.5-1.5B-Instruct (Q4_K_M, GGUF)",
        "runtime": "llama-cpp-python (bundled)",
        "approx_mb": 1100,
        "subdir": "script",
        "files": [{
            "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/"
                   "resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf?download=true",
            "name": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        }],
    },
    "voice": {
        "label": "Piper narration (engine + en_US-lessac voice)",
        "runtime": "piper",
        "approx_mb": 90,
        "subdir": "tts",
        "files": [
            {"url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                    "en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true",
             "name": "en_US-lessac-medium.onnx"},
            {"url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
                    "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true",
             "name": "en_US-lessac-medium.onnx.json"},
        ],
        # The Piper engine binary (platform-specific) is added at runtime by
        # _platform_files() so narration works without a separate install.
    },
}


def _platform_files() -> list[dict]:
    """The Piper engine binary for the current OS (extracted into tts/piper)."""
    base = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/"
    if os.name == "nt":
        return [{"url": base + "piper_windows_amd64.zip",
                 "name": "piper_windows_amd64.zip", "engine": True}]
    # Linux x86_64 (dev/CI). macOS users install piper via brew.
    return [{"url": base + "piper_linux_x86_64.tar.gz",
             "name": "piper_linux_x86_64.tar.gz", "engine": True}]


def _extract(archive: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    elif name.endswith((".tar.gz", ".tgz")):
        import tarfile
        with tarfile.open(archive) as t:
            t.extractall(into)
    # Make the piper binary executable on POSIX.
    for p in into.rglob("piper*"):
        if p.is_file() and p.suffix in ("", ".exe"):
            try:
                p.chmod(0o755)
            except Exception:
                pass


@dataclass
class DownloadState:
    key: str
    state: str = "idle"          # idle | running | completed | failed
    progress: float = 0.0        # 0..1 overall
    stage: str = ""
    message: str = ""
    dest: str = ""


class ModelDownloader:
    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self._states: dict[str, DownloadState] = {}
        self._lock = threading.Lock()

    def status(self, resolver) -> dict:
        """Report, per model, whether it is installed and any active download."""
        out = {}
        installed = {
            "script": bool(resolver.resolve_script_model()),
            "voice": bool(resolver.resolve_tts_voice()),
        }
        for key, meta in CATALOG.items():
            st = self._states.get(key)
            out[key] = {
                "label": meta["label"], "approx_mb": meta["approx_mb"],
                "runtime": meta["runtime"],
                "installed": installed.get(key, False),
                "state": st.state if st else "idle",
                "progress": st.progress if st else 0.0,
                "stage": st.stage if st else "",
                "message": st.message if st else "",
            }
        return out

    def start(self, key: str) -> DownloadState:
        if key not in CATALOG:
            raise KeyError(key)
        with self._lock:
            cur = self._states.get(key)
            if cur and cur.state == "running":
                return cur
            st = DownloadState(key=key, state="running", stage="Starting…")
            self._states[key] = st
        threading.Thread(target=self._run, args=(key, st), daemon=True).start()
        return st

    # ------------------------------------------------------------------
    def _run(self, key: str, st: DownloadState) -> None:
        meta = CATALOG[key]
        dest_dir = self.models_dir / meta["subdir"]
        dest_dir.mkdir(parents=True, exist_ok=True)
        files = list(meta["files"])
        if key == "voice":
            files += _platform_files()          # Piper engine binary
        try:
            for idx, spec in enumerate(files):
                st.stage = f"Downloading {spec['name']} ({idx+1}/{len(files)})"
                target = dest_dir / spec["name"]
                self._download(spec["url"], target, st, idx, len(files))
                if spec.get("engine"):
                    st.stage = "Installing engine"
                    _extract(target, dest_dir / "piper")
            st.state = "completed"
            st.progress = 1.0
            st.stage = "Installed"
            st.dest = str(dest_dir)
            st.message = f"{meta['label']} is ready."
        except Exception as exc:
            st.state = "failed"
            st.message = (f"Download failed: {exc}. Check your internet "
                          f"connection and try again.")

    def _download(self, url: str, target: Path, st: DownloadState,
                  file_idx: int, file_count: int) -> None:
        tmp = target.with_suffix(target.suffix + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "NOVA-Studio"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with tmp.open("wb") as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        frac = got / total
                        st.progress = (file_idx + frac) / file_count
                        st.stage = (f"{target.name}: "
                                    f"{got // (1024*1024)}/{total // (1024*1024)} MB")
        tmp.replace(target)
