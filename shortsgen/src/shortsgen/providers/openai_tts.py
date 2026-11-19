"""OpenAI TTS provider (response_format=pcm: raw 24 kHz s16le mono)."""

from __future__ import annotations

import numpy as np

from ..audio import pcm_bytes_to_array
from ..config import TTS_SAMPLE_RATE, Settings
from .base import Usage
from .openai_client import make_client

KOREAN_CHARS_PER_SECOND = 6.5  # estimate only; actual seconds are measured from the audio


class OpenAITTSProvider:
    sample_rate = TTS_SAMPLE_RATE

    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.client = make_client(settings, client)

    def _usd(self, seconds: float) -> float:
        return seconds / 60 * self.settings.prices["tts_per_min"]

    def estimate_usd(self, text: str) -> float:
        return self._usd(len(text) / KOREAN_CHARS_PER_SECOND)

    def synthesize(self, text: str) -> tuple[np.ndarray, Usage]:
        resp = self.client.audio.speech.create(
            model=self.settings.tts_model,
            voice=self.settings.tts_voice,
            input=text,
            instructions=self.settings.tts_instructions,
            response_format="pcm",
        )
        pcm = pcm_bytes_to_array(resp.content)
        seconds = len(pcm) / self.sample_rate
        return pcm, Usage("tts", seconds, "seconds", self._usd(seconds))
