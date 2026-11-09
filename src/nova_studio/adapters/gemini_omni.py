"""Gemini Omni Flash video engine (opt-in cloud).

Model: ``gemini-omni-1.1-flash`` through the Gemini API Interactions endpoint,
with the user's own API key. Capabilities below are taken from Google's docs
(read 2026-11-09), not guessed:

* 3-10 s clips, 16:9 or 9:16, 360p/720p native (1080p and 4K are upscaled).
* Video and audio, including dialogue, are generated together. Only English
  has been evaluated by Google, so only English is declared.
* Reference images and first/last frames are supported. The docs give no
  maximum for image references, so NOVA declares the two its examples use.
* No request field sets the clip length; the requested duration is passed as
  prompt text and the real length is measured from the file.
* Every output carries Google's SynthID watermark.

Rules this adapter keeps:
* It never runs unless cloud generation is switched on AND a key is present.
  NOVA never falls back from local to cloud on its own.
* The key is sent only in the ``x-goog-api-key`` header, never in a URL, a
  log line, an error message or a project file.
* A take only counts if a real file arrives and FFprobe finds a video stream
  in it. Nothing is ever substituted.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Protocol

from ..performance.engines import (EngineCapabilities, EngineSpec, EngineStatus,
                                   IdentityPreservation, Role)
from ..security.offline_mode import NetworkPolicy, NetworkPolicyError

ENGINE_ID = "gemini-omni-flash"
MODEL = "gemini-omni-1.1-flash"
API_BASE = "https://generativelanguage.googleapis.com/v1beta"
ENV_KEY = "NOVA_GEMINI_API_KEY"

CAPABILITIES = EngineCapabilities(
    image_generation=False,
    video_generation=True,
    native_audio=True,
    speech_synthesis=False,
    lip_sync=False,
    emotion_control=False,            # prompt text only
    head_motion_control=False,
    multi_speaker_in_one_shot=False,  # not documented, so not claimed
    max_reference_images=2,
    identity_preservation=IdentityPreservation.REFERENCE_GUIDED,
    start_end_frames=True,
    min_duration_s=3.0,
    max_duration_s=10.0,
    aspect_ratios=("16:9", "9:16"),
    languages=("en",),
    produces_placeholders=False,
    is_cloud=True,
)
RESOLUTIONS = ("360p", "720p", "1080p", "4k")


class OmniError(RuntimeError):
    """The provider refused or failed the request. Message is key-free."""


class Transport(Protocol):
    def __call__(self, method: str, url: str, headers: dict[str, str],
                 body: Optional[bytes], timeout: float) -> tuple[int, bytes]: ...


def urllib_transport(method: str, url: str, headers: dict[str, str],
                     body: Optional[bytes], timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@dataclass
class ImageInput:
    path: Path
    role: str = "reference"   # reference | first_frame | last_frame

    def mime(self) -> str:
        ext = self.path.suffix.lower()
        if ext == ".png":
            return "image/png"
        if ext in (".jpg", ".jpeg"):
            return "image/jpeg"
        raise OmniError(f"{self.path.name}: only PNG and JPEG images are supported.")


@dataclass
class OmniRequest:
    prompt: str
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    duration_s: Optional[float] = None
    images: list[ImageInput] = field(default_factory=list)


@dataclass
class OmniTake:
    path: Path
    interaction_id: str
    duration_s: Optional[float]
    has_audio: bool
    width: Optional[int]
    height: Optional[int]
    requested_duration_s: Optional[float]
    watermark: str = "SynthID"
    model: str = MODEL


class GeminiOmniEngine:
    def __init__(self, api_key_provider: Callable[[], Optional[str]],
                 cloud_enabled: Callable[[], bool],
                 transport: Transport = urllib_transport,
                 policy_provider: Optional[Callable[[], NetworkPolicy]] = None,
                 poll_interval_s: float = 5.0, poll_timeout_s: float = 600.0,
                 sleep: Callable[[float], None] = time.sleep,
                 media_probe: Optional[Callable[[Path], object]] = None) -> None:
        self._key = api_key_provider
        self._enabled = cloud_enabled
        self._transport = transport
        self._policy = policy_provider or (
            lambda: NetworkPolicy().enable_cloud_generation()
            if self._enabled() else NetworkPolicy())
        self._poll_interval = poll_interval_s
        self._poll_timeout = poll_timeout_s
        self._sleep = sleep
        self._probe = media_probe

    # -- declaration -------------------------------------------------------
    def status(self) -> EngineStatus:
        if not self._enabled():
            return EngineStatus(False, "Cloud generation is switched off in Settings")
        if not (self._key() or "").strip():
            return EngineStatus(False, f"No Gemini API key set (Settings or {ENV_KEY})")
        return EngineStatus(True)

    def spec(self) -> EngineSpec:
        return EngineSpec(
            id=ENGINE_ID, name="Gemini Omni Flash (cloud)",
            roles=frozenset({Role.VIDEO}), capabilities=CAPABILITIES,
            description="Google's video model with generated sound and dialogue. "
                        "Opt-in; runs on Google's servers and is billed to your key.",
            status_fn=self.status)

    # -- request -----------------------------------------------------------
    def build_body(self, req: OmniRequest) -> dict:
        if req.aspect_ratio not in CAPABILITIES.aspect_ratios:
            raise OmniError(f"Aspect ratio {req.aspect_ratio} is not supported "
                            f"(16:9 or 9:16).")
        if req.resolution not in RESOLUTIONS:
            raise OmniError(f"Resolution {req.resolution} is not supported.")
        prompt = req.prompt.strip()
        if not prompt:
            raise OmniError("The shot has no prompt.")
        if req.duration_s is not None:
            if not (CAPABILITIES.min_duration_s <= req.duration_s
                    <= CAPABILITIES.max_duration_s):
                raise OmniError(f"Gemini Omni Flash makes 3-10 s clips; "
                                f"{req.duration_s:g} s was requested.")
            # No documented duration field: state it in the prompt, then
            # measure the real length afterwards.
            prompt += f" The clip is about {req.duration_s:g} seconds long."
        firsts = [i for i in req.images if i.role == "first_frame"]
        lasts = [i for i in req.images if i.role == "last_frame"]
        refs = [i for i in req.images if i.role == "reference"]
        if lasts and not firsts:
            raise OmniError("A last frame needs a first frame too.")
        if len(firsts) > 1 or len(lasts) > 1:
            raise OmniError("Use at most one first frame and one last frame.")
        if len(refs) > CAPABILITIES.max_reference_images:
            raise OmniError(f"At most {CAPABILITIES.max_reference_images} "
                            f"reference images per shot.")
        body: dict = {
            "model": MODEL,
            "response_format": {"type": "video", "delivery": "uri",
                                "aspect_ratio": req.aspect_ratio,
                                "resolution": req.resolution},
        }
        if not req.images:
            body["input"] = prompt
            return body
        items = []
        for img in firsts + lasts + refs:
            items.append({"type": "image", "mime_type": img.mime(),
                          "data": base64.b64encode(img.path.read_bytes()).decode()})
        if firsts:
            prompt = ("Use the first image as the opening frame"
                      + (" and the second image as the final frame" if lasts else "")
                      + ". " + prompt)
        items.append({"type": "text", "text": prompt})
        body["input"] = items
        return body

    # -- HTTP --------------------------------------------------------------
    def _headers(self, json_body: bool) -> dict[str, str]:
        key = (self._key() or "").strip()
        h = {"x-goog-api-key": key}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def _call(self, method: str, url: str, body: Optional[dict] = None,
              timeout: float = 600.0) -> bytes:
        data = json.dumps(body).encode() if body is not None else None
        try:
            code, raw = self._transport(method, url, self._headers(data is not None),
                                        data, timeout)
        except OSError as exc:
            raise OmniError(f"Could not reach Google: {exc.__class__.__name__}") from None
        if code >= 400:
            raise OmniError(f"Google returned HTTP {code}: {_error_text(raw)}")
        return raw

    # -- generate ----------------------------------------------------------
    def generate(self, req: OmniRequest, out_path: Path,
                 on_progress: Optional[Callable[[str], None]] = None) -> OmniTake:
        st = self.status()
        if not st.available:
            raise OmniError(st.reason)
        try:
            self._policy().guard_network("cloud_generation")
        except NetworkPolicyError as exc:
            raise OmniError(str(exc)) from None
        say = on_progress or (lambda _m: None)
        body = self.build_body(req)
        say("Sending the shot to Gemini Omni Flash")
        resp = json.loads(self._call("POST", f"{API_BASE}/interactions", body))
        video = _find_video(resp)
        if video is None:
            raise OmniError("Google's response contained no video "
                            f"(status: {resp.get('status', 'unknown')}).")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if video.get("data"):
            out_path.write_bytes(base64.b64decode(video["data"]))
        elif video.get("uri"):
            file_id = _file_id(video["uri"])
            self._wait_active(file_id, say)
            say("Downloading the take")
            out_path.write_bytes(self._call(
                "GET", f"{API_BASE}/files/{file_id}:download?alt=media"))
        else:
            raise OmniError("Google's video entry had neither data nor a file link.")
        return self._verify(out_path, resp.get("id", ""), req.duration_s)

    def _wait_active(self, file_id: str, say: Callable[[str], None]) -> None:
        waited = 0.0
        while True:
            info = json.loads(self._call("GET", f"{API_BASE}/files/{file_id}", timeout=60))
            state = info.get("state", "")
            if state == "ACTIVE":
                return
            if state == "FAILED":
                raise OmniError("Google reports the video file failed: "
                                f"{_error_text(json.dumps(info).encode())}")
            if waited >= self._poll_timeout:
                raise OmniError(f"The video was not ready after {self._poll_timeout:g} s.")
            say(f"Waiting for Google to finish the file ({state or 'processing'})")
            self._sleep(self._poll_interval)
            waited += self._poll_interval

    def _verify(self, path: Path, interaction_id: str,
                requested: Optional[float]) -> OmniTake:
        if not path.exists() or path.stat().st_size == 0:
            raise OmniError("No video data was received.")
        probe_fn = self._probe
        if probe_fn is None:
            from ..media.probe import probe as probe_fn  # type: ignore[assignment]
        info = probe_fn(path)
        if not getattr(info, "ok", False) or not getattr(info, "has_video", False):
            path.unlink(missing_ok=True)
            raise OmniError("The downloaded file is not a playable video: "
                            f"{getattr(info, 'error', '') or 'no video stream'}.")
        return OmniTake(path=path, interaction_id=interaction_id,
                        duration_s=info.duration_s, has_audio=info.has_audio,
                        width=info.width, height=info.height,
                        requested_duration_s=requested)


def _find_video(resp: dict) -> Optional[dict]:
    out = resp.get("output_video")
    if isinstance(out, dict) and (out.get("data") or out.get("uri")):
        return out
    for step in resp.get("steps") or []:
        for item in step.get("content") or []:
            if isinstance(item, dict) and item.get("type") == "video":
                return item
    return None


def _file_id(uri: str) -> str:
    tail = uri.split("/files/", 1)[-1]
    fid = tail.split(":", 1)[0].split("?", 1)[0].strip("/")
    if not fid or "/" in fid:
        raise OmniError("Could not read the file id from Google's video link.")
    return fid


def _error_text(raw: bytes) -> str:
    try:
        data = json.loads(raw)
        err = data.get("error", data)
        msg = err.get("message") if isinstance(err, dict) else None
        return str(msg or err)[:300]
    except Exception:
        return raw[:300].decode("utf-8", "replace") or "no details"
