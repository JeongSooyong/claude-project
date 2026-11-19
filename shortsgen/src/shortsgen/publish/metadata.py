"""YouTube metadata from the (user-reviewed) Script."""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Script

CATEGORY_SCIENCE_TECH = "28"


def description_text(script: Script) -> str:
    tags = " ".join(t if t.startswith("#") else f"#{t}" for t in script.hashtags)
    return f"{script.description}\n\n{tags}".strip()


def video_body(script: Script) -> dict:
    return {
        "snippet": {
            "title": script.title,
            "description": description_text(script),
            "tags": [t.lstrip("#") for t in script.hashtags],
            "categoryId": CATEGORY_SCIENCE_TECH,
            "defaultLanguage": "ko",
            "defaultAudioLanguage": "ko",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            # Backgrounds are AI-generated images; disclose per YouTube A/S content policy.
            "containsSyntheticMedia": True,
        },
    }


def write(script: Script, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "metadata.json"
    data = {"title": script.title, "description": description_text(script), "hashtags": script.hashtags}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
