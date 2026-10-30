package com.tradingagents.asharescreener.data

import com.tradingagents.asharescreener.domain.ScreenerParams
import com.tradingagents.asharescreener.domain.ScreeningSummary
import org.json.JSONObject

object ScreenerParamsCodec {
    fun toJson(params: ScreenerParams): String = JSONObject()
        .put("minLotAmount", params.minLotAmount)
        .put("maxLotAmount", params.maxLotAmount)
        .put("minChangePct", params.minChangePct)
        .put("maxChangePct", params.maxChangePct)
        .put("minVolumeRatio", params.minVolumeRatio)
        .put("minTurnoverPct", params.minTurnoverPct)
        .put("maxTurnoverPct", params.maxTurnoverPct ?: JSONObject.NULL)
        .put("minFloatMarketCapYi", params.minFloatMarketCapYi)
        .put("maxFloatMarketCapYi", params.maxFloatMarketCapYi)
        .put("volumeGrowthDays", params.volumeGrowthDays)
        .put("maSlopeDays", params.maSlopeDays)
        .put("klineLookbackDays", params.klineLookbackDays)
        .put("recentPositionDays", params.recentPositionDays)
        .put("quoteBatchSize", params.quoteBatchSize)
        .put("quoteBatchIntervalMs", params.quoteBatchIntervalMs)
        .put("klineRequestIntervalMs", params.klineRequestIntervalMs)
        .put("eastmoneyMinIntervalMs", params.eastmoneyMinIntervalMs)
        .put("limit", params.limit)
        .toString()

    fun fromJson(json: String): ScreenerParams {
        if (json.isBlank()) return ScreenerParams()
        val obj = JSONObject(json)
        return ScreenerParams(
            minLotAmount = obj.optDouble("minLotAmount", 2000.0),
            maxLotAmount = obj.optDouble("maxLotAmount", 3000.0),
            minChangePct = obj.optDouble("minChangePct", 3.0),
            maxChangePct = obj.optDouble("maxChangePct", 5.0),
            minVolumeRatio = obj.optDouble("minVolumeRatio", 1.0),
            minTurnoverPct = obj.optDouble("minTurnoverPct", 5.0),
            maxTurnoverPct = when {
                !obj.has("maxTurnoverPct") -> 10.0
                obj.isNull("maxTurnoverPct") -> null
                else -> obj.optDouble("maxTurnoverPct", 10.0)
            },
            minFloatMarketCapYi = obj.optDouble("minFloatMarketCapYi", 50.0),
            maxFloatMarketCapYi = obj.optDouble("maxFloatMarketCapYi", 200.0),
            volumeGrowthDays = obj.optInt("volumeGrowthDays", 3),
            maSlopeDays = obj.optInt("maSlopeDays", 3),
            klineLookbackDays = obj.optInt("klineLookbackDays", 45),
            recentPositionDays = obj.optInt("recentPositionDays", 20),
            quoteBatchSize = obj.optInt("quoteBatchSize", 80),
            quoteBatchIntervalMs = obj.optLong("quoteBatchIntervalMs", 1_000L),
            klineRequestIntervalMs = obj.optLong("klineRequestIntervalMs", 1_800L),
            eastmoneyMinIntervalMs = obj.optLong("eastmoneyMinIntervalMs", 1_800L),
            limit = obj.optInt("limit", 50),
        )
    }
}

object ScreeningSummaryCodec {
    fun toJson(summary: ScreeningSummary): String = JSONObject()
        .put("asOf", summary.asOf)
        .put("quoteCount", summary.quoteCount)
        .put("quoteFilterCount", summary.quoteFilterCount)
        .put("selectedCount", summary.selectedCount)
        .put("rejectedCount", summary.rejectedCount)
        .put("returnedCount", summary.returnedCount)
        .toString()
}
