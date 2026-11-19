"""Settings from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from . import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")

# Approximate USD prices. CONFIRM CURRENT PRICES before relying on them.
DEFAULT_PRICES = {
    "script_input_per_mtok": 3.0,
    "script_output_per_mtok": 15.0,
    "image_low_1024x1536": 0.016,
    "image_medium_1024x1536": 0.063,
    "image_high_1024x1536": 0.25,
    "tts_per_min": 0.015,
}


@dataclass
class Settings:
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    script_model: str = field(default_factory=lambda: os.getenv("SCRIPT_MODEL", "claude-sonnet-5-5"))
    image_model: str = field(default_factory=lambda: os.getenv("IMAGE_MODEL", "gpt-image-1"))
    image_quality: str = field(default_factory=lambda: os.getenv("IMAGE_QUALITY", "low"))
    tts_model: str = field(default_factory=lambda: os.getenv("TTS_MODEL", "gpt-4o-mini-tts"))
    tts_voice: str = field(default_factory=lambda: os.getenv("TTS_VOICE", "alloy"))
    tts_instructions: str = field(
        default_factory=lambda: os.getenv(
            "TTS_INSTRUCTIONS",
            "차분하고 명확한 한국어 기술 강의 톤. 일정한 속도와 음색을 유지하세요.",
        )
    )
    cost_ceiling_krw: float = field(default_factory=lambda: float(os.getenv("COST_CEILING_KRW", "1000")))
    usd_krw: float = field(default_factory=lambda: float(os.getenv("USD_KRW", "1400")))
    projects_dir: Path = field(
        default_factory=lambda: Path(os.getenv("SHORTSGEN_PROJECTS", str(PROJECT_ROOT / "projects")))
    )
    secrets_dir: Path = field(
        default_factory=lambda: Path(os.getenv("APPDATA", str(Path.home()))) / "shortsgen"
    )
    prices: dict = field(default_factory=lambda: dict(DEFAULT_PRICES))


# Render constants (frame size lives in render/layout.py)
FPS = 30
SAMPLE_RATE = 48000
TTS_SAMPLE_RATE = 24000  # OpenAI pcm output: 24 kHz s16le mono
SENTENCE_GAP_MS = 120
SCENE_TAIL_MS = 300
MIN_SECONDS, MAX_SECONDS = 30.0, 59.0
