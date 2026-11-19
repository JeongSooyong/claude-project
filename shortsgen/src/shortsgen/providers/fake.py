"""Deterministic offline providers for tests and dry runs."""

from __future__ import annotations

import hashlib
import io

import numpy as np
from PIL import Image

from ..config import TTS_SAMPLE_RATE
from ..models import CodeRef, Scene, Script, Sentence, TechDoc
from .base import Usage


class FakeScriptProvider:
    def estimate_usd(self, doc: TechDoc) -> float:
        return 0.0

    def generate(self, doc: TechDoc) -> tuple[Script, Usage]:
        scenes: list[Scene] = [
            Scene(
                id="s1",
                narration=[
                    Sentence(text=f"오늘은 {doc.title or '이 문서'}의 핵심을 짧게 정리해 보겠습니다."),
                    Sentence(text="끝까지 보시면 바로 써먹을 수 있습니다."),
                ],
                on_screen_text=doc.title or "핵심 정리",
                image_prompt="abstract dark gradient, soft light",
            )
        ]
        for i, block in enumerate(doc.code_blocks[:5], start=2):
            n = len(block.lines)
            end = min(n, 12)
            scenes.append(
                Scene(
                    id=f"s{i}",
                    narration=[
                        Sentence(text="이 코드를 함께 살펴보겠습니다.", highlight_line=1),
                        Sentence(text=f"총 {end}줄로 핵심 동작을 보여 줍니다.", highlight_line=end),
                        Sentence(text="이 부분이 가장 중요한 포인트입니다."),
                    ],
                    on_screen_text=f"예제 {i - 1}",
                    code=CodeRef(block_id=block.id, start_line=1, end_line=end),
                    image_prompt="abstract circuit pattern, dark blue",
                )
            )
        scenes.append(
            Scene(
                id=f"s{len(scenes) + 1}",
                narration=[Sentence(text="오늘 내용이 도움이 되셨다면 구독해 주세요.")],
                on_screen_text="정리",
                image_prompt="abstract dark gradient",
            )
        )
        script = Script(
            title=(doc.title or "기술 문서 요약")[:80],
            description=f"{doc.title} 핵심 요약 쇼츠입니다.",
            hashtags=["#개발", "#프로그래밍", "#Shorts"],
            scenes=scenes,
        )
        return script, Usage("script", 0, "tokens", 0.0)


class FakeImageProvider:
    def estimate_usd(self, prompt: str) -> float:
        return 0.0

    def generate(self, prompt: str) -> tuple[bytes, Usage]:
        h = hashlib.sha256(prompt.encode()).digest()
        img = Image.new("RGB", (1024, 1536), (h[0] // 3, h[1] // 3, 60 + h[2] // 3))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue(), Usage("image", 1, "image", 0.0)


class FakeTTSProvider:
    """Silent PCM whose length is proportional to text length (seconds_per_char)."""

    sample_rate = TTS_SAMPLE_RATE

    def __init__(self, seconds_per_char: float = 0.16):
        self.seconds_per_char = seconds_per_char

    def estimate_usd(self, text: str) -> float:
        return 0.0

    def synthesize(self, text: str) -> tuple[np.ndarray, Usage]:
        n = max(1, int(len(text) * self.seconds_per_char * self.sample_rate))
        return np.zeros(n, dtype=np.int16), Usage("tts", n / self.sample_rate, "seconds", 0.0)
