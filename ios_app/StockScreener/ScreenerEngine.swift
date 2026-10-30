import Foundation

final class ScreenerEngine {
    private let marketData: MarketDataService

    init(marketData: MarketDataService) {
        self.marketData = marketData
    }

    func run(params: ScreenerParams, progress: @escaping @MainActor (String) -> Void) async throws -> ScreeningResult {
        let codes = generateMainBoardCodes()
        await progress("阶段1/4：开始获取实时行情，共 \(codes.count) 个代码")
        var quotes: [QuoteRow] = []
        let batchSize = max(params.quoteBatchSize, 10)
        let batches = codes.chunked(into: batchSize)
        for (index, batch) in batches.enumerated() {
            await progress("阶段1/4：行情批次 \(index + 1)/\(batches.count)，\(batch.first ?? "")-\(batch.last ?? "")")
            do {
                quotes.append(contentsOf: try await marketData.fetchTencentQuotes(codes: batch))
            } catch {
                await progress("行情批次失败：\(error.localizedDescription)")
            }
            if index < batches.count - 1 {
                try? await Task.sleep(nanoseconds: UInt64(max(params.quoteBatchIntervalMs, 300)) * 1_000_000)
            }
        }

        let quotePassed = quotes.filter { quoteRejectReasons($0, params: params).isEmpty }
        await progress("阶段2/4：实时行情 \(quotes.count) 条，报价条件通过 \(quotePassed.count) 条")

        var screened: [ScreenedStock] = []
        for (index, quote) in quotePassed.enumerated() {
            if index > 0 {
                try? await Task.sleep(nanoseconds: UInt64(max(params.klineRequestIntervalMs, 500)) * 1_000_000)
            }
            await progress("阶段3/4：校验K线 \(index + 1)/\(quotePassed.count)：\(quote.code) \(quote.name)")
            let kline = await marketData.fetchRecentKlines(code: quote.code, lookbackDays: params.klineLookbackDays)
            let stock = screenQuote(quote, rows: kline.rows, source: kline.source, errors: kline.errors, params: params)
            screened.append(stock)
            if stock.selected {
                await progress("命中候选：\(stock.code) \(stock.name) P\(stock.priority) \(stock.priorityLabel)")
            }
        }

        let selected = screened.filter(\.selected).sorted {
            if $0.priority == $1.priority { return $0.volumeRatio > $1.volumeRatio }
            return $0.priority < $1.priority
        }
        let selectedIds = Set(selected.map(\.code))
        let output = selected + screened.filter { !selectedIds.contains($0.code) }
        await progress("阶段4/4：完成，最终入选 \(selected.count) 条，全部保存 \(screened.count) 条")

        return ScreeningResult(
            id: UUID(),
            createdAt: Date(),
            params: params,
            summary: ScreeningSummary(
                asOf: Date().displayText,
                quoteCount: quotes.count,
                quoteFilterCount: quotePassed.count,
                selectedCount: selected.count,
                rejectedCount: max(screened.count - selected.count, 0),
                returnedCount: min(selected.count, params.limit)
            ),
            stocks: output
        )
    }

    func querySingleStock(input: String, params: ScreenerParams) async throws -> StockQueryResult {
        let code = try normalizeCode(input)
        guard let quote = (try await marketData.fetchTencentQuotes(codes: [code])).first else {
            throw NSError(domain: "StockQuery", code: 1, userInfo: [NSLocalizedDescriptionKey: "未读取到实时行情：\(code)"])
        }
        let kline = await marketData.fetchRecentKlines(code: code, lookbackDays: params.klineLookbackDays)
        let stock = screenSingleQuote(quote, rows: kline.rows, source: kline.source, errors: kline.errors, params: params)
        return StockQueryResult(id: UUID(), queriedAt: Date(), params: params, stock: stock)
    }

