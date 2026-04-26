"""China social-sentiment provider adapter placeholder.

Concrete integration (Eastmoney Guba/Xueqiu/互动易) will be added in next phase.
"""

from __future__ import annotations

from .ashare_provider import NullAShareProvider

# NOTE: temporary alias keeps import surfaces stable while implementation is pending.
CNSocialProvider = NullAShareProvider
