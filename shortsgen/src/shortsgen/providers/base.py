"""Provider interfaces. Swap implementations without touching the pipeline (AC-9)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..models import Script, TechDoc


@dataclass
class Usage:
    kind: str  # script | image | tts
    units: float
    unit_name: str
    usd: float


class ScriptProvider(Protocol):
    def estimate_usd(self, doc: TechDoc) -> float: ...
    def generate(self, doc: TechDoc) -> tuple[Script, Usage]: ...


class ImageProvider(Protocol):
    def estimate_usd(self, prompt: str) -> float: ...
    def generate(self, prompt: str) -> tuple[bytes, Usage]:
        """Returns PNG/JPEG bytes (portrait; caller cover-crops to 9:16)."""
        ...


class TTSProvider(Protocol):
    sample_rate: int

    def estimate_usd(self, text: str) -> float: ...
    def synthesize(self, text: str) -> tuple[np.ndarray, Usage]:
        """Returns mono int16 PCM at self.sample_rate."""
        ...


@dataclass
class Providers:
    script: ScriptProvider
    image: ImageProvider
    tts: TTSProvider
