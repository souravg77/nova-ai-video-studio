"""Timeline planning: Project -> RenderSpec (roadmap section 5 media engine).

Pure, testable mapping. Chooses motion effects for stills, resolves asset
paths, and carries the user's REQUESTED target resolution unchanged — the
renderer never silently downscales.
"""
from __future__ import annotations

from pathlib import Path

from ..models.project import AssetKind, Project
from .renderer import RenderSpec, SceneSpec


def build_render_spec(project: Project, output_path: str) -> RenderSpec:
    scenes: list[SceneSpec] = []
    narration_path: str | None = None
    music_path: str | None = None

    # First audio asset flagged as narration-like becomes narration; a second
    # distinct audio asset becomes music. (UI can override explicitly later.)
    audio_assets = [a for a in project.assets if a.kind == AssetKind.AUDIO]
    if audio_assets:
        narration_path = audio_assets[0].path
    if len(audio_assets) > 1:
        music_path = audio_assets[1].path

    for scene in project.scenes:
        visual = project.asset_by_id(scene.visual_asset_id) if scene.visual_asset_id else None
        if visual is None:
            scenes.append(SceneSpec(
                kind="color", color="black", duration_s=scene.duration_s,
                caption=scene.caption or scene.title))
            continue
        if visual.kind == AssetKind.IMAGE:
            scenes.append(SceneSpec(
                kind="image", source=visual.path, duration_s=scene.duration_s,
                caption=scene.caption, motion=scene.motion_effect or "kenburns"))
        elif visual.kind in (AssetKind.VIDEO, AssetKind.GENERATED):
            scenes.append(SceneSpec(
                kind="video", source=visual.path, duration_s=scene.duration_s,
                caption=scene.caption))
        else:
            scenes.append(SceneSpec(
                kind="color", color="black", duration_s=scene.duration_s,
                caption=scene.caption))

    return RenderSpec(
        scenes=scenes,
        width=project.target_width,
        height=project.target_height,
        fps=project.target_fps,
        narration_path=narration_path,
        music_path=music_path,
        output_path=output_path,
    )
