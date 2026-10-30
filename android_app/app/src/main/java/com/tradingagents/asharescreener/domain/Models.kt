package com.tradingagents.asharescreener.domain

data class ScreenerParams(
    val minLotAmount: Double = 2000.0,
    val maxLotAmount: Double = 3000.0,
    val minChangePct: Double = 3.0,
    val maxChangePct: Double = 5.0,
    val minVolumeRatio: Double = 1.0,
    val minTurnoverPct: Double = 5.0,
    val maxTurnoverPct: Double? = 10.0,
    val minFloatMarketCapYi: Double = 50.0,
    val maxFloatMarketCapYi: Double = 200.0,
    val volumeGrowthDays: Int = 3,
    val maSlopeDays: Int = 3,
    val klineLookbackDays: Int = 45,
    val recentPositionDays: Int = 20,
    val quoteBatchSize: Int = 80,
    val quoteBatchIntervalMs: Long = 1_000L,
    val klineRequestIntervalMs: Long = 1_800L,
    val eastmoneyMinIntervalMs: Long = 1_800L,
    val limit: Int = 50,
)

data class ScheduleSettings(
    val enabled: Boolean = false,
    val hour: Int = 14,
    val minute: Int = 30,
    val nextRunAt: Long = 0L,
    val lastRunText: String = "",
)

data class QuoteRow(
    val code: String,
    val name: String,
    val price: Double,
    val changePct: Double,
    val volumeRatio: Double,
    val turnoverPct: Double,
    val floatMarketCapYi: Double,
    val marketCapYi: Double,
    val amountWan: Double,
)

data class KlineRow(
    val date: String,
    val open: Double,
    val high: Double,
    val low: Double,
    val close: Double,
    val volume: Double,
    val amount: Double = 0.0,
)

data class KlineResult(
    val rows: List<KlineRow>,
    val source: String,
    val errors: List<String> = emptyList(),
)

data class ScreenedStock(
    val selected: Boolean,
    val rejectReason: String,
    val code: String,
    val name: String,
    val price: Double,
    val oneLotAmount: Double,
    val changePct: Double,
    val volumeRatio: Double,
    val turnoverPct: Double,
    val floatMarketCapYi: Double,
    val marketCapYi: Double,
    val priority: Int,
    val priorityLabel: String,
    val actionHint: String,
    val positionLabel: String,
    val recentPositionPct: Double?,
    val klineSource: String,
    val klineErrors: String,
)

data class ScreeningSummary(
    val asOf: String,
    val quoteCount: Int,
    val quoteFilterCount: Int,
    val selectedCount: Int,
    val rejectedCount: Int,
    val returnedCount: Int,
)

data class ScreeningResult(
    val params: ScreenerParams,
    val summary: ScreeningSummary,
    val stocks: List<ScreenedStock>,
)

data class StockQueryResult(
    val queriedAt: Long,
    val params: ScreenerParams,
    val stock: ScreenedStock,
)

sealed interface ScreeningProgress {
    data class Message(val text: String) : ScreeningProgress
}
