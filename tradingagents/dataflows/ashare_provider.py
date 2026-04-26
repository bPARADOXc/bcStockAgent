"""Provider contracts and payload models for A-share data adapters.

The goal is to keep analyst modules provider-agnostic: analysts consume unified
payloads while concrete integrations (AkShare/Tushare/Eastmoney/...) live behind
this interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol


StatusType = Literal["ok", "unavailable", "error"]


@dataclass
class ProviderEnvelope:
    """Common response envelope for all A-share provider outputs."""

    status: StatusType
    source: str
    as_of: str
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)


class AShareDataProvider(Protocol):
    """Protocol for pluggable A-share providers.

    Implementations must return ProviderEnvelope and avoid raising unless
    errors are unrecoverable; normal fetch failures should map to
    status='unavailable'/'error' with diagnostic fields populated.
    """

    def get_quote(self, symbol: str, trade_date: Optional[str] = None) -> ProviderEnvelope:
        """Fetch daily quote snapshot for symbol."""

    def get_fundamentals(self, symbol: str, report_period: Optional[str] = None) -> ProviderEnvelope:
        """Fetch normalized fundamentals metrics."""

    def get_news(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        """Fetch company/industry/policy/regulatory news items."""

    def get_social(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        """Fetch social sentiment and discussion evidence."""


@dataclass
class NullAShareProvider:
    """Safe fallback provider used before concrete integrations are wired in."""

    source: str = "null_ashare_provider"

    # NOTE: return deterministic unavailable responses instead of fabricating data.
    def _unavailable(self, reason: str) -> ProviderEnvelope:
        return ProviderEnvelope(
            status="unavailable",
            source=self.source,
            as_of="",
            data={},
            errors=[reason],
            evidence=[],
        )

    def get_quote(self, symbol: str, trade_date: Optional[str] = None) -> ProviderEnvelope:
        return self._unavailable(f"quote unavailable for {symbol}")

    def get_fundamentals(self, symbol: str, report_period: Optional[str] = None) -> ProviderEnvelope:
        return self._unavailable(f"fundamentals unavailable for {symbol}")

    def get_news(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        return self._unavailable(f"news unavailable for {symbol} ({start_date}~{end_date})")

    def get_social(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        return self._unavailable(f"social unavailable for {symbol} ({start_date}~{end_date})")
