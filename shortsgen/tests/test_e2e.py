"""Offline end-to-end with fake providers (AC-9): md -> script -> images -> TTS -> approve -> render."""

import json

import numpy as np

from shortsgen import audio
from shortsgen.config import Settings
from shortsgen.providers.base import Providers
from shortsgen.providers.fake import FakeImageProvider, FakeScriptProvider, FakeTTSProvider
from shortsgen.render import code_card, ffmpeg
from shortsgen.service import Service
from shortsgen.storage import Storage

MD = (
    "# requests 빠른 시작\r\n\r\n"
    "HTTP 요청을 보내는 가장 쉬운 방법입니다.\r\n\r\n"
    "```python\r\n"
    "import requests\r\n"
    "\r\n"
    "r = requests.get('https://api.github.com/events')\r\n"
    "if r.status_code == 200:\r\n"
    "\tprint(r.json()[0]['type'])  # 첫 이벤트 종류\r\n"
    "```\r\n\r\n"
    "응답 본문은 r.text로도 볼 수 있습니다.\r\n\r\n"
    "```bash\r\n"
    "$ pip install requests\r\n"
    "```\r\n"
)


def test_offline_end_to_end(tmp_path):
    settings = Settings(projects_dir=tmp_path / "한글 경로" / "projects")
    svc = Service(
        Storage(settings.projects_dir),
        Providers(FakeScriptProvider(), FakeImageProvider(), FakeTTSProvider(seconds_per_char=0.22)),
        settings,
        uploader=None,
    )
    p = svc.create_from_markdown(MD, "requests.md")
    p, issues = svc.generate_script(p.id)
    assert issues == []
    svc.generate_missing_images(p.id)
    p, tl = svc.generate_tts(p.id)
    assert 30 <= tl.total_seconds <= 59, tl.total_seconds
    p = svc.approve(p.id)
    p = svc.render(p.id)
    assert p.state.value == "rendered", p.error
    d = svc.dir(p.id)

    # AC-10: local outputs
    out = d / "out" / "video.mp4"
    meta = json.loads((d / "out" / "metadata.json").read_text(encoding="utf-8"))
    assert out.exists() and meta["title"] and meta["description"] and meta["hashtags"]

    # AC-6: format and duration
    info = ffmpeg.probe(out)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"], v["pix_fmt"], v["r_frame_rate"]) == (1080, 1920, "yuv420p", "30/1")
    assert abs(float(v["duration"]) - tl.total_seconds) <= 1 / 30 + 1e-6
    assert abs(float(a["duration"]) - float(v["duration"])) <= 1 / 30 + 1e-6
    assert 30 <= float(info["format"]["duration"]) <= 59

    # AC-7: code shown == source text, for every scene that shows code
    shown = 0
    for scene in p.script.scenes:
        if scene.code:
            block = p.doc.block(scene.code.block_id)
            lines = block.line_range(scene.code.start_line, scene.code.end_line)
            card = code_card.render(lines, block.language)
            assert card.drawn_text == "\n".join(l.expandtabs(4) for l in lines)
            shown += 1
    assert shown == 2
    assert p.doc.block("c1").content == (
        "import requests\n\nr = requests.get('https://api.github.com/events')\n"
        "if r.status_code == 200:\n\tprint(r.json()[0]['type'])  # 첫 이벤트 종류"
    )

    # AC-8: per-scene assets and one subtitle overlay per cue
    for scene, timing in zip(p.script.scenes, tl.scenes):
        assert (d / p.assets[f"image:{scene.id}"].path).exists()
        assert (d / p.assets[f"tts:{scene.id}"].path).exists()
        sdir = d / "render" / f"scene_{scene.id}"
        assert (sdir / "fg.png").exists() and (sdir / "bg.png").exists()
        assert len(list(sdir.glob("sub_*.png"))) == len(timing.cues)
        hl_lines = {c.highlight_line for c in timing.cues if c.highlight_line}
        assert {int(x.stem[3:]) for x in sdir.glob("hl_*.png")} == hl_lines

    # master audio length matches the timeline exactly
    master, rate = audio.read_wav(d / "render" / "master.wav")
    assert rate == 48000 and len(master) == tl.total_frames * 1600
    assert isinstance(master, np.ndarray)
