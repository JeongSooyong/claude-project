"""Claude script writer. Tool-use JSON schema: code is referenced by block id + line range only."""

from __future__ import annotations

from ..config import Settings
from ..models import Script, TechDoc
from .base import Usage

SCRIPT_TOOL = {
    "name": "submit_script",
    "description": "Submit the YouTube Shorts script.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "YouTube 제목 (한국어, 100자 이하)"},
            "description": {"type": "string", "description": "YouTube 설명 (한국어)"},
            "hashtags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 10},
            "scenes": {
                "type": "array",
                "minItems": 3,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "s1, s2, ..."},
                        "narration": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string", "description": "한국어 내레이션 한 문장 (80자 이하)"},
                                    "highlight_line": {
                                        "type": ["integer", "null"],
                                        "description": "이 문장을 말할 때 강조할 코드 줄 번호 (블록 기준, code 범위 안)",
                                    },
                                },
                                "required": ["text"],
                            },
                        },
                        "on_screen_text": {"type": "string", "description": "화면 상단 짧은 한국어 문구. 코드 금지"},
                        "code": {
                            "type": ["object", "null"],
                            "properties": {
                                "block_id": {"type": "string"},
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                            },
                            "required": ["block_id", "start_line", "end_line"],
                        },
                        "image_prompt": {"type": "string", "description": "English prompt for an abstract background image"},
                    },
                    "required": ["id", "narration", "on_screen_text", "code", "image_prompt"],
                },
            },
        },
        "required": ["title", "description", "hashtags", "scenes"],
    },
}

SYSTEM = """당신은 개발자용 기술 문서를 30~59초 분량의 한국어 유튜브 쇼츠 대본으로 바꾸는 작가입니다.

규칙:
- 내레이션은 한국어. 함수·클래스·API 이름 등 식별자는 원문 표기 그대로 씁니다.
- 전체 내레이션은 약 40초(한국어 260~320음절)를 목표로 합니다. 문장은 짧게(80자 이하).
- 장면은 3~8개. 첫 장면은 훅, 마지막 장면은 정리.
- 코드를 절대 직접 쓰지 마세요. 코드를 보여줄 때는 code 필드에 block_id와 줄 범위(1부터 시작, 끝 줄 포함, 최대 18줄)만 지정합니다.
- highlight_line은 지정한 범위 안의 줄 번호만 사용합니다.
- on_screen_text는 짧은 한국어 문구이며 코드나 기호(`, {, }, ;, =>, ::)를 넣지 않습니다.
- image_prompt는 영어로, 글자가 없는 추상적이고 어두운 배경을 묘사합니다.
- 문서에 없는 사실을 지어내지 마세요."""


def render_doc_for_prompt(doc: TechDoc, max_chars: int = 30000) -> str:
    parts = [f"# 문서: {doc.title}\n출처: {doc.source}\n\n## 본문\n{doc.prose[:max_chars]}\n\n## 코드 블록 (줄 번호 포함)"]
    for b in doc.code_blocks:
        numbered = "\n".join(f"{i:>3}| {line}" for i, line in enumerate(b.lines, start=1))
        parts.append(f"\n### block_id={b.id} language={b.language or 'text'} lines={len(b.lines)}\n{numbered}")
    return "\n".join(parts)


class AnthropicScriptProvider:
    def __init__(self, settings: Settings, client=None):
        self.settings = settings
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=120.0, max_retries=0)
        self.client = client

    def _usd(self, in_tok: float, out_tok: float) -> float:
        p = self.settings.prices
        return in_tok / 1e6 * p["script_input_per_mtok"] + out_tok / 1e6 * p["script_output_per_mtok"]

    def estimate_usd(self, doc: TechDoc) -> float:
        return self._usd(len(render_doc_for_prompt(doc)) / 2 + 1500, 3000)

    def generate(self, doc: TechDoc) -> tuple[Script, Usage]:
        msg = self.client.messages.create(
            model=self.settings.script_model,
            max_tokens=4000,
            system=SYSTEM,
            tools=[SCRIPT_TOOL],
            tool_choice={"type": "tool", "name": "submit_script"},
            messages=[{"role": "user", "content": render_doc_for_prompt(doc)}],
        )
        block = next(b for b in msg.content if getattr(b, "type", None) == "tool_use")
        script = Script.model_validate(block.input)
        usage = msg.usage
        usd = self._usd(usage.input_tokens, usage.output_tokens)
        return script, Usage("script", usage.input_tokens + usage.output_tokens, "tokens", usd)
