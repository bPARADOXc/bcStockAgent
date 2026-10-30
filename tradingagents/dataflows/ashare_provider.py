"""Provider contracts and payload models for A-share data adapters.

The goal is to keep analyst modules provider-agnostic: analysts consume unified
payloads while concrete integrations (AkShare/Tushare/Eastmoney/...) live behind
this interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Protocol


StatusType = Literal["ok", "unavailable", "error"]
FallbackLevel = Literal["none", "equivalent", "partial", "diagnostic"]


@dataclass
class ProviderEnvelope:
    """Common response envelope for all A-share provider outputs."""

    status: StatusType
    source: str
    as_of: str
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    contract_fulfilled: bool = True
    fallback_level: FallbackLevel = "none"

    def __post_init__(self) -> None:
        if self.status != "ok":
            self.contract_fulfilled = False


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

    def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        """Fetch OHLCV rows for a date range."""

    def get_indicators(
        self, symbol: str, indicator: str, curr_date: str, look_back_days: int = 30
    ) -> ProviderEnvelope:
        """Fetch or calculate a technical indicator window."""

    def get_research_reports(self, symbol: str, max_pages: int = 1) -> ProviderEnvelope:
        """Fetch analyst research reports."""

    def get_iwencai_reports(self, query: str, limit: int = 50) -> ProviderEnvelope:
        """Fetch semantic research-report search results when iwencai credentials exist."""

    def get_announcements(self, symbol: str, page_size: int = 30) -> ProviderEnvelope:
        """Fetch listed-company announcements."""

    def get_global_news(self, curr_date: str, look_back_days: int = 7, limit: int = 50) -> ProviderEnvelope:
        """Fetch broad market and macro news."""

    def get_financial_report(self, symbol: str, report_type: str, num: int = 8) -> ProviderEnvelope:
        """Fetch one financial statement type."""

    def get_capital_flow(self, symbol: str) -> ProviderEnvelope:
        """Fetch capital-flow evidence."""

    def get_concept_blocks(self, symbol: str) -> ProviderEnvelope:
        """Fetch industry/concept block membership."""

    def get_dragon_tiger(self, symbol: str, trade_date: str, look_back: int = 30) -> ProviderEnvelope:
        """Fetch dragon-tiger-board records."""

    def get_lockup_expiry(self, symbol: str, trade_date: str, forward_days: int = 90) -> ProviderEnvelope:
        """Fetch lockup expiry evidence."""

    def get_margin_trading(self, symbol: str, page_size: int = 30) -> ProviderEnvelope:
        """Fetch margin trading records."""

    def get_block_trades(self, symbol: str, page_size: int = 20) -> ProviderEnvelope:
        """Fetch block trade records."""

    def get_holder_changes(self, symbol: str, page_size: int = 10) -> ProviderEnvelope:
        """Fetch shareholder-count changes."""

    def get_dividends(self, symbol: str, page_size: int = 20) -> ProviderEnvelope:
        """Fetch dividend history."""

    def get_industry_comparison(self, top_n: int = 20) -> ProviderEnvelope:
        """Fetch industry comparison/ranking data."""

    def get_full_valuation(self, symbol: str) -> ProviderEnvelope:
        """Fetch a combined valuation summary."""

    def get_f10(self, symbol: str, category: str = "最新提示") -> ProviderEnvelope:
        """Fetch mootdx F10 text."""


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

    def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        return self._unavailable(f"stock data unavailable for {symbol} ({start_date}~{end_date})")

    def get_indicators(
        self, symbol: str, indicator: str, curr_date: str, look_back_days: int = 30
    ) -> ProviderEnvelope:
        return self._unavailable(f"indicator {indicator} unavailable for {symbol} as of {curr_date}")

    def get_research_reports(self, symbol: str, max_pages: int = 1) -> ProviderEnvelope:
        return self._unavailable(f"research reports unavailable for {symbol}")

    def get_iwencai_reports(self, query: str, limit: int = 50) -> ProviderEnvelope:
        return self._unavailable("iwencai report search unavailable")

    def get_announcements(self, symbol: str, page_size: int = 30) -> ProviderEnvelope:
        return self._unavailable(f"announcements unavailable for {symbol}")

    def get_global_news(self, curr_date: str, look_back_days: int = 7, limit: int = 50) -> ProviderEnvelope:
        return self._unavailable(f"global news unavailable as of {curr_date}")

    def get_financial_report(self, symbol: str, report_type: str, num: int = 8) -> ProviderEnvelope:
        return self._unavailable(f"{report_type} unavailable for {symbol}")

    def get_capital_flow(self, symbol: str) -> ProviderEnvelope:
        return self._unavailable(f"capital flow unavailable for {symbol}")

    def get_concept_blocks(self, symbol: str) -> ProviderEnvelope:
        return self._unavailable(f"concept blocks unavailable for {symbol}")

    def get_dragon_tiger(self, symbol: str, trade_date: str, look_back: int = 30) -> ProviderEnvelope:
        return self._unavailable(f"dragon tiger board unavailable for {symbol}")

    def get_lockup_expiry(self, symbol: str, trade_date: str, forward_days: int = 90) -> ProviderEnvelope:
        return self._unavailable(f"lockup expiry unavailable for {symbol}")

    def get_margin_trading(self, symbol: str, page_size: int = 30) -> ProviderEnvelope:
        return self._unavailable(f"margin trading unavailable for {symbol}")

    def get_block_trades(self, symbol: str, page_size: int = 20) -> ProviderEnvelope:
        return self._unavailable(f"block trades unavailable for {symbol}")

    def get_holder_changes(self, symbol: str, page_size: int = 10) -> ProviderEnvelope:
        return self._unavailable(f"holder changes unavailable for {symbol}")

    def get_dividends(self, symbol: str, page_size: int = 20) -> ProviderEnvelope:
        return self._unavailable(f"dividends unavailable for {symbol}")

    def get_industry_comparison(self, top_n: int = 20) -> ProviderEnvelope:
        return self._unavailable("industry comparison unavailable")

    def get_full_valuation(self, symbol: str) -> ProviderEnvelope:
        return self._unavailable(f"full valuation unavailable for {symbol}")

    def get_f10(self, symbol: str, category: str = "最新提示") -> ProviderEnvelope:
        return self._unavailable(f"F10 {category} unavailable for {symbol}")
