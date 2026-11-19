"""PNG layers for a scene: zoomable background, static foreground, highlight bands, subtitle cards.

All text is drawn by Pillow with bundled fonts (no libass).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from .. import TEXT_FONT
from . import code_card, fonts, layout
from .text_layout import wrap


@dataclass
class SceneLayers:
    bg: Path  # 2x size still for zoompan
    fg: Path  # full-frame RGBA
    highlights: dict[int, Path]  # code line (1-based, in the block) -> full-frame RGBA band
    subtitles: list[Path]  # one per cue, full-frame RGBA


def cover_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (resized.width - w) // 2
    top = (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def title_lines(text: str) -> list[str]:
    if not text.strip():
        return []
    font = fonts.load(TEXT_FONT, layout.TITLE_FONT_SIZE)
    return wrap(text, font, layout.TITLE_MAX_WIDTH)


def _draw_centered(d: ImageDraw.ImageDraw, lines: list[str], font, top: int, line_h: int, stroke: int):
    for i, line in enumerate(lines):
        w = font.getlength(line)
        d.text(
            ((layout.WIDTH - w) / 2, top + i * line_h),
            line,
            font=font,
            fill="white",
            stroke_width=stroke,
            stroke_fill="black",
        )


def build_foreground(on_screen_text: str, card: code_card.CodeCard | None) -> Image.Image:
    img = Image.new("RGBA", (layout.WIDTH, layout.HEIGHT), (0, 0, 0, layout.DIM_ALPHA))
    d = ImageDraw.Draw(img)
    font = fonts.load(TEXT_FONT, layout.TITLE_FONT_SIZE)
    lines = title_lines(on_screen_text)
    _draw_centered(d, lines, font, layout.TITLE_TOP, int(layout.TITLE_FONT_SIZE * 1.3), stroke=3)
    if card is not None:
        img.alpha_composite(card.image, (layout.CODE_LEFT, layout.CODE_TOP))
    return img


def build_highlight(card: code_card.CodeCard, row: int) -> Image.Image:
    """row: 0-based row within the card."""
    img = Image.new("RGBA", (layout.WIDTH, layout.HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = layout.CODE_TOP + card.line_tops[row] - 4
    bottom = top + card.line_height
    left = layout.CODE_LEFT + 12
    right = layout.CODE_LEFT + card.image.width - 12
    d.rectangle((left, top, right, bottom), fill=(255, 214, 0, 55))
    d.rectangle((left, top, left + 6, bottom), fill=(255, 214, 0, 230))
    return img


def build_subtitle(lines: list[str]) -> Image.Image:
    img = Image.new("RGBA", (layout.WIDTH, layout.HEIGHT), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = fonts.load(TEXT_FONT, layout.SUB_FONT_SIZE)
    line_h = int(layout.SUB_FONT_SIZE * 1.3)
    top = layout.SUB_BOTTOM - line_h * len(lines)
    _draw_centered(d, lines, font, top, line_h, stroke=5)
    return img