    func quoteRejectReasons(_ q: QuoteRow, params p: ScreenerParams) -> [String] {
        var reasons: [String] = []
        let name = q.name.uppercased()
        if name.contains("ST") || name.contains("退") { reasons.append("ST/退市风险名称过滤") }
        if !["600", "601", "603", "605", "000", "001", "002", "003"].contains(where: { q.code.hasPrefix($0) }) {
            reasons.append("非A股主板代码范围")
        }
        let lot = q.price * 100
        if lot < p.minLotAmount || lot > p.maxLotAmount { reasons.append("一手金额不在 \(p.minLotAmount.compactText)-\(p.maxLotAmount.compactText)") }
        if q.changePct < p.minChangePct || q.changePct > p.maxChangePct { reasons.append("涨幅不在 \(p.minChangePct.compactText)-\(p.maxChangePct.compactText)%") }
        if q.volumeRatio <= p.minVolumeRatio { reasons.append("量比未大于 \(p.minVolumeRatio.compactText)") }
        if q.turnoverPct < p.minTurnoverPct { reasons.append("换手率低于 \(p.minTurnoverPct.compactText)%") }
        if let maxTurnover = p.maxTurnoverPct, q.turnoverPct > maxTurnover { reasons.append("换手率高于 \(maxTurnover.compactText)%") }
        if q.floatMarketCapYi < p.minFloatMarketCapYi || q.floatMarketCapYi > p.maxFloatMarketCapYi {
            reasons.append("流通市值不在 \(p.minFloatMarketCapYi.compactText)-\(p.maxFloatMarketCapYi.compactText)亿")
        }
        return reasons
    }

    private func screenSingleQuote(_ quote: QuoteRow, rows: [KlineRow], source: String, errors: [String], params: ScreenerParams) -> ScreenedStock {
        let quoteReasons = quoteRejectReasons(quote, params: params)
        let stock = screenQuote(quote, rows: rows, source: source, errors: errors, params: params)
        let reasons = quoteReasons + (stock.selected ? [] : [stock.rejectReason].filter { !$0.isEmpty })
        if reasons.isEmpty { return stock }
        return ScreenedStock(
            selected: false,
            rejectReason: reasons.joined(separator: "；"),
            code: stock.code,
            name: stock.name,
            price: stock.price,
            oneLotAmount: stock.oneLotAmount,
            changePct: stock.changePct,
            volumeRatio: stock.volumeRatio,
            turnoverPct: stock.turnoverPct,
            floatMarketCapYi: stock.floatMarketCapYi,
            marketCapYi: stock.marketCapYi,
            priority: stock.priority,
            priorityLabel: stock.priorityLabel,
            actionHint: stock.actionHint,
            positionLabel: stock.positionLabel,
            recentPositionPct: stock.recentPositionPct,
            klineSource: stock.klineSource,
            klineErrors: stock.klineErrors
        )
    }

    private func screenQuote(_ quote: QuoteRow, rows: [KlineRow], source: String, errors: [String], params: ScreenerParams) -> ScreenedStock {
        let priority = prioritySignal(turnoverPct: quote.turnoverPct, volumeRatio: quote.volumeRatio)
        let eval = evaluateKlines(rows, params: params)
        let selected = eval.volumeOk && eval.maOk
        return ScreenedStock(
            selected: selected,
            rejectReason: selected ? "" : rejectReason(eval: eval, errors: errors),
            code: quote.code,
            name: quote.name,
            price: round2(quote.price),
            oneLotAmount: round2(quote.price * 100),
            changePct: round2(quote.changePct),
            volumeRatio: round2(quote.volumeRatio),
            turnoverPct: round2(quote.turnoverPct),
            floatMarketCapYi: round2(quote.floatMarketCapYi),
            marketCapYi: round2(quote.marketCapYi),
            priority: priority.0,
            priorityLabel: priority.1,
            actionHint: priority.2,
            positionLabel: eval.positionLabel,
            recentPositionPct: eval.positionPct,
            klineSource: source,
            klineErrors: errors.joined(separator: "；")
        )
    }

