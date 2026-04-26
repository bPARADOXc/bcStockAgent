"""China news provider adapter placeholder.

Concrete integration (Eastmoney/Cninfo/SSE/SZSE) will be added in next phase.
"""

from __future__ import annotations

from .ashare_provider import NullAShareProvider

# NOTE: temporary alias keeps import surfaces stable while implementation is pending.
CNNewsProvider = NullAShareProvider
