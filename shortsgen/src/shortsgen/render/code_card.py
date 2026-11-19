"""Verbatim code card rendering with Pygments + Pillow.

The drawn text is recorded token-by-token as it is passed to draw.text, so tests
can prove the pixels came from exactly the source text (AC-7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PIL import Image, ImageDraw
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.util import ClassNotFound

from .. import CODE_FONT
from . import fonts

TAB_WIDTH = 4
MAX_FONT = 40
MIN_FONT = 28
MAX_LINES = 18
CARD_WIDTH = 1000
CARD_MAX_HEIGHT = 1000
PADDING = 32
LINE_SPACING = 1.35
STYLE = get_style_by_name("monokai")
DEFAULT_COLOR = "#f8f8f2"


class CodeOverflowError(ValueError):
    pass


@dataclass
class CodeCard:
    image: Image.Image
    font_size: int
    line_tops: list[int]  # y of each line within the card
    line_height: int
    drawn: list[str] = field(default_factory=list)  # every string passed to draw.text, plus "\n"

    @property
    def drawn_text(self) -> str:
        return "".join(self.drawn)


def prepare(lines: list[str]) -> str:
    """The exact text that will be drawn: lines joined by \\n, tabs expanded."""
    return "\n".join(line.expandtabs(TAB_WIDTH) for line in lines)


def _lexer(language: str | None):
    opts = dict(stripnl=False, ensurenl=False, stripall=False, tabsize=0)
    if language:
        try:
            return get_lexer_by_name(language, **opts)
        except ClassNotFound:
            pass
    return TextLexer(**opts)


def fit_font_size(text: str) -> int:
    lines = text.split("\n")
    if len(lines) > MAX_LINES:
        raise CodeOverflowError(f"{len(lines)} lines > max {MAX_LINES}")
    inner_w = CARD_WIDTH - 2 * PADDING
    for size in range(MAX_FONT, MIN_FONT - 1, -2):
        font = fonts.load(CODE_FONT, size)
        line_h = int(size * LINE_SPACING)
        widest = max((font.getlength(l) for l in lines), default=0)
        if widest <= inner_w and line_h * len(lines) + 2 * PADDING <= CARD_MAX_HEIGHT:
            return size
    raise CodeOverflowError(f"code does not fit at minimum font size {MIN_FONT}px")


def _color(ttype) -> str:
    while ttype is not None:
        style = STYLE.style_for_token(ttype)
        if style.get("color"):
            return "#" + style["color"]
        ttype = ttype.parent
    return DEFAULT_COLOR


def render(lines: list[str], language: str | None) -> CodeCard:
    text = prepare(lines)
    size = fit_font_size(text)
    font = fonts.load(CODE_FONT, size)
    line_h = int(size * LINE_SPACING)
    n_lines = len(text.split("\n"))
    height = line_h * n_lines + 2 * PADDING
    img = Image.new("RGBA", (CARD_WIDTH, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, CARD_WIDTH - 1, height - 1), radius=24, fill=(20, 22, 30, 225))

    drawn: list[str] = []
    x, row = PADDING, 0
    line_tops = [PADDING + i * line_h for i in range(n_lines)]
    for ttype, value in _lexer(language).get_tokens(text):
        parts = value.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                drawn.append("\n")
                row += 1
                x = PADDING
            if part:
                d.text((x, line_tops[row]), part, font=font, fill=_color(ttype))
                drawn.append(part)
                x += font.getlength(part)
    card = CodeCard(image=img, font_size=size, line_tops=line_tops, line_height=line_h, drawn=drawn)
    if card.drawn_text != text:
        # Pygments altered the text (should not happen with these options): never show wrong code.
        raise AssertionError("drawn code differs from source")
    return card
