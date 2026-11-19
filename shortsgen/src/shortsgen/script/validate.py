"""Script validation rules (plan §3). Returns human-readable Korean issues; empty list = valid."""

from __future__ import annotations

import re

from .. import CODE_FONT, TEXT_FONT
from ..models import Script, TechDoc
from ..render import code_card, fonts, layout
from ..render.layers import title_lines

MIN_SCENES, MAX_SCENES = 3, 8
MAX_SENTENCE_CHARS = 80
MAX_TITLE, MAX_DESCRIPTION = 100, 5000
MIN_TAGS, MAX_TAGS = 1, 10
# Code-like text: backticks, braces, semicolons, arrows, scope operators, or a call like `name(`.
# Ordinary parentheses in Korean text, e.g. "(선택)", are allowed.
SCENE_ID = re.compile(r"[A-Za-z0-9_-]{1,16}")
CODE_LIKE = re.compile(r"`|[{};]|=>|::|[A-Za-z_][A-Za-z0-9_.]*\(")


def validate(script: Script, doc: TechDoc) -> list[str]:
    issues: list[str] = []
    n = len(script.scenes)
    if not MIN_SCENES <= n <= MAX_SCENES:
        issues.append(f"장면 수는 {MIN_SCENES}~{MAX_SCENES}개여야 합니다 (현재 {n}개).")
    if not 1 <= len(script.title) <= MAX_TITLE:
        issues.append(f"제목은 1~{MAX_TITLE}자여야 합니다 (현재 {len(script.title)}자).")
    if len(script.description) > MAX_DESCRIPTION:
        issues.append(f"설명은 {MAX_DESCRIPTION}자 이하여야 합니다.")
    if not MIN_TAGS <= len(script.hashtags) <= MAX_TAGS:
        issues.append(f"해시태그는 {MIN_TAGS}~{MAX_TAGS}개여야 합니다 (현재 {len(script.hashtags)}개).")
    ids = [s.id for s in script.scenes]
    if len(set(ids)) != len(ids):
        issues.append("장면 id가 중복되었습니다.")
    bad = [i for i in ids if not SCENE_ID.fullmatch(i)]
    if bad:
        issues.append(f"장면 id 형식이 잘못되었습니다: {bad}")

    for scene in script.scenes:
        p = f"[{scene.id}]"
        code_lines: list[str] = []
        if scene.code is not None:
            ref = scene.code
            block = doc.block(ref.block_id)
            if block is None:
                issues.append(f"{p} 존재하지 않는 코드 블록 '{ref.block_id}'.")
            elif not 1 <= ref.start_line <= ref.end_line <= len(block.lines):
                issues.append(f"{p} 코드 줄 범위 {ref.start_line}-{ref.end_line}가 블록 범위(1-{len(block.lines)})를 벗어났습니다.")
            elif ref.end_line - ref.start_line + 1 > code_card.MAX_LINES:
                issues.append(f"{p} 코드는 최대 {code_card.MAX_LINES}줄까지 보여줄 수 있습니다.")
            else:
                code_lines = block.line_range(ref.start_line, ref.end_line)
                try:
                    code_card.fit_font_size(code_card.prepare(code_lines))
                except code_card.CodeOverflowError:
                    issues.append(f"{p} 코드 줄이 너무 길어 {code_card.MIN_FONT}px로도 화면에 들어가지 않습니다. 범위를 줄여 주세요.")
                missing = fonts.missing_glyphs(code_card.prepare(code_lines), CODE_FONT)
                if missing:
                    issues.append(f"{p} 코드 폰트에 없는 문자: {''.join(sorted(missing))}")

        if CODE_LIKE.search(scene.on_screen_text):
            issues.append(f"{p} 화면 문구에 코드처럼 보이는 텍스트가 있습니다. 코드는 code 범위로만 보여 주세요.")
        if len(title_lines(scene.on_screen_text)) > layout.TITLE_MAX_LINES:
            issues.append(f"{p} 화면 문구가 {layout.TITLE_MAX_LINES}줄을 넘습니다.")

        if not scene.narration:
            issues.append(f"{p} 내레이션이 비어 있습니다.")
        for i, sent in enumerate(scene.narration, start=1):
            if not sent.text.strip():
                issues.append(f"{p} {i}번째 문장이 비어 있습니다.")
            elif len(sent.text) > MAX_SENTENCE_CHARS:
                issues.append(f"{p} {i}번째 문장이 {MAX_SENTENCE_CHARS}자를 넘습니다.")
            if sent.highlight_line is not None:
                ref = scene.code
                if ref is None or not ref.start_line <= sent.highlight_line <= ref.end_line:
                    issues.append(f"{p} {i}번째 문장의 강조 줄 {sent.highlight_line}이 코드 범위 밖입니다.")

        text = scene.on_screen_text + "".join(s.text for s in scene.narration)
        missing = fonts.missing_glyphs(text, TEXT_FONT)
        if missing:
            issues.append(f"{p} 글꼴에 없는 문자: {''.join(sorted(missing))}")
    return issues
