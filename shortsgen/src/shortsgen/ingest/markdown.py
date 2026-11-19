"""Markdown ingest: fenced/indented code -> CodeBlock (verbatim), prose keeps [[CODE:id]] placeholders."""

from __future__ import annotations

from markdown_it import MarkdownIt

from ..models import CodeBlock, TechDoc
from . import IngestError
from .normalize import newlines, strip_one_trailing_newline


def placeholder(block_id: str) -> str:
    return f"[[CODE:{block_id}]]"


def parse(text: str, source: str = "document.md") -> TechDoc:
    text = newlines(text)
    md = MarkdownIt("commonmark")
    tokens = md.parse(text)
    lines = text.split("\n")
    blocks: list[CodeBlock] = []
    spans: list[tuple[int, int, str]] = []
    title = ""
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.tag == "h1" and not title:
            title = tokens[i + 1].content.strip()
        if tok.type in ("fence", "code_block") and tok.map:
            block_id = f"c{len(blocks) + 1}"
            lang = ((tok.info or "").strip().split(" ")[0] or None) if tok.type == "fence" else None
            blocks.append(CodeBlock(id=block_id, language=lang, content=strip_one_trailing_newline(tok.content)))
            spans.append((tok.map[0], tok.map[1], block_id))
    if not blocks:
        raise IngestError("문서에서 코드 블록을 찾지 못했습니다. 코드가 포함된 기술 문서를 입력해 주세요.")
    for start, end, block_id in reversed(spans):
        lines[start:end] = [placeholder(block_id)]
    return TechDoc(source=source, title=title, prose="\n".join(lines).strip(), code_blocks=blocks)
