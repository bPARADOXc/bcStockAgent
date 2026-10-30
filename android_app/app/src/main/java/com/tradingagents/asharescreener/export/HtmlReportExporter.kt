package com.tradingagents.asharescreener.export

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import com.tradingagents.asharescreener.data.ScreenedStockEntity
import com.tradingagents.asharescreener.data.ScreeningRunEntity
import com.tradingagents.asharescreener.data.ScreenerParamsCodec
import com.tradingagents.asharescreener.domain.ScreenedStock
import com.tradingagents.asharescreener.domain.ScreeningResult
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class HtmlReportExporter(private val context: Context) {
    fun exportCurrent(result: ScreeningResult): Uri {
        val html = HtmlReportBuilder.buildCurrent(result)
        return writeReport("ashare_report_${System.currentTimeMillis()}.html", html)
    }

    fun exportHistory(run: ScreeningRunEntity, stocks: List<ScreenedStockEntity>): Uri {
        val html = HtmlReportBuilder.buildHistory(run, stocks)
        return writeReport("ashare_report_${run.id}.html", html)
    }

    private fun writeReport(fileName: String, html: String): Uri {
        val dir = File(context.cacheDir, "reports")
        dir.mkdirs()
        val file = File(dir, fileName)
        file.writeText(html, Charsets.UTF_8)
        return FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    }
}

object HtmlReportBuilder {
    fun buildCurrent(result: ScreeningResult): String {
        val selected = result.stocks.count { it.selected }
        val header = """
            <h1>A股短线筛选报告</h1>
            <div class="summary">
              <div>时间：${h(result.summary.asOf)}</div>
              <div>实时行情通过：${result.summary.quoteFilterCount}</div>
              <div>最终入选：$selected</div>
              <div>保存股票：${result.stocks.size}</div>
            </div>
        """.trimIndent()
        return page(header + paramsCard(result.params) + result.stocks.joinToString("") { stockCard(it) })
    }

    fun buildHistory(run: ScreeningRunEntity, stocks: List<ScreenedStockEntity>): String {
        val time = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.CHINA).format(Date(run.createdAt))
        val header = """
            <h1>A股短线筛选报告</h1>
            <div class="summary">
              <div>时间：${h(time)}</div>
              <div>最终入选：${run.selectedCount}</div>
              <div>保存股票：${run.screenedCount}</div>
            </div>
        """.trimIndent()
        val paramsHtml = runCatching { paramsCard(ScreenerParamsCodec.fromJson(run.paramsJson)) }.getOrDefault("")
        return page(header + paramsHtml + stocks.joinToString("") { stockCard(it) })
    }

    private fun page(body: String): String = """
        <!doctype html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>A股短线筛选报告</title>
          <style>
            body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f6f7f9;color:#17202a;}
            h1{font-size:22px;margin:18px 14px 10px;}
            .summary{margin:0 14px 12px;padding:12px;border-radius:8px;background:#fff;line-height:1.7;}
            .params{margin:0 14px 12px;padding:12px;border-radius:8px;background:#fff;line-height:1.7;font-size:14px;}
            .card{margin:10px 14px;padding:12px;border-radius:8px;background:#fff;border-left:5px solid #a6aeb8;}
            .selected{border-left-color:#1a8f5a;}
            .rejected{border-left-color:#b14545;}
            .title{display:flex;justify-content:space-between;gap:8px;font-weight:700;}
            .meta{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;font-size:14px;}
            .reason{margin-top:8px;color:#8a2d2d;font-size:14px;line-height:1.45;}
            .tag{font-size:13px;padding:2px 6px;border-radius:999px;background:#eef2f6;}
          </style>
        </head>
        <body>$body</body>
        </html>
    """.trimIndent()

    private fun paramsCard(params: com.tradingagents.asharescreener.domain.ScreenerParams): String = """
        <section class="params">
          <strong>参数</strong>
          <div>一手金额：${params.minLotAmount}-${params.maxLotAmount} 元；涨幅：${params.minChangePct}-${params.maxChangePct}%</div>
          <div>量比：>${params.minVolumeRatio}；换手：${params.minTurnoverPct}-${params.maxTurnoverPct?.toString() ?: "不限"}%</div>
          <div>流通市值：${params.minFloatMarketCapYi}-${params.maxFloatMarketCapYi} 亿；放量：${params.volumeGrowthDays} 天；MA：${params.maSlopeDays} 天</div>
          <div>K线回看：${params.klineLookbackDays} 天；位置区间：${params.recentPositionDays} 天；返回：${params.limit}</div>
        </section>
    """.trimIndent()

    private fun stockCard(stock: ScreenedStock): String = """
        <section class="card ${if (stock.selected) "selected" else "rejected"}">
          <div class="title"><span>${h(stock.code)} ${h(stock.name)}</span><span class="tag">${if (stock.selected) "入选" else "未入选"}</span></div>
          <div class="meta">
            <div>价格：${stock.price}</div><div>涨幅：${stock.changePct}%</div>
            <div>量比：${stock.volumeRatio}</div><div>换手：${stock.turnoverPct}%</div>
            <div>流通市值：${stock.floatMarketCapYi}亿</div><div>优先级：P${stock.priority} ${h(stock.priorityLabel)}</div>
            <div>位置：${h(stock.positionLabel)}</div><div>K线：${h(stock.klineSource)}</div>
          </div>
          ${if (stock.selected) "" else """<div class="reason">原因：${h(stock.rejectReason.ifBlank { "未说明" })}</div>"""}
        </section>
    """.trimIndent()

    private fun stockCard(stock: ScreenedStockEntity): String = """
        <section class="card ${if (stock.selected) "selected" else "rejected"}">
          <div class="title"><span>${h(stock.code)} ${h(stock.name)}</span><span class="tag">${if (stock.selected) "入选" else "未入选"}</span></div>
          <div class="meta">
            <div>价格：${stock.price}</div><div>涨幅：${stock.changePct}%</div>
            <div>量比：${stock.volumeRatio}</div><div>换手：${stock.turnoverPct}%</div>
            <div>流通市值：${stock.floatMarketCapYi}亿</div><div>优先级：P${stock.priority} ${h(stock.priorityLabel)}</div>
            <div>位置：${h(stock.positionLabel)}</div><div>K线：${h(stock.klineSource)}</div>
          </div>
          ${if (stock.selected) "" else """<div class="reason">原因：${h(stock.rejectReason.ifBlank { "未说明" })}</div>"""}
        </section>
    """.trimIndent()

    internal fun h(value: String): String = value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\"", "&quot;")
        .replace("'", "&#39;")
}
