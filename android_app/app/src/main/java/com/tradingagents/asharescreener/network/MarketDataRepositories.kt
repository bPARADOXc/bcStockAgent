package com.tradingagents.asharescreener.network

import com.tradingagents.asharescreener.domain.KlineResult
import com.tradingagents.asharescreener.domain.KlineRow
import com.tradingagents.asharescreener.domain.QuoteRow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.nio.charset.Charset
import java.time.LocalDate
import kotlin.math.max

private const val UA =
    "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Mobile Safari/537.36"

class EastmoneyRateLimiter(private val minIntervalMs: Long) {
    private val mutex = Mutex()
    private var lastAt = 0L

    suspend fun <T> run(block: suspend () -> T): T = mutex.withLock {
        val now = System.currentTimeMillis()
        val wait = minIntervalMs - (now - lastAt)
        if (wait > 0) delay(wait)
        try {
            block()
        } finally {
            lastAt = System.currentTimeMillis()
        }
    }
}

class QuoteRepository(private val client: OkHttpClient) {
    suspend fun fetchTencentQuotes(codes: List<String>): List<QuoteRow> = withContext(Dispatchers.IO) {
        if (codes.isEmpty()) return@withContext emptyList()
        val symbols = codes.joinToString(",") { "${prefixFor(it)}$it" }
        val request = Request.Builder()
            .url("https://qt.gtimg.cn/q=$symbols")
            .header("User-Agent", UA)
            .header("Referer", "https://finance.qq.com/")
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Tencent quote HTTP ${response.code}")
            val text = response.body?.bytes()?.toString(Charset.forName("GBK")).orEmpty()
            parseTencentQuotes(text)
        }
    }

    internal fun parseTencentQuotes(text: String): List<QuoteRow> =
        text.split(";").mapNotNull { line ->
            if (!line.contains("=") || !line.contains("\"")) return@mapNotNull null
            val key = line.substringBefore("=").substringAfterLast("_")
            val values = line.substringAfter("\"").substringBeforeLast("\"").split("~")
            if (values.size < 53) return@mapNotNull null
            val code = key.takeLast(6)
            val price = values[3].toDoubleOrNull() ?: 0.0
            if (price <= 0.0 || values[1].isBlank()) return@mapNotNull null
            QuoteRow(
                code = code,
                name = values[1],
                price = price,
                changePct = values[32].toDoubleOrNull() ?: 0.0,
                volumeRatio = values[49].toDoubleOrNull() ?: 0.0,
                turnoverPct = values[38].toDoubleOrNull() ?: 0.0,
                floatMarketCapYi = values[44].toDoubleOrNull() ?: 0.0,
                marketCapYi = values[45].toDoubleOrNull() ?: 0.0,
                amountWan = values[37].toDoubleOrNull() ?: 0.0,
            )
        }
}

