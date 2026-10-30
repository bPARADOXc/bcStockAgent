package com.tradingagents.asharescreener.notification

import com.tradingagents.asharescreener.domain.ScreenerParams
import com.tradingagents.asharescreener.domain.ScreenedStock
import com.tradingagents.asharescreener.domain.ScreeningResult
import com.tradingagents.asharescreener.domain.ScreeningSummary
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NotificationTextBuilderTest {
    @Test
    fun completionTextIncludesCountsAndTopThree() {
        val result = ScreeningResult(
            params = ScreenerParams(),
            summary = ScreeningSummary("2026-06-10 14:30:00", 10, 5, 4, 1, 4),
            stocks = listOf(
                stock("600001", true),
                stock("600002", true),
                stock("600003", true),
                stock("600004", true),
                stock("600005", false),
            ),
        )

        val text = NotificationTextBuilder.completedText(result)

        assertTrue(text.contains("入选 4"))
        assertTrue(text.contains("筛过 5"))
        assertTrue(text.contains("600001"))
        assertTrue(text.contains("600003"))
        assertFalse(text.contains("600004 测试600004"))
    }

    private fun stock(code: String, selected: Boolean) = ScreenedStock(
        selected = selected,
        rejectReason = if (selected) "" else "成交量条件不满足",
        code = code,
        name = "测试$code",
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
