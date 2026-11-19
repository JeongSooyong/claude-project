import base64
from types import SimpleNamespace

import pytest

from shortsgen.config import Settings
from shortsgen.cost import CostCeilingError, CostGuard
from shortsgen.models import CodeBlock, TechDoc
from shortsgen.providers import anthropic_script, openai_image, openai_tts
from shortsgen.providers.base import Usage
from shortsgen.providers.fake import FakeImageProvider, FakeScriptProvider, FakeTTSProvider
from shortsgen.providers.retry import ProviderError, with_retries
from shortsgen.storage import Storage

DOC = TechDoc(source="x.md", title="json", prose="p", code_blocks=[CodeBlock(id="c1", language="python", content="a = 1\nb = 2")])


def test_fakes_are_deterministic():
    s1, _ = FakeScriptProvider().generate(DOC)
    s2, _ = FakeScriptProvider().generate(DOC)
    assert s1 == s2 and len(s1.scenes) >= 3
    assert FakeImageProvider().generate("p")[0] == FakeImageProvider().generate("p")[0]
    pcm, u = FakeTTSProvider(seconds_per_char=0.1).synthesize("가나다라마")
    assert len(pcm) == int(5 * 0.1 * 24000) and not pcm.any()


def test_retry_succeeds_after_transient_failures():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("slow")
        return "ok"

    assert with_retries(flaky, sleep=lambda s: None) == "ok"
    assert len(calls) == 3


def test_retry_gives_up_after_two_retries():
    calls = []

    def bad():
        calls.append(1)
        raise ConnectionError("down")

    with pytest.raises(ProviderError):
        with_retries(bad, sleep=lambda s: None)
    assert len(calls) == 3


def test_retry_does_not_retry_permanent_errors():
    calls = []

    class E(Exception):
        status_code = 401

    def bad():
        calls.append(1)
        raise E("unauthorized")

    with pytest.raises(ProviderError):
        with_retries(bad, sleep=lambda s: None)
    assert len(calls) == 1


def test_cost_ceiling_refuses_and_ledger_records(tmp_path):
    st = Storage(tmp_path)
    p = st.create(DOC)
    settings = Settings(cost_ceiling_krw=100, usd_krw=1000)
    guard = CostGuard(st, p.id, settings)
    guard.check(0.05)  # 50 KRW ok
    guard.record(Usage("image", 1, "image", 0.08))  # 80 KRW spent
    assert len(st.cost_entries(p.id)) == 1
    assert guard.spent_krw() == pytest.approx(80)
    with pytest.raises(CostCeilingError):
        guard.check(0.03)  # 80 + 30 > 100


def test_anthropic_provider_parses_tool_use_without_code_text():
    tool_input = {
        "title": "제목", "description": "설명", "hashtags": ["#a"],
        "scenes": [{"id": "s1", "narration": [{"text": "문장.", "highlight_line": 1}], "on_screen_text": "소개",
                    "code": {"block_id": "c1", "start_line": 1, "end_line": 2}, "image_prompt": "dark"}],
    }
    captured = {}

    class Msgs:
        def create(self, **kw):
            captured.update(kw)
            return SimpleNamespace(
                content=[SimpleNamespace(type="tool_use", input=tool_input)],
                usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
            )

    prov = anthropic_script.AnthropicScriptProvider(Settings(), client=SimpleNamespace(messages=Msgs()))
    script, usage = prov.generate(DOC)
    assert script.scenes[0].code.block_id == "c1"
    assert usage.usd > 0
    assert captured["tool_choice"]["name"] == "submit_script"
    assert "  1| a = 1" in captured["messages"][0]["content"]
    # schema has no field that accepts code text
    scene_props = anthropic_script.SCRIPT_TOOL["input_schema"]["properties"]["scenes"]["items"]["properties"]
    assert set(scene_props["code"]["properties"]) == {"block_id", "start_line", "end_line"}


def test_openai_providers_request_shapes():
    png = b"\x89PNG fake"
    seen = {}

    class Images:
        def generate(self, **kw):
            seen["image"] = kw
            return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(png).decode())])

    class Speech:
        def create(self, **kw):
            seen["tts"] = kw
            return SimpleNamespace(content=b"\x01\x00" * 24000)

    client = SimpleNamespace(images=Images(), audio=SimpleNamespace(speech=Speech()))
    s = Settings(image_quality="low")
    data, u = openai_image.OpenAIImageProvider(s, client).generate("dark")
    assert data == png and seen["image"]["quality"] == "low" and seen["image"]["size"] == "1024x1536"
    assert "no text" in seen["image"]["prompt"]
    pcm, u = openai_tts.OpenAITTSProvider(s, client).synthesize("안녕")
    assert seen["tts"]["response_format"] == "pcm"
    assert len(pcm) == 24000 and u.units == pytest.approx(1.0)
