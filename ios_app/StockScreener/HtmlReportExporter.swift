import Foundation

enum HtmlReportExporter {
    static func export(result: ScreeningResult) throws -> URL {
        let html = page(body: summary(result) + paramsCard(result.params) + result.stocks.map(stockCard).joined())
        return try write(html: html, fileName: "ashare_report_\(Int(Date().timeIntervalSince1970)).html")
    }

    private static func write(html: String, fileName: String) throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("reports", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent(fileName)
        try html.write(to: url, atomically: true, encoding: .utf8)
        return url
    }

    private static func page(body: String) -> String {
        """
        <!doctype html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>A股短线筛选报告</title>
          <style>
            body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f6f7f9;color:#17202a;}
            h1{font-size:22px;margin:18px 14px 10px;}
            .summary,.params{margin:0 14px 12px;padding:12px;border-radius:8px;background:#fff;line-height:1.7;}
            .params{font-size:14px;}
            .card{margin:10px 14px;padding:12px;border-radius:8px;background:#fff;border-left:5px solid #a6aeb8;}
            .selected{border-left-color:#1a8f5a;}
            .rejected{border-left-color:#b14545;}
            .title{display:flex;justify-content:space-between;gap:8px;font-weight:700;}
            .meta{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px;font-size:14px;}
            .reason{margin-top:8px;color:#8a2d2d;font-size:14px;line-height:1.45;}
            .tag{font-size:13px;padding:2px 6px;border-radius:999px;background:#eef2f6;}
          </style>
        </head>
        <body>\(body)</body>
        </html>
        """
    }

    private static func summary(_ result: ScreeningResult) -> String {
        """
        <h1>A股短线筛选报告</h1>
        <div class="summary">
          <div>时间：\(escape(result.summary.asOf))</div>
          <div>实时行情通过：\(result.summary.quoteFilterCount)</div>
          <div>最终入选：\(result.summary.selectedCount)</div>
          <div>保存股票：\(result.stocks.count)</div>
        </div>
        """
    }

    private static func paramsCard(_ params: ScreenerParams) -> String {
        """
        <section class="params">
          <strong>参数</strong>
          <div>一手金额：\(params.minLotAmount.compactText)-\(params.maxLotAmount.compactText) 元；涨幅：\(params.minChangePct.compactText)-\(params.maxChangePct.compactText)%</div>
          <div>量比：>\(params.minVolumeRatio.compactText)；换手：\(params.minTurnoverPct.compactText)-\(params.maxTurnoverPct?.compactText ?? "不限")%</div>
          <div>流通市值：\(params.minFloatMarketCapYi.compactText)-\(params.maxFloatMarketCapYi.compactText) 亿；放量：\(params.volumeGrowthDays) 天；MA：\(params.maSlopeDays) 天</div>
        </section>
        """
    }

    private static func stockCard(_ stock: ScreenedStock) -> String {
        """
        <section class="card \(stock.selected ? "selected" : "rejected")">
          <div class="title"><span>\(escape(stock.code)) \(escape(stock.name))</span><span class="tag">\(stock.selected ? "入选" : "未入选")</span></div>
          <div class="meta">
            <div>价格：\(stock.price.compactText)</div><div>涨幅：\(stock.changePct.compactText)%</div>
            <div>量比：\(stock.volumeRatio.compactText)</div><div>换手：\(stock.turnoverPct.compactText)%</div>
            <div>流通市值：\(stock.floatMarketCapYi.compactText)亿</div><div>优先级：P\(stock.priority) \(escape(stock.priorityLabel))</div>
            <div>位置：\(escape(stock.positionLabel))</div><div>K线：\(escape(stock.klineSource))</div>
          </div>
          \(stock.selected ? "" : "<div class=\"reason\">原因：\(escape(stock.rejectReason.isEmpty ? "未说明" : stock.rejectReason))</div>")
        </section>
        """
    }

    private static func escape(_ value: String) -> String {
        value
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
            .replacingOccurrences(of: "'", with: "&#39;")
    }
}