class KlineRepository(
    private val client: OkHttpClient,
    private val eastmoneyRateLimiter: EastmoneyRateLimiter,
) {
    suspend fun fetchRecentKlines(code: String, lookbackDays: Int): KlineResult {
        val errors = mutableListOf<String>()
        for ((source, fetcher) in listOf<Pair<String, suspend () -> List<KlineRow>>>(
            "baidu_kline" to { fetchBaidu(code, lookbackDays) },
            "sina_kline" to { fetchSina(code, max(lookbackDays * 2, 80)) },
            "eastmoney_kline" to { fetchEastmoney(code, lookbackDays) },
        )) {
            try {
                val rows = fetcher().sortedBy { it.date }
                if (rows.isNotEmpty()) return KlineResult(rows, source, errors)
                errors += "$source: no records"
            } catch (exc: Exception) {
                errors += "$source: ${exc.message ?: exc::class.java.simpleName}"
            }
        }
        return KlineResult(emptyList(), "unavailable", errors)
    }

    private suspend fun fetchBaidu(code: String, lookbackDays: Int): List<KlineRow> = withContext(Dispatchers.IO) {
        val url = "https://finance.pae.baidu.com/selfselect/getstockquotation".toHttpUrl().newBuilder()
            .addQueryParameter("all", "1")
            .addQueryParameter("isIndex", "false")
            .addQueryParameter("isBk", "false")
            .addQueryParameter("isBlock", "false")
            .addQueryParameter("isFutures", "false")
            .addQueryParameter("isStock", "true")
            .addQueryParameter("newFormat", "1")
            .addQueryParameter("group", "quotation_kline_ab")
            .addQueryParameter("finClientType", "pc")
            .addQueryParameter("code", code)
            .addQueryParameter("ktype", "1")
            .build()
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", UA)
            .header("Origin", "https://gushitong.baidu.com")
            .header("Referer", "https://gushitong.baidu.com/")
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Baidu HTTP ${response.code}")
            val result = JSONObject(response.body?.string().orEmpty()).opt("Result")
            val obj = when (result) {
                is JSONObject -> result
                is JSONArray -> (0 until result.length()).mapNotNull { result.optJSONObject(it) }.firstOrNull()
                else -> null
            } ?: return@withContext emptyList()
            val md = obj.optJSONObject("newMarketData") ?: return@withContext emptyList()
            val keys = md.optJSONArray("keys")?.let { array -> List(array.length()) { array.optString(it) } }.orEmpty()
            val rawRows = md.opt("marketData")
            val rows = when (rawRows) {
                is JSONArray -> List(rawRows.length()) { rawRows.optString(it) }
                is String -> rawRows.split(";")
                else -> emptyList()
            }
            rows.mapNotNull { parseBaiduRow(keys, it) }.takeLast(max(lookbackDays, 25))
        }
    }

    private suspend fun fetchSina(code: String, dataLen: Int): List<KlineRow> = withContext(Dispatchers.IO) {
        val url = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20data=/CN_MarketDataService.getKLineData"
            .toHttpUrl().newBuilder()
            .addQueryParameter("symbol", "${prefixFor(code)}$code")
            .addQueryParameter("scale", "240")
            .addQueryParameter("ma", "no")
            .addQueryParameter("datalen", dataLen.toString())
            .build()
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", UA)
            .header("Referer", "https://finance.sina.com.cn/")
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Sina HTTP ${response.code}")
            val text = response.body?.string().orEmpty()
            val json = text.substringAfter("var data=(").substringBeforeLast(");")
            if (!json.trim().startsWith("[")) return@withContext emptyList()
            val array = JSONArray(json)
            List(array.length()) { idx ->
                val item = array.getJSONObject(idx)
                KlineRow(
                    date = item.optString("day"),
                    open = item.optDouble("open"),
                    high = item.optDouble("high"),
                    low = item.optDouble("low"),
                    close = item.optDouble("close"),
                    volume = item.optDouble("volume"),
                    amount = item.optDouble("amount"),
                )
            }
        }
    }

    private suspend fun fetchEastmoney(code: String, lookbackDays: Int): List<KlineRow> =
        eastmoneyRateLimiter.run {
            withContext(Dispatchers.IO) {
                val end = java.time.LocalDate.now()
                val begin = end.minusDays(lookbackDays.toLong())
                val url = "https://push2his.eastmoney.com/api/qt/stock/kline/get".toHttpUrl().newBuilder()
                    .addQueryParameter("secid", "${marketIdFor(code)}.$code")
                    .addQueryParameter("fields1", "f1,f2,f3,f4,f5,f6")
                    .addQueryParameter("fields2", "f51,f52,f53,f54,f55,f56,f57")
                    .addQueryParameter("klt", "101")
                    .addQueryParameter("fqt", "1")
                    .addQueryParameter("beg", begin.toString().replace("-", ""))
                    .addQueryParameter("end", end.toString().replace("-", ""))
                    .build()
                val request = Request.Builder()
                    .url(url)
                    .header("User-Agent", UA)
                    .header("Referer", "https://quote.eastmoney.com/")
                    .build()
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) error("Eastmoney HTTP ${response.code}")
                    val klines = JSONObject(response.body?.string().orEmpty())
                        .optJSONObject("data")
                        ?.optJSONArray("klines") ?: return@withContext emptyList()
                    List(klines.length()) { idx ->
                        val parts = klines.optString(idx).split(",")
                        KlineRow(
                            date = parts.getOrElse(0) { "" },
                            open = parts.getOrNull(1)?.toDoubleOrNull() ?: 0.0,
                            close = parts.getOrNull(2)?.toDoubleOrNull() ?: 0.0,
                            high = parts.getOrNull(3)?.toDoubleOrNull() ?: 0.0,
                            low = parts.getOrNull(4)?.toDoubleOrNull() ?: 0.0,
                            volume = (parts.getOrNull(5)?.toDoubleOrNull() ?: 0.0) * 100,
                            amount = parts.getOrNull(6)?.toDoubleOrNull() ?: 0.0,
                        )
                    }
                }
            }
        }

    private fun parseBaiduRow(keys: List<String>, raw: String): KlineRow? {
        val parts = raw.split(",")
        if (keys.isEmpty() || parts.size != keys.size) return null
        val map = keys.zip(parts).toMap()
        val date = map["time"]?.take(10).orEmpty()
        if (date.isBlank()) return null
        return KlineRow(
            date = date,
            open = map["open"]?.toDoubleOrNull() ?: 0.0,
            high = map["high"]?.toDoubleOrNull() ?: 0.0,
            low = map["low"]?.toDoubleOrNull() ?: 0.0,
            close = map["close"]?.toDoubleOrNull() ?: 0.0,
            volume = map["volume"]?.toDoubleOrNull() ?: 0.0,
            amount = map["amount"]?.toDoubleOrNull() ?: 0.0,
        )
    }
}

