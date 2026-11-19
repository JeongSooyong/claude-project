import math

import numpy as np
import pytest
from PIL import Image

from shortsgen import CODE_FONT, TEXT_FONT, audio
from shortsgen.config import SAMPLE_RATE, TTS_SAMPLE_RATE
from shortsgen.models import CodeBlock, CodeRef, Scene, Script, Sentence, TechDoc
from shortsgen.render import code_card, compose, ffmpeg, fonts, layout
from shortsgen.timeline import plan

# ---------- AC-7: verbatim code ----------

# Source lines (1-based): blank first line, tab indent, trailing spaces, Korean comment, blank last line.
FIXTURE_LINES = [
    "",
    "def add(a, b):",
    "\treturn a + b  ",
    "# 두 수를 더합니다",
    "x = add(1, 2)\t# tab before comment",
    "",
]
# Hand-written expected drawn text (tabs expanded to width 4, nothing else changed).
EXPECTED_DRAWN = (
    "\n"
    "def add(a, b):\n"
    "    return a + b  \n"
    "# 두 수를 더합니다\n"
    "x = add(1, 2)   # tab before comment\n"
)


@pytest.mark.parametrize("language", ["python", None, "no-such-lang"])
def test_code_card_draws_exact_source(language):
    card = code_card.render(FIXTURE_LINES, language)
    assert card.drawn_text == EXPECTED_DRAWN


def test_code_card_range_from_block():
    block = CodeBlock(id="c1", language="python", content="\n".join(FIXTURE_LINES))
    card = code_card.render(block.line_range(2, 3), "python")
    assert card.drawn_text == "def add(a, b):\n    return a + b  "


def test_code_card_overflow_raises():
    with pytest.raises(code_card.CodeOverflowError):
        code_card.render(["x = " + "a" * 200], "python")
    with pytest.raises(code_card.CodeOverflowError):
        code_card.render([f"line{i}" for i in range(19)], "python")


def test_glyph_coverage():
    assert fonts.missing_glyphs("안녕하세요 (선택) abc", TEXT_FONT) == set()
    assert fonts.missing_glyphs("# 두 수를 더합니다", CODE_FONT) == set()
    assert fonts.missing_glyphs("ok \U00013000", TEXT_FONT) == {"\U00013000"}


# ---------- timeline ----------

def _script(scenes):
    return Script(title="t", description="d", hashtags=["#a"], scenes=scenes)


def _scene(sid, sentences, code=None, text="제목"):
    return Scene(id=sid, narration=sentences, on_screen_text=text, code=code, image_prompt="x")


def test_timeline_offsets_frames_and_master_length():
    script = _script([
        _scene("s1", [Sentence(text="첫 문장입니다."), Sentence(text="둘째.")]),
        _scene("s2", [Sentence(text="셋째 문장.")]),
    ])
    tl = plan.build(script, {"s1": [24000, 12000], "s2": [36000]})
    s1, s2 = tl.scenes
    # 48 kHz lengths: 48000, 24000; gap 120 ms = 5760 samples; tail 300 ms = 14400
    assert s1.sentence_lengths_samples == [48000, 24000]
    assert s1.sentence_offsets_samples == [0, 53760]
    assert s1.frames == math.ceil((53760 + 24000 + 14400) / 1600) == 58
    assert s2.start_frame == 58
    assert s2.frames == (72000 + 14400) // 1600 == 54
    assert tl.total_frames == 112
    sents = {"s1": [np.zeros(24000, np.int16), np.zeros(12000, np.int16)], "s2": [np.zeros(36000, np.int16)]}
    assert len(audio.build_master(tl, sents)) == tl.total_frames * SAMPLE_RATE // 30


def test_cues_respect_limits_and_inherit_highlight():
    long = "이 함수는 두 개의 인자를 받아서 그 합을 반환하며 타입 힌트는 사용하지 않습니다."
    script = _script([_scene("s1", [Sentence(text=long, highlight_line=3), Sentence(text="끝.")],
                             code=CodeRef(block_id="c1", start_line=2, end_line=3))])
    tl = plan.build(script, {"s1": [96000, 12000]})
    cues = tl.scenes[0].cues
    font = fonts.load(TEXT_FONT, layout.SUB_FONT_SIZE)
    assert len(cues) >= 3
    for c in cues:
        assert 1 <= len(c.lines) <= 2
        for line in c.lines:
            assert len(line) <= 16 and font.getlength(line) <= 960
        assert c.end_frame > c.start_frame
    assert [c.highlight_line for c in cues[:-1]] == [3] * (len(cues) - 1)
    assert cues[-1].highlight_line is None
    # monotonic, inside scene
    for a, b in zip(cues, cues[1:]):
        assert a.start_frame <= b.start_frame
    assert cues[-1].end_frame <= tl.scenes[0].frames


