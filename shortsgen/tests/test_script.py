import pytest

from shortsgen.models import CodeBlock, CodeRef, Scene, Script, Sentence, TechDoc
from shortsgen.providers.fake import FakeScriptProvider
from shortsgen.script.generate import generate_script
from shortsgen.script.validate import validate

DOC = TechDoc(
    source="x.md",
    title="json",
    prose="p",
    code_blocks=[
        CodeBlock(id="c1", language="python", content="\n".join(f"x{i} = {i}" for i in range(1, 31))),
        CodeBlock(id="c2", language="python", content="y = '" + "a" * 120 + "'"),
    ],
)


def scene(sid="s1", **kw):
    base = dict(id=sid, narration=[Sentence(text="문장입니다.")], on_screen_text="소개", code=None, image_prompt="dark")
    base.update(kw)
    return Scene(**base)


def script(scenes=None, **kw):
    base = dict(title="제목", description="설명", hashtags=["#a"],
                scenes=scenes or [scene("s1"), scene("s2"), scene("s3")])
    base.update(kw)
    return Script(**base)


def issues_for(**kw):
    return validate(script(**kw), DOC)


def test_valid_script_has_no_issues():
    assert validate(script(), DOC) == []


@pytest.mark.parametrize("n", [2, 9])
def test_scene_count(n):
    assert any("장면 수" in i for i in issues_for(scenes=[scene(f"s{k}") for k in range(n)]))


@pytest.mark.parametrize(
    "code, needle",
    [
        (CodeRef(block_id="zz", start_line=1, end_line=2), "존재하지 않는"),
        (CodeRef(block_id="c1", start_line=0, end_line=2), "범위"),
        (CodeRef(block_id="c1", start_line=5, end_line=31), "범위"),
        (CodeRef(block_id="c1", start_line=1, end_line=19), "최대 18줄"),
        (CodeRef(block_id="c2", start_line=1, end_line=1), "너무 길어"),
    ],
)
def test_code_ref_rules(code, needle):
    issues = issues_for(scenes=[scene("s1", code=code), scene("s2"), scene("s3")])
    assert any(needle in i for i in issues), issues


@pytest.mark.parametrize("text", ["`x`", "{ a }", "a; b", "x => y", "std::vec", "print(1)", "json.dumps( 쓰기"])
def test_code_like_on_screen_text_rejected(text):
    assert any("코드처럼" in i for i in issues_for(scenes=[scene("s1", on_screen_text=text), scene("s2"), scene("s3")]))


@pytest.mark.parametrize("text", ["(선택) 옵션 정리", "3가지 방법 (기초)", "a = b 비교"])
def test_ordinary_korean_parentheses_allowed(text):
    assert issues_for(scenes=[scene("s1", on_screen_text=text), scene("s2"), scene("s3")]) == []


def test_highlight_line_must_be_in_range():
    s = scene("s1", code=CodeRef(block_id="c1", start_line=2, end_line=4),
              narration=[Sentence(text="좋아요.", highlight_line=5)])
    assert any("강조 줄" in i for i in issues_for(scenes=[s, scene("s2"), scene("s3")]))
    s_ok = s.model_copy(update={"narration": [Sentence(text="좋아요.", highlight_line=4)]})
    assert issues_for(scenes=[s_ok, scene("s2"), scene("s3")]) == []
    no_code = scene("s1", narration=[Sentence(text="좋아요.", highlight_line=1)])
    assert any("강조 줄" in i for i in issues_for(scenes=[no_code, scene("s2"), scene("s3")]))


def test_sentence_rules():
    long = scene("s1", narration=[Sentence(text="가" * 81)])
    assert any("80자" in i for i in issues_for(scenes=[long, scene("s2"), scene("s3")]))
    empty = scene("s1", narration=[])
    assert any("비어" in i for i in issues_for(scenes=[empty, scene("s2"), scene("s3")]))


def test_metadata_rules():
    assert any("제목" in i for i in issues_for(title="가" * 101))
    assert any("제목" in i for i in issues_for(title=""))
    assert any("설명" in i for i in issues_for(description="가" * 5001))
    assert any("해시태그" in i for i in issues_for(hashtags=[]))
    assert any("해시태그" in i for i in issues_for(hashtags=[f"#t{i}" for i in range(11)]))


def test_missing_glyph_rejected():
    s = scene("s1", narration=[Sentence(text="이상한 문자 \U00013000")])
    assert any("글꼴" in i for i in issues_for(scenes=[s, scene("s2"), scene("s3")]))


def test_bad_scene_ids_rejected_and_renumbered_after_generation():
    bad = [scene("../x"), scene("a'b"), scene("s3")]
    assert any("id 형식" in i for i in issues_for(scenes=bad))

    class Evil:
        def estimate_usd(self, doc):
            return 0.0

        def generate(self, doc):
            from shortsgen.providers.base import Usage

            return script(scenes=bad), Usage("script", 0, "tokens", 0.0)

    sc, issues = generate_script(DOC, Evil())
    assert [s.id for s in sc.scenes] == ["s1", "s2", "s3"]
    assert issues == []


def test_generate_with_fake_provider_is_valid():
    doc = TechDoc(source="x.md", title="json 모듈", prose="p",
                  code_blocks=[CodeBlock(id="c1", language="python", content="import json\njson.dumps([1])")])
    sc, issues = generate_script(doc, FakeScriptProvider())
    assert issues == []
    assert 3 <= len(sc.scenes) <= 8
