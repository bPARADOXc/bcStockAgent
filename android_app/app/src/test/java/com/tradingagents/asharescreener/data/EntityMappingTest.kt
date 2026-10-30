package com.tradingagents.asharescreener.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class EntityMappingTest {
    @Test
    fun rejectedEntityKeepsRejectReason() {
        val entity = ScreenedStockEntity(
            runId = 1,
            selected = false,
            rejectReason = "数据未读取",
            code = "600001",
            name = "测试股份",
            price = 10.0,
            changePct = 4.0,
            volumeRatio = 2.0,
            turnoverPct = 6.0,
            floatMarketCapYi = 100.0,
            priority = 4,
            priorityLabel = "撤退风险",
            positionLabel = "未知",
            klineSource = "unavailable",
            klineErrors = "timeout",
        )

        assertFalse(entity.selected)
        assertEquals("数据未读取", entity.rejectReason)
        assertEquals("unavailable", entity.klineSource)
    }
}