class TradingDayChecker(
    private val client: OkHttpClient,
    private val eastmoneyRateLimiter: EastmoneyRateLimiter,
) {
    suspend fun isTradingDay(today: LocalDate = LocalDate.now()): Boolean =
        eastmoneyRateLimiter.run {
            withContext(Dispatchers.IO) {
                val begin = today.minusDays(10).toString().replace("-", "")
                val end = today.toString().replace("-", "")
                val url = "https://push2his.eastmoney.com/api/qt/stock/kline/get".toHttpUrl().newBuilder()
                    .addQueryParameter("secid", "1.000001")
                    .addQueryParameter("fields1", "f1,f2,f3,f4,f5,f6")
                    .addQueryParameter("fields2", "f51,f52,f53,f54,f55,f56")
                    .addQueryParameter("klt", "101")
                    .addQueryParameter("fqt", "1")
                    .addQueryParameter("beg", begin)
                    .addQueryParameter("end", end)
                    .build()
                val request = Request.Builder()
                    .url(url)
                    .header("User-Agent", UA)
                    .header("Referer", "https://quote.eastmoney.com/zs000001.html")
                    .build()
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) error("Eastmoney index HTTP ${response.code}")
                    val klines = JSONObject(response.body?.string().orEmpty())
                        .optJSONObject("data")
                        ?.optJSONArray("klines") ?: error("上证指数K线为空")
                    val latest = (0 until klines.length())
                        .mapNotNull { idx -> klines.optString(idx).substringBefore(",").takeIf { it.isNotBlank() } }
                        .maxOrNull()
                    TradingDayDecider.isTradingDay(latest, today)
                }
            }
        }
}

object TradingDayDecider {
    fun isTradingDay(latestDate: String?, today: LocalDate): Boolean = latestDate == today.toString()
}

fun prefixFor(code: String) = if (code.startsWith("6") || code.startsWith("9")) "sh" else "sz"

fun marketIdFor(code: String) = if (code.startsWith("6") || code.startsWith("9")) 1 else 0
