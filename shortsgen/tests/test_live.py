"""Opt-in smoke tests against real paid APIs: `uv run pytest -m live`. Skipped without keys."""

import pytest

from shortsgen.config import Settings
from shortsgen.models import CodeBlock, TechDoc
from shortsgen.script.validate import validate

pytestmark = pytest.mark.live
S = Settings()

DOC = TechDoc(
    source="https://docs.python.org/3/library/json.html",
    title="json — JSON encoder and decoder",
    prose="json exposes an API familiar to users of the marshal and pickle modules.\n\n[[CODE:c1]]",
    code_blocks=[CodeBlock(id="c1", language="python", content=">>> import json\n>>> json.dumps(['foo', {'bar': ('baz', None, 1.0, 2)}])\n'[\"foo\", {\"bar\": [\"baz\", null, 1.0, 2]}]'")],
)


@pytest.mark.skipif(not S.anthropic_api_key, reason="ANTHROPIC_API_KEY not set")
def test_live_claude_script():
    from shortsgen.providers.anthropic_script import AnthropicScriptProvider

    script, usage = AnthropicScriptProvider(S).generate(DOC)
    assert 3 <= len(script.scenes) <= 8
    assert usage.usd > 0
    print(validate(script, DOC))


@pytest.mark.skipif(not S.openai_api_key, reason="OPENAI_API_KEY not set")
def test_live_openai_tts():
    from shortsgen.providers.openai_tts import OpenAITTSProvider

    pcm, usage = OpenAITTSProvider(S).synthesize("안녕하세요. json 모듈을 알아봅시다.")
    assert len(pcm) > 24000 * 0.5  # more than half a second of audio
    assert usage.units > 0.5
