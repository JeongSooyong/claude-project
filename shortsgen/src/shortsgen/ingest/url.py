"""URL ingest for static HTML tech docs.

Code is taken from <pre> text verbatim. Only UI chrome is removed (line-number gutters,
copy buttons). Prompt markers such as ">>> " or "$ " are kept exactly as the page shows them.
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from markdownify import markdownify

from ..models import CodeBlock, TechDoc
from . import IngestError
from .markdown import placeholder
from .normalize import newlines, strip_one_trailing_newline

CHROME_SELECTORS = [".linenos", ".linenodiv", ".copybutton", ".copy-button", "button"]
DROP_TAGS = ["script", "style", "nav", "footer", "noscript", "svg"]
NO_PRE_MESSAGE = (
    "이 페이지에서 코드 블록(<pre>)을 찾지 못했습니다. "
    "JavaScript로 렌더링되는 문서일 수 있습니다. 원본 Markdown(.md) 파일이나 raw 소스 URL을 사용해 주세요."
)
USER_AGENT = "shortsgen/0.1 (local docs-to-shorts tool)"


def fetch(url: str, timeout: float = 15.0) -> str:
    resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.text


def ingest(url: str) -> TechDoc:
    text = fetch(url)
    if url.lower().split("?")[0].endswith((".md", ".markdown")):
        from .markdown import parse

        return parse(text, source=url)
    return parse_html(text, source=url)


def _language(pre: Tag) -> str | None:
    candidates: list[Tag] = [pre]
    code = pre.find("code")
    if isinstance(code, Tag):
        candidates.insert(0, code)
    parent = pre.parent
    for _ in range(6):  # Sphinx linenos tables nest <pre> ~5 levels below div.highlight-<lang>
        if not isinstance(parent, Tag):
            break
        candidates.append(parent)
        parent = parent.parent
    for el in candidates:
        for cls in el.get("class", []) or []:
            for prefix in ("language-", "lang-", "highlight-"):
                if cls.startswith(prefix) and len(cls) > len(prefix):
                    lang = cls[len(prefix):]
                    return None if lang in ("default", "none", "text") else lang
    return None


def _container(pre: Tag) -> Tag:
    """Outermost code wrapper to replace with the placeholder (Sphinx tables / highlight divs)."""
    best = pre
    node = pre.parent
    for _ in range(5):
        if not isinstance(node, Tag):
            break
        classes = node.get("class", []) or []
        if node.name == "table" and "highlighttable" in classes:
            best = node
        elif node.name == "div" and any(c.startswith("highlight") for c in classes):
            best = node
        node = node.parent
    return best


def parse_html(html: str, source: str = "page.html") -> TechDoc:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    root = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body or soup
    for tag in root.find_all(DROP_TAGS):
        tag.decompose()
    for sel in CHROME_SELECTORS:
        for tag in root.select(sel):
            tag.decompose()

    blocks: list[CodeBlock] = []
    for pre in list(root.find_all("pre")):
        for br in pre.find_all("br"):
            br.replace_with(NavigableString("\n"))
        text = newlines(pre.get_text())
        if text.startswith("\n"):
            text = text[1:]
        text = strip_one_trailing_newline(text)
        if not text.strip():
            continue
        block_id = f"c{len(blocks) + 1}"
        blocks.append(CodeBlock(id=block_id, language=_language(pre), content=text))
        holder = soup.new_tag("p")
        holder.string = placeholder(block_id)
        _container(pre).replace_with(holder)

    if not blocks:
        raise IngestError(NO_PRE_MESSAGE)
    if not title:
        h1 = root.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
    prose = markdownify(str(root), heading_style="ATX", escape_underscores=False, escape_asterisks=False)
    prose = "\n".join(line.rstrip() for line in prose.split("\n"))
    while "\n\n\n" in prose:
        prose = prose.replace("\n\n\n", "\n\n")
    return TechDoc(source=source, title=title, prose=prose.strip(), code_blocks=blocks)
