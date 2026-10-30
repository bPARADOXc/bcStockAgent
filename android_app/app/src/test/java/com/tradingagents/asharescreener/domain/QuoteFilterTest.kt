package com.tradingagents.asharescreener.domain

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QuoteFilterTest {
    @Test
    fun nullMaxTurnoverDoesNotRejectHighTurnover() {
        val quote = quote(turnoverPct = 18.0)
        val params = ScreenerParams(maxTurnoverPct = null)

        val reasons = quoteRejectReasons(quote, params)

        assertFalse(reasons.any { it.contains("换手率高于") })
    }

    @Test
    fun explicitMaxTurnoverRejectsHighTurnover() {
        val quote = quote(turnoverPct = 18.0)
        val params = ScreenerParams(maxTurnoverPct = 10.0)

        val reasons = quoteRejectReasons(quote, params)

        assertTrue(reasons.any { it.contains("换手率高于") })
    }

    private fun quote(turnoverPct: Double) = QuoteRow(
        code = "600001",
        name = "测试股份",
        price = 25.0,
        changePct = 4.0,
        volumeRatio = 2.0,
        turnoverPct = turnoverPct,
        floatMarketCapYi = 100.0,
        marketCapYi = 150.0,
        amountWan = 50000.0,
    )
}
