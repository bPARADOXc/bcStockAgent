package com.tradingagents.asharescreener.export

import com.tradingagents.asharescreener.domain.ScreenerParams
import com.tradingagents.asharescreener.domain.ScreenedStock
import com.tradingagents.asharescreener.domain.ScreeningResult
import com.tradingagents.asharescreener.domain.ScreeningSummary
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HtmlReportBuilderTest {
    @Test
    fun reportContainsSelectedAndRejectedReason() {
        val result = ScreeningResult(
            params = ScreenerParams(),
            summary = ScreeningSummary("2026-06-09 14:35:00", 2, 2, 1, 1, 1),
            stocks = listOf(
                stock("600001", true, ""),
                stock("600002", false, "成交量条件不满足"),
            ),
        )

        val html = HtmlReportBuilder.buildCurrent(result)

        assertTrue(html.contains("600001"))
        assertTrue(html.contains("600002"))
        assertTrue(html.contains("成交量条件不满足"))
        assertTrue(html.contains("最终入选：1"))
    }

    @Test
    fun htmlEscapesSpecialCharacters() {
        val escaped = HtmlReportBuilder.h("<script>'&\"")

        assertFalse(escaped.contains("<script>"))
        assertTrue(escaped.contains("&lt;script&gt;"))
        assertTrue(escaped.contains("&#39;"))
        assertTrue(escaped.contains("&quot;"))
        assertTrue(escaped.contains("&amp;"))
    }

    private fun stock(code: String, selected: Boolean, reason: String) = ScreenedStock(
        selected = selected,
        rejectReason = reason,
        code = code,
        name = "测试股份",
        price = 10.0,
        oneLotAmount = 1000.0,
        changePct = 4.0,
        volumeRatio = 2.5,
        turnoverPct = 6.0,
        floatMarketCapYi = 100.0,
        marketCapYi = 120.0,
        priority = 1,
        priorityLabel = "启动信号",
        actionHint = "测试",
        positionLabel = "中位",
        recentPositionPct = 50.0,
        klineSource = "sina_kline",
        klineErrors = "",
    )
}
