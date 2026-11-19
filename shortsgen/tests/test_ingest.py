"""Expected values are hand-written, not produced by the parser under test."""

import pytest

from shortsgen.ingest import IngestError, markdown, url

MD = (
    "# Tabs 가이드\r\n"
    "\r\n"
    "설명 문단입니다.\r\n"
    "\r\n"
    "```python\r\n"
    "\r\n"
    "def f():\r\n"
    "\treturn 1   \r\n"
    "# 한글 주석\r\n"
    "\r\n"
    "```\r\n"
    "\r\n"
    "중간 문단.\r\n"
    "\r\n"
    "```\r\n"
    "plain text\r\n"
    "```\r\n"
)


def test_markdown_blocks_verbatim_and_placeholders():
    doc = markdown.parse(MD)
    assert doc.title == "Tabs 가이드"
    assert [b.id for b in doc.code_blocks] == ["c1", "c2"]
    assert doc.code_blocks[0].language == "python"
    assert doc.code_blocks[0].content == "\ndef f():\n\treturn 1   \n# 한글 주석\n"
    assert doc.code_blocks[1].language is None
    assert doc.code_blocks[1].content == "plain text"
    assert doc.prose == "# Tabs 가이드\n\n설명 문단입니다.\n\n[[CODE:c1]]\n\n중간 문단.\n\n[[CODE:c2]]"


def test_markdown_without_code_errors():
    with pytest.raises(IngestError):
        markdown.parse("# 제목\n\n코드 없음")


SPHINX = """<html><head><title>json — JSON encoder</title></head><body>
<nav>menu</nav>
<div role="main"><h1>json</h1><p>Encoding basic objects:</p>
<div class="highlight-python3 notranslate"><div class="highlight"><pre><span></span><span class="gp">&gt;&gt;&gt; </span><span class="kn">import</span> <span class="nn">json</span>
<span class="gp">&gt;&gt;&gt; </span><span class="n">json</span><span class="o">.</span><span class="n">dumps</span><span class="p">([</span><span class="s1">&#39;foo&#39;</span><span class="p">])</span>
<span class="go">&#39;[&quot;foo&quot;]&#39;</span>
</pre><button class="copybutton">Copy</button></div></div>
<p>With line numbers:</p>
<div class="highlight-python notranslate"><table class="highlighttable"><tr><td class="linenos"><div class="linenodiv"><pre><span class="normal">1</span>
<span class="normal">2</span></pre></div></td><td class="code"><div class="highlight"><pre><span></span>def f():
    return 1
</pre></div></td></tr></table></div>
<p>Inline gutter:</p>
<div class="highlight-default notranslate"><div class="highlight"><pre><span></span><span class="linenos">1</span>x = 1
<span class="linenos">2</span>y = 2
</pre></div></div>
</div></body></html>"""


def test_sphinx_strips_chrome_keeps_prompts():
    doc = url.parse_html(SPHINX, "https://docs.python.org/3/library/json.html")
    assert doc.title == "json — JSON encoder"
    c1, c2, c3 = doc.code_blocks
    assert c1.content == ">>> import json\n>>> json.dumps(['foo'])\n'[\"foo\"]'"
    assert c1.language == "python3"
    assert c2.content == "def f():\n    return 1"
    assert c2.language == "python"
    assert c3.content == "x = 1\ny = 2"
    assert c3.language is None
    assert "Copy" not in doc.prose and "menu" not in doc.prose
    assert doc.prose.index("Encoding basic objects") < doc.prose.index("[[CODE:c1]]") < doc.prose.index("[[CODE:c2]]") < doc.prose.index("[[CODE:c3]]")


MDN = """<html><head><title>Array.prototype.map() - MDN</title></head><body>
<header>site header</header>
<main><article><h1>Array.prototype.map()</h1><p>The <code>map()</code> method creates a new array.</p>
<div class="code-example"><pre class="brush: js notranslate"><code class="language-js">const a = [1, 4];
const m = a.map((x) =&gt; x * 2);</code></pre></div>
<pre class="language-bash">
$ npm install<br>$ npm test</pre>
</article></main></body></html>"""


def test_mdn_language_br_and_leading_newline():
    doc = url.parse_html(MDN)
    c1, c2 = doc.code_blocks
    assert c1.content == "const a = [1, 4];\nconst m = a.map((x) => x * 2);"
    assert c1.language == "js"
    assert c2.content == "$ npm install\n$ npm test"
    assert c2.language == "bash"
    assert "[[CODE:c1]]" in doc.prose and "[[CODE:c2]]" in doc.prose
    assert "site header" not in doc.prose


def test_page_without_pre_errors():
    with pytest.raises(IngestError) as e:
        url.parse_html("<html><body><main><div id='app'></div></main></body></html>")
    assert "Markdown" in str(e.value)
