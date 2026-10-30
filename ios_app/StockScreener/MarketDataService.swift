import Foundation
import CoreFoundation

actor EastmoneyRateLimiter {
    private var lastRequestAt: Date?
    private var minIntervalMs: Int

    init(minIntervalMs: Int) {
        self.minIntervalMs = max(minIntervalMs, 1000)
    }

    func update(minIntervalMs: Int) {
        self.minIntervalMs = max(minIntervalMs, 1000)
    }

    func waitTurn() async {
        if let lastRequestAt {
            let elapsed = Date().timeIntervalSince(lastRequestAt) * 1000
            let wait = Double(minIntervalMs) - elapsed
            if wait > 0 {
                try? await Task.sleep(nanoseconds: UInt64(wait * 1_000_000))
            }
        }
        lastRequestAt = Date()
    }
}

final class MarketDataService {
    private let session: URLSession
    private let eastmoneyLimiter: EastmoneyRateLimiter
    private let gbkEncoding = String.Encoding(rawValue: CFStringConvertEncodingToNSStringEncoding(CFStringEncoding(CFStringEncodings.GB_18030_2000.rawValue)))

    init(session: URLSession = .shared, eastmoneyLimiter: EastmoneyRateLimiter) {
        self.session = session
        self.eastmoneyLimiter = eastmoneyLimiter
    }

    func fetchTencentQuotes(codes: [String]) async throws -> [QuoteRow] {
        guard !codes.isEmpty else { return [] }
        let symbols = codes.map { "\(prefix(for: $0))\($0)" }.joined(separator: ",")
        var request = URLRequest(url: URL(string: "https://qt.gtimg.cn/q=\(symbols)")!)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("https://finance.qq.com/", forHTTPHeaderField: "Referer")
        let (data, response) = try await session.data(for: request)
        try validate(response, provider: "Tencent")
        let text = String(data: data, encoding: gbkEncoding) ?? String(data: data, encoding: .utf8) ?? ""
        return parseTencentQuotes(text)
    }

    func fetchRecentKlines(code: String, lookbackDays: Int) async -> KlineResult {
        var errors: [String] = []
        do {
            let rows = try await fetchSinaKlines(code: code, dataLen: max(lookbackDays * 2, 80))
            if !rows.isEmpty { return KlineResult(rows: rows.sorted { $0.date < $1.date }.suffixArray(max(lookbackDays, 25)), source: "sina_kline", errors: errors) }
            errors.append("sina_kline: no records")
        } catch {
            errors.append("sina_kline: \(error.localizedDescription)")
        }
        do {
            let rows = try await fetchEastmoneyKlines(code: code, lookbackDays: lookbackDays)
            if !rows.isEmpty { return KlineResult(rows: rows.sorted { $0.date < $1.date }, source: "eastmoney_kline", errors: errors) }
            errors.append("eastmoney_kline: no records")
        } catch {
            errors.append("eastmoney_kline: \(error.localizedDescription)")
        }
        return KlineResult(rows: [], source: "unavailable", errors: errors)
    }

    func isTradingDay(today: Date = Date()) async throws -> Bool {
        await eastmoneyLimiter.waitTurn()
        let calendar = Calendar(identifier: .gregorian)
        let begin = calendar.date(byAdding: .day, value: -10, to: today) ?? today
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd"
        var components = URLComponents(string: "https://push2his.eastmoney.com/api/qt/stock/kline/get")!
        components.queryItems = [
            URLQueryItem(name: "secid", value: "1.000001"),
            URLQueryItem(name: "fields1", value: "f1,f2,f3,f4,f5,f6"),
            URLQueryItem(name: "fields2", value: "f51,f52,f53,f54,f55,f56"),
            URLQueryItem(name: "klt", value: "101"),
            URLQueryItem(name: "fqt", value: "1"),
            URLQueryItem(name: "beg", value: formatter.string(from: begin)),
            URLQueryItem(name: "end", value: formatter.string(from: today))
        ]
        var request = URLRequest(url: components.url!)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("https://quote.eastmoney.com/zs000001.html", forHTTPHeaderField: "Referer")
        let (data, response) = try await session.data(for: request)
        try validate(response, provider: "Eastmoney index")
        let latest = try latestDateFromEastmoneyKlines(data: data)
        let dayFormatter = DateFormatter()
        dayFormatter.dateFormat = "yyyy-MM-dd"
        return latest == dayFormatter.string(from: today)
    }

