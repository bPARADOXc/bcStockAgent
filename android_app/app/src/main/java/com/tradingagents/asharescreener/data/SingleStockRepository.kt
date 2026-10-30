package com.tradingagents.asharescreener.data

import com.tradingagents.asharescreener.domain.AshareScreener
import com.tradingagents.asharescreener.domain.ScreenerParams
import com.tradingagents.asharescreener.domain.StockQueryResult
import com.tradingagents.asharescreener.network.KlineRepository
import com.tradingagents.asharescreener.network.QuoteRepository

class SingleStockRepository(
    private val quoteRepository: QuoteRepository,
    private val klineRepository: KlineRepository,
) {
    suspend fun query(input: String, params: ScreenerParams): StockQueryResult {
        val code = normalizeCode(input)
        val quote = quoteRepository.fetchTencentQuotes(listOf(code)).firstOrNull()
            ?: error("未读取到实时行情：$code")
        val kline = klineRepository.fetchRecentKlines(code, params.klineLookbackDays)
        val stock = AshareScreener(quoteRepository, klineRepository)
            .screenSingleQuote(quote, kline.rows, kline.source, kline.errors, params)
        return StockQueryResult(
            queriedAt = System.currentTimeMillis(),
            params = params,
            stock = stock,
        )
    }

    private fun normalizeCode(input: String): String {
        val compact = input.trim().lowercase()
            .removePrefix("sh")
            .removePrefix("sz")
            .filter { it.isDigit() }
        require(compact.length == 6) { "请输入6位股票代码" }
        return compact
    }
}
