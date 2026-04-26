import unittest

import pytest

from cli.utils import normalize_ticker_symbol
from tradingagents.agents.utils.agent_utils import build_instrument_context


@pytest.mark.unit
class TickerSymbolHandlingTests(unittest.TestCase):
    def test_normalize_ticker_symbol_preserves_exchange_suffix(self):
        self.assertEqual(normalize_ticker_symbol(" cnc.to "), "CNC.TO")


    def test_normalize_ticker_symbol_supports_ashare_code(self):
        # NOTE: plain 6-digit CN input should normalize to ts_code format.
        self.assertEqual(normalize_ticker_symbol("600519"), "600519.SH")

    def test_build_instrument_context_mentions_exact_symbol(self):
        context = build_instrument_context("7203.T")
        self.assertIn("7203.T", context)
        self.assertIn("exchange suffix", context)


if __name__ == "__main__":
    unittest.main()
