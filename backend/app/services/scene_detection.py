from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.services.highlight_scoring import SceneWindow
from app.settings import Settings, get_settings


class SceneDetectionProvider(Protocol):
    @property
    def metadata(self) -> dict[str, object]: ...

    def detect_scenes(self, video_path: Path) -> list[SceneWindow]: ...


def _load_scenedetect_module():
    return importlib.import_module("scenedetect")


@dataclass(slots=True)
class PySceneDetectProvider:
    threshold: float = 27.0
    min_scene_len: int = 15
    start_in_scene: bool = True

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "provider": "pyscenedetect",
            "detector": "ContentDetector",
            "threshold": self.threshold,
            "min_scene_len": self.min_scene_len,
            "start_in_scene": self.start_in_scene,
        }

    def detect_scenes(self, video_path: Path) -> list[SceneWindow]:
        scenedetect = _load_scenedetect_module()
        scene_list = scenedetect.detect(
            str(video_path),
            scenedetect.ContentDetector(threshold=self.threshold, min_scene_len=self.min_scene_len),
            start_in_scene=self.start_in_scene,
            show_progress=False,
        )

        scene_windows: list[SceneWindow] = []
        for index, (start, end) in enumerate(scene_list, start=1):
            start_s = round(float(start.seconds), 3)
            end_s = round(float(end.seconds), 3)
            if end_s <= start_s:
                continue
            scene_windows.append(
                SceneWindow(
                    id=f"scene-{index:04d}",
                    start_s=start_s,
                    end_s=end_s,
                    source="pyscenedetect",
                )
            )
        return scene_windows


def build_scene_detection_provider(settings: Settings | None = None) -> SceneDetectionProvider:
    runtime = settings or get_settings()
    return PySceneDetectProvider(
        threshold=runtime.scenedetect_threshold,
        min_scene_len=runtime.scenedetect_min_scene_len,
    )
