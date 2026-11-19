"""Content hashes: asset freshness and approval binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import Project, Scene


def _h(obj) -> str:
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scene_hash(scene: Scene) -> str:
    return _h(scene.model_dump(mode="json"))


def tts_source_hash(scene: Scene, voice: str, model: str) -> str:
    return _h({"narration": [s.text for s in scene.narration], "voice": voice, "model": model})


def image_source_hash(scene: Scene) -> str:
    return _h({"image_prompt": scene.image_prompt})


def content_hash(project: Project, project_dir: Path) -> str:
    """Hash of the script plus every asset file's bytes. Bound at approval."""
    assert project.script is not None
    assets = {
        key: file_sha256(project_dir / rec.path) if (project_dir / rec.path).exists() else None
        for key, rec in sorted(project.assets.items())
    }
    return _h({"script": project.script.model_dump(mode="json"), "assets": assets})