# ---------- compose (ffmpeg) ----------

def _tone(n, hz=440, rate=TTS_SAMPLE_RATE):
    t = np.arange(n) / rate
    return (np.sin(2 * np.pi * hz * t) * 12000).astype(np.int16)


def _render(tmp_path):
    doc = TechDoc(source="x.md", prose="", code_blocks=[CodeBlock(id="c1", language="python", content="\n".join(FIXTURE_LINES))])
    script = _script([
        _scene("s1", [Sentence(text="조용한 첫 장면.")]),
        _scene("s2", [Sentence(text="소리가 나는 둘째 장면.", highlight_line=3)], code=CodeRef(block_id="c1", start_line=2, end_line=5)),
        _scene("s3", [Sentence(text="마지막.")], text=""),
    ])
    sents = {
        "s1": [np.zeros(24000, np.int16)],
        "s2": [_tone(30000)],
        "s3": [np.zeros(12000, np.int16)],
    }
    tl = plan.build(script, {k: [len(a) for a in v] for k, v in sents.items()})
    bgs = {}
    for i, sid in enumerate(["s1", "s2", "s3"]):
        p = tmp_path / f"bg_{sid}.png"
        Image.new("RGB", (1024, 1536), (40 * i, 60, 120)).save(p)
        bgs[sid] = p
    out = tmp_path / "out" / "video.mp4"
    compose.render_video(tmp_path, script, doc, tl, bgs, sents, out)
    return out, tl


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    return _render(tmp_path_factory.mktemp("한글 프로젝트"))


def test_compose_format_and_duration(rendered):
    out, tl = rendered
    info = ffmpeg.probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264" and v["pix_fmt"] == "yuv420p"
    assert v["r_frame_rate"] == "30/1"
    assert a["codec_name"] == "aac" and a["sample_rate"] == "48000"
    frame = 1 / 30
    expected = tl.total_frames / 30
    assert abs(float(v["duration"]) - expected) <= frame + 1e-6
    assert abs(float(a["duration"]) - float(v["duration"])) <= frame + 1e-6
    assert abs(float(info["format"]["duration"]) - expected) <= frame + 1e-6


def test_compose_audio_sync_tone_onset(rendered):
    out, tl = rendered
    pcm = audio.pcm_bytes_to_array(ffmpeg.decode_audio(out))
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) > 2000)
    assert loud.size
    onset_frame = loud[0] / SAMPLE_RATE * 30
    assert abs(onset_frame - tl.scenes[1].start_frame) <= 1


def test_compose_korean_path(rendered):
    out, _ = rendered
    assert "한글 프로젝트" in str(out) and out.exists()


def test_failed_mux_leaves_no_output(tmp_path, monkeypatch):
    out = tmp_path / "p.mp4"

    def failing_run(args, cwd=None):
        (cwd / args[-1]).write_bytes(b"partial")  # ffmpeg wrote part of the temp file, then crashed
        raise ffmpeg.FFmpegError(args, "boom")

    monkeypatch.setattr(compose.ffmpeg, "run", failing_run)
    with pytest.raises(ffmpeg.FFmpegError):
        compose.mux(tmp_path, tmp_path / "v.mp4", tmp_path / "a.wav", out)
    assert not out.exists()


def test_scene_preview(tmp_path):
    doc = TechDoc(source="x.md", prose="", code_blocks=[])
    script = _script([_scene("s1", [Sentence(text="하나.")]), _scene("s2", [Sentence(text="둘.")])])
    sents = {"s1": [np.zeros(24000, np.int16)], "s2": [_tone(24000)]}
    tl = plan.build(script, {k: [len(a) for a in v] for k, v in sents.items()})
    bg = tmp_path / "bg.png"
    Image.new("RGB", (1024, 1536), (10, 20, 30)).save(bg)
    out = compose.render_scene_preview(tmp_path, script.scenes[1], doc, tl, bg, sents["s2"], tmp_path / "p.mp4")
    dur = float(ffmpeg.probe(out)["format"]["duration"])
    assert abs(dur - tl.scenes[1].frames / 30) <= 1 / 30 + 1e-6
