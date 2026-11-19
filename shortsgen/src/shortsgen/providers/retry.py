"""Retries for provider calls. SDK clients are created with max_retries=0 and a timeout,
so this is the single retry layer (timeout + 2 retries with backoff)."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

ATTEMPTS = 3  # 1 try + 2 retries


class ProviderError(RuntimeError):
    pass


def with_retries(fn: Callable[[], T], attempts: int = ATTEMPTS, backoff: float = 1.0, sleep=time.sleep) -> T:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - surfaced verbatim after final attempt
            if _is_permanent(e):
                raise ProviderError(str(e)) from e
            last = e
            if i + 1 < attempts:
                sleep(backoff * (2**i))
    raise ProviderError(f"{type(last).__name__}: {last}") from last


def _is_permanent(e: Exception) -> bool:
    status = getattr(e, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and status not in (408, 409, 429)
