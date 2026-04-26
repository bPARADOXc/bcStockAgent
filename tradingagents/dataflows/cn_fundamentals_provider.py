"""China fundamentals provider adapter placeholder.

Concrete integration (Tushare/AkShare) will be added in next phase.
"""

from __future__ import annotations

from .ashare_provider import NullAShareProvider

# NOTE: temporary alias keeps import surfaces stable while implementation is pending.
CNFundamentalsProvider = NullAShareProvider
