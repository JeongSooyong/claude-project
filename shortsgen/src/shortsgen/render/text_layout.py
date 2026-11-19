"""Korean-aware line wrapping by pixel width."""

from __future__ import annotations

from PIL import ImageFont


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_chars: int | None = None) -> list[str]:
    """Wrap text into lines that fit max_width px (and max_chars, if given).

    Breaks at spaces; a word that alone is too wide is broken per character.
    Explicit newlines are respected.
    """

    def fits(s: str) -> bool:
        return font.getlength(s) <= max_width and (max_chars is None or len(s) <= max_chars)

    out: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        line = ""
        for word in words:
            candidate = word if not line else f"{line} {word}"
            if fits(candidate):
                line = candidate
                continue
            if line:
                out.append(line)
                line = ""
            if fits(word):
                line = word
                continue
            for ch in word:  # hard-break an over-long word
                if fits(line + ch):
                    line += ch
                else:
                    out.append(line)
                    line = ch
        out.append(line)
    return out
