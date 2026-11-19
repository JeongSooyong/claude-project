"""The only text normalizations applied to code:

1. CRLF / CR -> LF.
2. Block boundaries: one leading newline directly after <pre> (browsers hide it) and
   one trailing newline before the block end (fence/pre terminator) are dropped.
   Neither is visible on the source page.
"""


def newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def strip_one_trailing_newline(text: str) -> str:
    return text[:-1] if text.endswith("\n") else text
