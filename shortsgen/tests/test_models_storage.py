from shortsgen.hashing import scene_hash
from shortsgen.models import CodeBlock, CodeRef, Scene, Script, Sentence, TechDoc
from shortsgen.storage import Storage


def _scene(**kw):
    base = dict(
        id="s1",
        narration=[Sentence(text="안녕하세요.")],
        on_screen_text="소개",
        code=CodeRef(block_id="c1", start_line=1, end_line=2),
        image_prompt="dark abstract",
    )
    base.update(kw)
    return Scene(**base)


def test_code_block_line_range_is_one_based_inclusive():
    b = CodeBlock(id="c1", content="a\nb\nc\nd")
    assert b.line_range(2, 3) == ["b", "c"]
    assert b.line_range(1, 1) == ["a"]


def test_project_round_trip(tmp_path):
    st = Storage(tmp_path)
    doc = TechDoc(source="x.md", prose="p [[CODE:c1]]", code_blocks=[CodeBlock(id="c1", content="x = 1")])
    p = st.create(doc)
    p.script = Script(title="t", description="d", hashtags=["#a"], scenes=[_scene()])
    st.save(p)
    loaded = st.load(p.id)
    assert loaded == p
    assert (tmp_path / p.id / "project.json").exists()


def test_scene_hash_stable_and_sensitive():
    a = _scene()
    assert scene_hash(a) == scene_hash(_scene())
    for change in (
        dict(on_screen_text="다른"),
        dict(image_prompt="light"),
        dict(narration=[Sentence(text="안녕.")]),
        dict(narration=[Sentence(text="안녕하세요.", highlight_line=1)]),
        dict(code=CodeRef(block_id="c1", start_line=1, end_line=3)),
    ):
        assert scene_hash(_scene(**change)) != scene_hash(a), change
