"""Per-project cost ledger (cost.json) with a hard ceiling."""

from __future__ import annotations

from .config import Settings
from .models import CostEntry
from .providers.base import Usage
from .storage import Storage


class CostCeilingError(RuntimeError):
    pass


class CostGuard:
    def __init__(self, storage: Storage, project_id: str, settings: Settings):
        self.storage = storage
        self.project_id = project_id
        self.settings = settings

    def spent_usd(self) -> float:
        return sum(e.usd for e in self.storage.cost_entries(self.project_id))

    def spent_krw(self) -> float:
        return self.spent_usd() * self.settings.usd_krw

    def check(self, estimate_usd: float) -> None:
        projected = (self.spent_usd() + estimate_usd) * self.settings.usd_krw
        if projected > self.settings.cost_ceiling_krw:
            raise CostCeilingError(
                f"예상 비용 {projected:.0f}원이 상한 {self.settings.cost_ceiling_krw:.0f}원을 넘습니다. "
                "COST_CEILING_KRW를 올리거나 재생성을 줄여 주세요."
            )

    def record(self, usage: Usage) -> None:
        self.storage.append_cost(
            self.project_id, CostEntry(kind=usage.kind, units=usage.units, unit_name=usage.unit_name, usd=usage.usd)
        )
