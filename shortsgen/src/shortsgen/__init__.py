"""shortsgen: tech docs -> Korean YouTube Shorts."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"
TEXT_FONT = FONTS_DIR / "NotoSansKR-Bold.otf"
TEXT_FONT_REGULAR = FONTS_DIR / "NotoSansKR-Regular.otf"
CODE_FONT = FONTS_DIR / "D2Coding.ttf"
