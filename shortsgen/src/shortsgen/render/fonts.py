"""Font loading and glyph coverage (fontTools cmap)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import ImageFont

_IGNORED = {"\n", "\r", "\t"}


@lru_cache(maxsize=None)
def _cmap(path: str) -> frozenset[int]:
    font = TTFont(path, lazy=True)
    return frozenset(font.getBestCmap().keys())


def missing_glyphs(text: str, font_path: Path) -> set[str]:
    cmap = _cmap(str(font_path))
    return {ch for ch in text if ch not in _IGNORED and ord(ch) not in cmap}


@lru_cache(maxsize=None)
def load(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)
