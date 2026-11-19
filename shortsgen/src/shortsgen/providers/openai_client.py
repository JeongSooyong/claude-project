"""Shared OpenAI client factory (timeout set; retries handled by providers.retry)."""

from __future__ import annotations

from ..config import Settings


def make_client(settings: Settings, client):
    if client is not None:
        return client
    import openai

    return openai.OpenAI(api_key=settings.openai_api_key, timeout=120.0, max_retries=0)
