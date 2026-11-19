"""Domain models. All line numbers are 1-based and inclusive."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CodeBlock(BaseModel):
    id: str
    language: str | None = None
    content: str  # verbatim (only CRLF/CR -> LF normalization applied)

    @property
    def lines(self) -> list[str]:
        return self.content.split("\n")

    def line_range(self, start: int, end: int) -> list[str]:
        """Lines start..end, 1-based inclusive."""
        return self.lines[start - 1 : end]


class TechDoc(BaseModel):
    source: str
    title: str = ""
    prose: str  # markdown prose with [[CODE:<id>]] placeholders
    code_blocks: list[CodeBlock] = Field(default_factory=list)

    def block(self, block_id: str) -> CodeBlock | None:
        return next((b for b in self.code_blocks if b.id == block_id), None)


class CodeRef(BaseModel):
    block_id: str
    start_line: int
    end_line: int


class Sentence(BaseModel):
    text: str
    highlight_line: int | None = None


class Scene(BaseModel):
    id: str
    narration: list[Sentence]
    on_screen_text: str = ""
    code: CodeRef | None = None
    image_prompt: str


class Script(BaseModel):
    title: str
    description: str
    hashtags: list[str]
    scenes: list[Scene]

    def scene(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.id == scene_id), None)


class Cue(BaseModel):
    start_frame: int
    end_frame: int  # exclusive
    lines: list[str]
    highlight_line: int | None = None


class SceneTiming(BaseModel):
    scene_id: str
    start_frame: int
    frames: int
    sentence_offsets_samples: list[int]  # relative to scene start, at audio sample rate
    sentence_lengths_samples: list[int]
    cues: list[Cue]


class Timeline(BaseModel):
    fps: int
    sample_rate: int
    scenes: list[SceneTiming]

    @property
    def total_frames(self) -> int:
        return sum(s.frames for s in self.scenes)

    @property
    def total_seconds(self) -> float:
        return self.total_frames / self.fps


class ProjectState(str, Enum):
    ingested = "ingested"
    scripted = "scripted"
    reviewing = "reviewing"
    approved = "approved"
    rendering = "rendering"
    render_failed = "render_failed"
    rendered = "rendered"
    uploading = "uploading"
    upload_failed = "upload_failed"
    uploaded = "uploaded"


class AssetRecord(BaseModel):
    """A generated file plus the hash of the inputs it was generated from."""

    path: str  # relative to the project dir
    source_hash: str
    samples: int | None = None  # for TTS audio (per sentence lengths summed)
    sentence_samples: list[int] | None = None


class CostEntry(BaseModel):
    kind: str  # script | image | tts
    units: float
    unit_name: str
    usd: float
    at: str = Field(default_factory=_now)


class Project(BaseModel):
    id: str
    state: ProjectState = ProjectState.ingested
    doc: TechDoc
    script: Script | None = None
    # keys: "image:<scene_id>", "tts:<scene_id>"
    assets: dict[str, AssetRecord] = Field(default_factory=dict)
    approved_hash: str | None = None
    rendered_hash: str | None = None
    video_id: str | None = None
    upload_uri: str | None = None
    error: str | None = None
    created_at: str = Field(default_factory=_now)
