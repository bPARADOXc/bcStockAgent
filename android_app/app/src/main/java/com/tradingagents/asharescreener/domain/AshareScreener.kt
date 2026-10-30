package com.tradingagents.asharescreener.domain

import com.tradingagents.asharescreener.network.KlineRepository
import com.tradingagents.asharescreener.network.QuoteRepository
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import kotlin.math.max
import kotlin.math.round

class AshareScreener(
    private val quoteRepository: QuoteRepository,
    private val klineRepository: KlineRepository,
) {
    suspend fun run(
        params: ScreenerParams,
        progress: (String) -> Unit,
    ): ScreeningResult {
        val codes = generateMainBoardCodes()
        progress("阶段1/4：开始获取实时行情，共 ${codes.size} 个代码。")
        val quotes = mutableListOf<QuoteRow>()
        codes.chunked(params.quoteBatchSize).forEachIndexed { index, batch ->
            progress("阶段1/4：行情批次 ${index + 1}，${batch.first()}-${batch.last()}。")
            runCatching { quoteRepository.fetchTencentQuotes(batch) }
                .onSuccess { quotes += it }
                .onFailure { progress("行情批次失败：${it.message}") }
            if (index < codes.size / params.quoteBatchSize) delay(params.quoteBatchIntervalMs)
        }

        val quotePassed = quotes.filter { passesQuoteFilters(it, params) }
        progress("阶段2/4：实时行情 ${quotes.size} 条，报价条件通过 ${quotePassed.size} 条。")

        val screened = mutableListOf<ScreenedStock>()
        quotePassed.forEachIndexed { index, quote ->
            if (index > 0) delay(params.klineRequestIntervalMs)
            progress("阶段3/4：校验K线 ${index + 1}/${quotePassed.size}：${quote.code} ${quote.name}")
            val kline = klineRepository.fetchRecentKlines(quote.code, params.klineLookbackDays)
            val stock = screenQuote(quote, kline.rows, kline.source, kline.errors, params)
            screened += stock
            if (stock.selected) progress("命中候选：${stock.code} ${stock.name} P${stock.priority} ${stock.priorityLabel}")
        }

        val selected = screened.filter { it.selected }
            .sortedWith(compareBy<ScreenedStock> { it.priority }.thenByDescending { it.volumeRatio })
        val selectedForTop = selected.take(params.limit)
        val output = selected + screened.filterNot { selected.contains(it) }
        progress("阶段4/4：完成，最终入选 ${selected.size} 条，全部保存 ${screened.size} 条。")

        return ScreeningResult(
            params = params,
            summary = ScreeningSummary(
                asOf = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")),
                quoteCount = quotes.size,
                quoteFilterCount = quotePassed.size,
                selectedCount = selected.size,
                rejectedCount = max(screened.size - selected.size, 0),
                returnedCount = selectedForTop.size,
            ),
            stocks = output,
        )
    }

    internal fun screenQuote(
        quote: QuoteRow,
        rows: List<KlineRow>,
        source: String,
        errors: List<String>,
        params: ScreenerParams,
    ): ScreenedStock {
        val priority = prioritySignal(quote.turnoverPct, quote.volumeRatio)
        val eval = evaluateKlines(rows, params)
        val selected = eval.volumeOk && eval.maOk
        return ScreenedStock(
            selected = selected,
            rejectReason = if (selected) "" else rejectReason(eval, errors),
            code = quote.code,
            name = quote.name,
            price = quote.price,
            oneLotAmount = round2(quote.price * 100),
            changePct = quote.changePct,
            volumeRatio = quote.volumeRatio,
            turnoverPct = quote.turnoverPct,
            floatMarketCapYi = quote.floatMarketCapYi,
            marketCapYi = quote.marketCapYi,
            priority = priority.first,
            priorityLabel = priority.second,
            actionHint = priority.third,
            positionLabel = eval.positionLabel,
            recentPositionPct = eval.positionPct,
            klineSource = source,
            klineErrors = errors.joinToString("；"),
        )
    }

    internal fun screenSingleQuote(
        quote: QuoteRow,
        rows: List<KlineRow>,
        source: String,
        errors: List<String>,
        params: ScreenerParams,
    ): ScreenedStock {
        val klineStock = screenQuote(quote, rows, source, errors, params)
        val quoteReasons = quoteRejectReasons(quote, params)
        val reasons = buildList {
            addAll(quoteReasons)
            if (!klineStock.selected && klineStock.rejectReason.isNotBlank()) add(klineStock.rejectReason)
        }
        return if (reasons.isEmpty()) {
            klineStock
        } else {
            klineStock.copy(selected = false, rejectReason = reasons.joinToString("；"))
        }
    }
}

private data class KlineEval(
    val volumeOk: Boolean,
    val maOk: Boolean,
    val positionLabel: String,
    val positionPct: Double?,
    val reason: String,
)