    private func fetchSinaKlines(code: String, dataLen: Int) async throws -> [KlineRow] {
        var components = URLComponents(string: "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20data=/CN_MarketDataService.getKLineData")!
        components.queryItems = [
            URLQueryItem(name: "symbol", value: "\(prefix(for: code))\(code)"),
            URLQueryItem(name: "scale", value: "240"),
            URLQueryItem(name: "ma", value: "no"),
            URLQueryItem(name: "datalen", value: "\(dataLen)")
        ]
        var request = URLRequest(url: components.url!)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("https://finance.sina.com.cn/", forHTTPHeaderField: "Referer")
        let (data, response) = try await session.data(for: request)
        try validate(response, provider: "Sina")
        let text = String(data: data, encoding: .utf8) ?? ""
        guard let start = text.range(of: "var data=("), let end = text.range(of: ");", options: .backwards) else { return [] }
        let jsonText = String(text[start.upperBound..<end.lowerBound])
        guard let jsonData = jsonText.data(using: .utf8),
              let items = try JSONSerialization.jsonObject(with: jsonData) as? [[String: Any]]
        else { return [] }
        return items.compactMap { item in
            guard let day = item["day"] as? String, !day.isEmpty else { return nil }
            return KlineRow(
                date: day,
                open: double(item["open"]),
                high: double(item["high"]),
                low: double(item["low"]),
                close: double(item["close"]),
                volume: double(item["volume"]),
                amount: double(item["amount"])
            )
        }
    }

    private func fetchEastmoneyKlines(code: String, lookbackDays: Int) async throws -> [KlineRow] {
        await eastmoneyLimiter.waitTurn()
        let today = Date()
        let begin = Calendar.current.date(byAdding: .day, value: -lookbackDays, to: today) ?? today
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd"
        var components = URLComponents(string: "https://push2his.eastmoney.com/api/qt/stock/kline/get")!
        components.queryItems = [
            URLQueryItem(name: "secid", value: "\(marketId(for: code)).\(code)"),
            URLQueryItem(name: "fields1", value: "f1,f2,f3,f4,f5,f6"),
            URLQueryItem(name: "fields2", value: "f51,f52,f53,f54,f55,f56,f57"),
            URLQueryItem(name: "klt", value: "101"),
            URLQueryItem(name: "fqt", value: "1"),
            URLQueryItem(name: "beg", value: formatter.string(from: begin)),
            URLQueryItem(name: "end", value: formatter.string(from: today))
        ]
        var request = URLRequest(url: components.url!)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("https://quote.eastmoney.com/", forHTTPHeaderField: "Referer")
        let (data, response) = try await session.data(for: request)
        try validate(response, provider: "Eastmoney")
        let strings = try eastmoneyKlineStrings(data: data)
        return strings.compactMap { raw in
            let parts = raw.split(separator: ",").map(String.init)
            guard parts.count >= 6 else { return nil }
            return KlineRow(
                date: parts[0],
                open: Double(parts[safe: 1] ?? "") ?? 0,
                high: Double(parts[safe: 3] ?? "") ?? 0,
                low: Double(parts[safe: 4] ?? "") ?? 0,
                close: Double(parts[safe: 2] ?? "") ?? 0,
                volume: (Double(parts[safe: 5] ?? "") ?? 0) * 100,
                amount: Double(parts[safe: 6] ?? "") ?? 0
            )
        }
    }

    private func parseTencentQuotes(_ text: String) -> [QuoteRow] {
        text.split(separator: ";").compactMap { segment in
            let line = String(segment)
            guard line.contains("="), line.contains("\"") else { return nil }
            let key = line.components(separatedBy: "=").first?.components(separatedBy: "_").last ?? ""
            let values = line.components(separatedBy: "\"").dropFirst().first?.components(separatedBy: "~") ?? []
            guard values.count >= 53 else { return nil }
            let code = String(key.suffix(6))
            let price = Double(values[safe: 3] ?? "") ?? 0
            guard price > 0, !(values[safe: 1] ?? "").isEmpty else { return nil }
            return QuoteRow(
                code: code,
                name: values[safe: 1] ?? "",
                price: price,
                changePct: Double(values[safe: 32] ?? "") ?? 0,
                volumeRatio: Double(values[safe: 49] ?? "") ?? 0,
                turnoverPct: Double(values[safe: 38] ?? "") ?? 0,
                floatMarketCapYi: Double(values[safe: 44] ?? "") ?? 0,
                marketCapYi: Double(values[safe: 45] ?? "") ?? 0,
                amountWan: Double(values[safe: 37] ?? "") ?? 0
            )
        }
    }

    private func latestDateFromEastmoneyKlines(data: Data) throws -> String? {
        let strings = try eastmoneyKlineStrings(data: data)
        return strings.compactMap { $0.components(separatedBy: ",").first }.max()
    }

    private func eastmoneyKlineStrings(data: Data) throws -> [String] {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let dataObject = object["data"] as? [String: Any],
              let klines = dataObject["klines"] as? [String]
        else { return [] }
        return klines
    }

    private func validate(_ response: URLResponse, provider: String) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            throw NSError(domain: provider, code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: "\(provider) HTTP \(http.statusCode)"])
        }
    }

    private func prefix(for code: String) -> String {
        code.hasPrefix("6") || code.hasPrefix("9") ? "sh" : "sz"
    }

    private func marketId(for code: String) -> Int {
        code.hasPrefix("6") || code.hasPrefix("9") ? 1 : 0
    }

    private func double(_ value: Any?) -> Double {
        if let value = value as? Double { return value }
        if let value = value as? String { return Double(value) ?? 0 }
        return 0
    }

    private var userAgent: String {
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}

private extension Array {
    func suffixArray(_ maxLength: Int) -> [Element] {
        Array(suffix(maxLength))
    }
}
