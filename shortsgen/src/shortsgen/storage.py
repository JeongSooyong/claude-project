"""File-based project storage: <root>/<id>/{project.json, cost.json, timeline.json, assets/, out/}."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from .models import CostEntry, Project, TechDoc, Timeline

PROJECT_ID = re.compile(r"[0-9a-f]{12}")


class Storage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        # Ids are generated here (12 hex chars). Anything else could escape the root
        # (e.g. "..\\x" after URL decoding on Windows), so it is treated as not found.
        if not PROJECT_ID.fullmatch(project_id or ""):
            raise KeyError(project_id)
        return self.root / project_id

    def create(self, doc: TechDoc) -> Project:
        project = Project(id=uuid.uuid4().hex[:12], doc=doc)
        d = self.project_dir(project.id)
        (d / "assets").mkdir(parents=True, exist_ok=True)
        (d / "out").mkdir(parents=True, exist_ok=True)
        self.save(project)
        return project

    def save(self, project: Project) -> None:
        path = self.project_dir(project.id) / "project.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, project_id: str) -> Project:
        path = self.project_dir(project_id) / "project.json"
        return Project.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, project_id: str) -> bool:
        try:
            return (self.project_dir(project_id) / "project.json").exists()
        except KeyError:
            return False

    # --- timeline ---
    def save_timeline(self, project_id: str, timeline: Timeline) -> None:
        (self.project_dir(project_id) / "timeline.json").write_text(
            timeline.model_dump_json(indent=2), encoding="utf-8"
        )

    # --- cost ---
    def cost_entries(self, project_id: str) -> list[CostEntry]:
        p = self.project_dir(project_id) / "cost.json"
        if not p.exists():
            return []
        return [CostEntry.model_validate(e) for e in json.loads(p.read_text(encoding="utf-8"))]

    def append_cost(self, project_id: str, entry: CostEntry) -> None:
        entries = self.cost_entries(project_id) + [entry]
        p = self.project_dir(project_id) / "cost.json"
        p.write_text(
            json.dumps([e.model_dump(mode="json") for e in entries], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