private fun evaluateKlines(rows: List<KlineRow>, params: ScreenerParams): KlineEval {
    if (rows.size < 20) return KlineEval(false, false, "未知", null, "数据不足：K线仅 ${rows.size} 条，无法稳定判断MA20。")
    val sorted = rows.sortedBy { it.date }
    val volumeWindow = sorted.takeLast(max(params.volumeGrowthDays, 2)).map { it.volume }
    val volumeOk = volumeWindow.zipWithNext().all { (prev, curr) -> curr > prev }
    val maOk = listOf(5, 10, 20).all { window -> maUp(sorted.map { it.close }, window, max(params.maSlopeDays, 2)) }
    val pos = recentPosition(sorted, params.recentPositionDays)
    return KlineEval(volumeOk, maOk, pos.first, pos.second, "")
}

private fun maUp(closes: List<Double>, window: Int, slopeDays: Int): Boolean {
    val mas = closes.mapIndexedNotNull { idx, _ ->
        if (idx + 1 < window) null else closes.subList(idx + 1 - window, idx + 1).average()
    }.takeLast(slopeDays)
    return mas.size >= slopeDays && mas.zipWithNext().all { (prev, curr) -> curr >= prev } && mas.last() > mas.first()
}

private fun recentPosition(rows: List<KlineRow>, days: Int): Pair<String, Double?> {
    val win = rows.takeLast(max(days, 2))
    if (win.isEmpty()) return "未知" to null
    val high = win.maxOf { it.high }
    val low = win.minOf { it.low }
    val close = win.last().close
    val pct = if (high <= low) 50.0 else (close - low) / (high - low) * 100
    val label = when {
        pct <= 35 -> "低位"
        pct >= 70 -> "高位"
        else -> "中位"
    }
    return label to round2(pct)
}

private fun rejectReason(eval: KlineEval, errors: List<String>): String {
    if (eval.positionLabel == "未知" && errors.isNotEmpty()) return "数据未读取：${errors.joinToString("；")}"
    val reasons = mutableListOf<String>()
    if (!eval.volumeOk) reasons += "成交量条件不满足"
    if (!eval.maOk) reasons += "均线条件不满足"
    return reasons.joinToString("；").ifBlank { eval.reason.ifBlank { "K线/MA/成交量条件不满足" } }
}

private fun passesQuoteFilters(q: QuoteRow, p: ScreenerParams): Boolean {
    return quoteRejectReasons(q, p).isEmpty()
}

internal fun quoteRejectReasons(q: QuoteRow, p: ScreenerParams): List<String> {
    val reasons = mutableListOf<String>()
    val name = q.name.uppercase()
    if (name.contains("ST") || name.contains("退")) reasons += "ST/退市风险名称过滤"
    if (!q.code.startsWith("600") && !q.code.startsWith("601") && !q.code.startsWith("603") &&
        !q.code.startsWith("605") && !q.code.startsWith("000") && !q.code.startsWith("001") &&
        !q.code.startsWith("002") && !q.code.startsWith("003")
    ) reasons += "非A股主板代码范围"
    val lot = q.price * 100
    if (lot !in p.minLotAmount..p.maxLotAmount) reasons += "一手金额不在 ${p.minLotAmount}-${p.maxLotAmount}"
    if (q.changePct !in p.minChangePct..p.maxChangePct) reasons += "涨幅不在 ${p.minChangePct}-${p.maxChangePct}%"
    if (q.volumeRatio <= p.minVolumeRatio) reasons += "量比未大于 ${p.minVolumeRatio}"
    if (q.turnoverPct < p.minTurnoverPct) reasons += "换手率低于 ${p.minTurnoverPct}%"
    if (p.maxTurnoverPct != null && q.turnoverPct > p.maxTurnoverPct) reasons += "换手率高于 ${p.maxTurnoverPct}%"
    if (q.floatMarketCapYi !in p.minFloatMarketCapYi..p.maxFloatMarketCapYi) {
        reasons += "流通市值不在 ${p.minFloatMarketCapYi}-${p.maxFloatMarketCapYi}亿"
    }
    return reasons
}

private fun prioritySignal(turnoverPct: Double, volumeRatio: Double): Triple<Int, String, String> = when {
    turnoverPct > 5 && volumeRatio in 2.0..3.0 -> Triple(1, "启动信号", "换手率>5%、量比2-3")
    turnoverPct in 5.0..10.0 && volumeRatio > 3 && volumeRatio <= 5 -> Triple(2, "资金加速主升浪", "换手率5%-10%、量比3-5")
    turnoverPct > 10 && volumeRatio > 5 -> Triple(3, "高换手高量比", "需结合位置判断低位吸筹或高位出货")
    turnoverPct > 5 && volumeRatio < 2 -> Triple(4, "撤退风险", "换手率>5%、量比<2")
    else -> Triple(99, "未命中优先级", "未命中四条优先级规则")
}

private fun generateMainBoardCodes(): List<String> =
    listOf("600", "601", "603", "605", "000", "001", "002", "003")
        .flatMap { prefix -> (0..999).map { "$prefix${it.toString().padStart(3, '0')}" } }

private fun round2(value: Double): Double = round(value * 100.0) / 100.0
