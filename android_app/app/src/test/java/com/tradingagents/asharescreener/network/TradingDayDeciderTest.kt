package com.tradingagents.asharescreener.network

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class TradingDayDeciderTest {
    @Test
    fun latestDateEqualTodayMeansTradingDay() {
        assertTrue(TradingDayDecider.isTradingDay("2026-06-10", LocalDate.of(2026, 6, 10)))
    }

    @Test
    fun staleLatestDateMeansNonTradingDay() {
        assertFalse(TradingDayDecider.isTradingDay("2026-06-09", LocalDate.of(2026, 6, 10)))
    }
}
