"""OpenAI image provider (portrait, quality from config)."""

from __future__ import annotations

import base64

from ..config import Settings
from .base import Usage
from .openai_client import make_client

IMAGE_SUFFIX = ", no text, no letters, no logos, abstract, dark, high contrast background, vertical composition"


class OpenAIImageProvider:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        self.client = make_client(settings, client)

    def estimate_usd(self, prompt: str) -> float:
        return self.settings.prices[f"image_{self.settings.image_quality}_1024x1536"]

    def generate(self, prompt: str) -> tuple[bytes, Usage]:
        resp = self.client.images.generate(
            model=self.settings.image_model,
            prompt=prompt + IMAGE_SUFFIX,
            size="1024x1536",
            quality=self.settings.image_quality,
            n=1,
        )
        data = base64.b64decode(resp.data[0].b64_json)
        return data, Usage("image", 1, "image", self.estimate_usd(prompt))