    private func evaluateKlines(_ rows: [KlineRow], params: ScreenerParams) -> KlineEval {
        guard rows.count >= 20 else {
            return KlineEval(volumeOk: false, maOk: false, positionLabel: "未知", positionPct: nil, reason: "数据不足：K线仅 \(rows.count) 条，无法稳定判断MA20")
        }
        let sorted = rows.sorted { $0.date < $1.date }
        let volumeDays = max(params.volumeGrowthDays, 2)
        let volumeWindow = sorted.suffix(volumeDays).map(\.volume)
        let volumeOk = zip(volumeWindow, volumeWindow.dropFirst()).allSatisfy { $1 > $0 }
        let closes = sorted.map(\.close)
        let slopeDays = max(params.maSlopeDays, 2)
        let maOk = [5, 10, 20].allSatisfy { maUp(closes: closes, window: $0, slopeDays: slopeDays) }
        let position = recentPosition(rows: sorted, days: params.recentPositionDays)
        return KlineEval(volumeOk: volumeOk, maOk: maOk, positionLabel: position.0, positionPct: position.1, reason: "")
    }

    private func maUp(closes: [Double], window: Int, slopeDays: Int) -> Bool {
        guard closes.count >= window else { return false }
        let mas = (window...closes.count).map { index in
            Array(closes[(index - window)..<index]).reduce(0, +) / Double(window)
        }.suffix(slopeDays)
        guard mas.count >= slopeDays, let first = mas.first, let last = mas.last else { return false }
        return zip(mas, mas.dropFirst()).allSatisfy { $1 >= $0 } && last > first
    }

    private func recentPosition(rows: [KlineRow], days: Int) -> (String, Double?) {
        let win = rows.suffix(max(days, 2))
        guard let high = win.map(\.high).max(), let low = win.map(\.low).min(), let close = win.last?.close else {
            return ("未知", nil)
        }
        let pct = high <= low ? 50 : (close - low) / (high - low) * 100
        let label = pct <= 35 ? "低位" : (pct >= 70 ? "高位" : "中位")
        return (label, round2(pct))
    }

    private func rejectReason(eval: KlineEval, errors: [String]) -> String {
        if eval.positionLabel == "未知", !errors.isEmpty { return "数据未读取：\(errors.joined(separator: "；"))" }
        var reasons: [String] = []
        if !eval.volumeOk { reasons.append("成交量条件不满足") }
        if !eval.maOk { reasons.append("均线条件不满足") }
        return reasons.isEmpty ? (eval.reason.isEmpty ? "K线/MA/成交量条件不满足" : eval.reason) : reasons.joined(separator: "；")
    }

    private func prioritySignal(turnoverPct: Double, volumeRatio: Double) -> (Int, String, String) {
        if turnoverPct > 5, volumeRatio >= 2, volumeRatio <= 3 {
            return (1, "启动信号", "换手率>5%、量比2-3")
        }
        if turnoverPct >= 5, turnoverPct <= 10, volumeRatio > 3, volumeRatio <= 5 {
            return (2, "资金加速主升浪", "换手率5%-10%、量比3-5")
        }
        if turnoverPct > 10, volumeRatio > 5 {
            return (3, "高换手高量比", "需结合位置判断低位吸筹或高位出货")
        }
        if turnoverPct > 5, volumeRatio < 2 {
            return (4, "撤退风险", "换手率>5%、量比<2")
        }
        return (99, "未命中优先级", "未命中四条优先级规则")
    }

    private func generateMainBoardCodes() -> [String] {
        ["600", "601", "603", "605", "000", "001", "002", "003"].flatMap { prefix in
            (0...999).map { "\(prefix)\(String(format: "%03d", $0))" }
        }
    }

    private func normalizeCode(_ input: String) throws -> String {
        let code = input.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "sh", with: "")
            .replacingOccurrences(of: "sz", with: "")
            .filter(\.isNumber)
        guard code.count == 6 else {
            throw NSError(domain: "StockQuery", code: 2, userInfo: [NSLocalizedDescriptionKey: "请输入6位股票代码"])
        }
        return code
    }

    private func round2(_ value: Double) -> Double {
        (value * 100).rounded() / 100
    }
}

private struct KlineEval {
    let volumeOk: Bool
    let maOk: Bool
    let positionLabel: String
    let positionPct: Double?
    let reason: String
}

private extension Array {
    func chunked(into size: Int) -> [[Element]] {
        stride(from: 0, to: count, by: size).map { index in
            Array(self[index..<Swift.min(index + size, count)])
        }
    }
}
