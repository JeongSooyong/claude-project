"""Script generation: cost check -> provider (with retries) -> ledger -> validation."""

from __future__ import annotations

from ..cost import CostGuard
from ..models import Script, TechDoc
from ..providers.base import ScriptProvider
from ..providers.retry import with_retries
from .validate import validate


def generate_script(doc: TechDoc, provider: ScriptProvider, guard: CostGuard | None = None) -> tuple[Script, list[str]]:
    if guard is not None:
        guard.check(provider.estimate_usd(doc))
    script, usage = with_retries(lambda: provider.generate(doc))
    if guard is not None:
        guard.record(usage)
    # Scene ids end up in file names and the ffmpeg concat list: never trust model output for them.
    script = script.model_copy(
        update={"scenes": [s.model_copy(update={"id": f"s{i}"}) for i, s in enumerate(script.scenes, start=1)]}
    )
    return script, validate(script, doc)
