"""Script-generation adapter (roadmap: Qwen2.5 quantized via llama.cpp).

If llama-cpp-python and a GGUF model are present it runs locally; otherwise it
reports Unavailable with a precise reason. A deterministic offline fallback
can produce a *structured* script skeleton from the user's brief so the
editing pipeline is never blocked — but it is clearly labelled as non-AI
template output, never passed off as model generation.

P2 hardening:
  * Uses the Qwen2.5-Instruct chat template (chat completion) for reliable,
    parseable JSON.
  * Robustly extracts a scene list from the model's text even when it wraps
    the JSON in prose or a ```json fence.
  * Returns parsed scenes in `metrics['scenes']` so the pipeline can verify
    real structured output, not just a non-empty string.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Optional

from .base import AdapterResult, Availability, AIAdapter


class ScriptAdapter(AIAdapter):
    capability = "script"
    runtime = "llama_cpp"

    def __init__(self, model_path: Optional[str] = None,
                 n_ctx: int = 2048, n_threads: Optional[int] = None) -> None:
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads

    def availability(self) -> Availability:
        try:
            import llama_cpp  # noqa: F401
        except Exception:
            return Availability(
                False,
                "llama-cpp-python not installed. Install the Tier-1 CPU AI "
                "environment and a quantized Qwen2.5 GGUF model to enable "
                "local script generation.",
                runtime=self.runtime)
        if not self.model_path or not Path(self.model_path).exists():
            return Availability(
                False,
                "No GGUF script model found. Place an approved Qwen2.5 "
                "quantized .gguf in the models/script directory first.",
                runtime=self.runtime)
        return Availability(True, runtime=self.runtime,
                            model_name=Path(self.model_path).name)

    def run(self, params: dict, cancel: Optional[threading.Event] = None) -> AdapterResult:
        avail = self.availability()
        if not avail.available:
            return AdapterResult(False, message=avail.reason)

        brief = params.get("brief", "")
        n_scenes = int(params.get("scenes", 6))
        t0 = time.time()
        try:
            from llama_cpp import Llama  # type: ignore
            kwargs = dict(model_path=self.model_path, n_ctx=self.n_ctx,
                          verbose=False)
            if self.n_threads:
                kwargs["n_threads"] = self.n_threads
            llm = Llama(**kwargs)
            messages = _chat_messages(brief, n_scenes)
            # Qwen2.5-Instruct supports chat completion via llama.cpp.
            out = llm.create_chat_completion(
                messages=messages, max_tokens=900, temperature=0.7)
            text = out["choices"][0]["message"]["content"]
        except Exception as exc:
            return AdapterResult(False, message=f"Model run failed: {exc}")
        dt = time.time() - t0

        scenes = parse_scenes(text, n_scenes)
        if not scenes:
            return AdapterResult(
                False,
                message="Model produced output but no valid scene JSON could "
                        "be parsed. Treating as a failed generation rather "
                        "than guessing a script.",
                metrics={"runtime_s": round(dt, 2), "raw": text[:500]})
        return AdapterResult(
            True, text=text, message="Script generated locally.",
            metrics={"runtime_s": round(dt, 2), "scenes": scenes,
                     "tokens_hint": len(text.split())})


def _chat_messages(brief: str, n_scenes: int) -> list[dict]:
    system = (
        "You are a concise video script writer. You ALWAYS reply with ONLY a "
        "JSON array, no prose, no markdown fences.")
    user = (
        f"Write a {n_scenes}-scene script for a short video about: {brief}\n"
        f"Return a JSON array of exactly {n_scenes} objects, each with keys "
        f'"title" (short), "narration" (1-2 spoken sentences), and "caption" '
        f"(a few on-screen words). JSON only.")
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_scenes(text: str, n_scenes: int) -> list[dict]:
    """Extract a list of {title,narration,caption} dicts from model text.

    Tolerant of ```json fences and surrounding prose. Returns [] on failure —
    the caller treats that as a failed generation, never a fabricated script.
    """
    if not text:
        return []
    # Strip code fences.
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text
    # Find the first JSON array in the candidate.
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    blob = candidate[start:end + 1]
    try:
        data = json.loads(blob)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    scenes: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        scenes.append({
            "title": str(item.get("title", "") or f"Scene {len(scenes)+1}"),
            "narration": str(item.get("narration", "") or ""),
            "caption": str(item.get("caption", "") or ""),
        })
    return scenes


def template_script(brief: str, n_scenes: int = 6) -> dict:
    """Deterministic, NON-AI structured skeleton.

    Lets a user storyboard offline when no model is available. The caller must
    label this as a template, not generated content.
    """
    scenes = []
    for i in range(max(1, n_scenes)):
        scenes.append({
            "title": f"Scene {i+1}",
            "narration": "" if i else (brief or "Introduction"),
            "caption": "",
        })
    return {"source": "template", "brief": brief, "scenes": scenes}
