from PIL import ImageFont

import shortsgen


def test_package_imports_and_fonts_load():
    for path in (shortsgen.TEXT_FONT, shortsgen.TEXT_FONT_REGULAR, shortsgen.CODE_FONT):
        assert path.exists(), path
        font = ImageFont.truetype(str(path), 40)
        assert font.getbbox("가나다 abc")[2] > 0
