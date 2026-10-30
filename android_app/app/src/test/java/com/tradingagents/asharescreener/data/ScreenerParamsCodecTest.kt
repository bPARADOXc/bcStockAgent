package com.tradingagents.asharescreener.data

import com.tradingagents.asharescreener.domain.ScreenerParams
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScreenerParamsCodecTest {
    @Test
    fun nullableMaxTurnoverRoundTripsAsUnlimited() {
        val params = ScreenerParams(maxTurnoverPct = null, quoteBatchSize = 40, limit = 12)

        val decoded = ScreenerParamsCodec.fromJson(ScreenerParamsCodec.toJson(params))

        assertNull(decoded.maxTurnoverPct)
        assertEquals(40, decoded.quoteBatchSize)
        assertEquals(12, decoded.limit)
    }

    @Test
    fun missingMaxTurnoverKeepsDefaultLimit() {
        val decoded = ScreenerParamsCodec.fromJson("""{"minLotAmount":1000}""")

        assertEquals(10.0, decoded.maxTurnoverPct ?: -1.0, 0.001)
    }
}
