package com.tradingagents.asharescreener.data

import com.tradingagents.asharescreener.domain.ScreenedStock
import com.tradingagents.asharescreener.domain.ScreeningResult
import com.tradingagents.asharescreener.domain.StockQueryResult

class HistoryRepository(private val dao: ScreeningDao) {
    fun observeRuns() = dao.observeRuns()

    fun observeRun(runId: Long) = dao.observeRun(runId)

    fun observeStockQueries() = dao.observeStockQueries()

    fun observeStockQuery(queryId: Long) = dao.observeStockQuery(queryId)

    suspend fun save(result: ScreeningResult): Long {
        val runId = dao.insertRun(
            ScreeningRunEntity(
                createdAt = System.currentTimeMillis(),
                paramsJson = ScreenerParamsCodec.toJson(result.params),
                summaryJson = ScreeningSummaryCodec.toJson(result.summary),
                selectedCount = result.summary.selectedCount,
                screenedCount = result.stocks.size,
            )
        )
        dao.insertStocks(result.stocks.map { it.toEntity(runId) })
        return runId
    }

    suspend fun saveStockQuery(result: StockQueryResult): Long =
        dao.insertStockQuery(result.toEntity())

    suspend fun delete(runId: Long) = dao.deleteRun(runId)

    suspend fun deleteStockQuery(queryId: Long) = dao.deleteStockQuery(queryId)
}

private fun ScreenedStock.toEntity(runId: Long) = ScreenedStockEntity(
    runId = runId,
    selected = selected,
    rejectReason = rejectReason,
    code = code,
    name = name,
    price = price,
    changePct = changePct,
    volumeRatio = volumeRatio,
    turnoverPct = turnoverPct,
    floatMarketCapYi = floatMarketCapYi,
    priority = priority,
    priorityLabel = priorityLabel,
    positionLabel = positionLabel,
    klineSource = klineSource,
    klineErrors = klineErrors,
)

private fun StockQueryResult.toEntity() = StockQueryEntity(
    queriedAt = queriedAt,
    code = stock.code,
    name = stock.name,
    paramsJson = ScreenerParamsCodec.toJson(params),
    selected = stock.selected,
    rejectReason = stock.rejectReason,
    price = stock.price,
    oneLotAmount = stock.oneLotAmount,
    changePct = stock.changePct,
    volumeRatio = stock.volumeRatio,
    turnoverPct = stock.turnoverPct,
    floatMarketCapYi = stock.floatMarketCapYi,
    marketCapYi = stock.marketCapYi,
    priority = stock.priority,
    priorityLabel = stock.priorityLabel,
    actionHint = stock.actionHint,
    positionLabel = stock.positionLabel,
    recentPositionPct = stock.recentPositionPct,
    klineSource = stock.klineSource,
    klineErrors = stock.klineErrors,
)
