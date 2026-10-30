import Foundation

struct ScreenerParams: Codable, Equatable {
    var minLotAmount: Double = 2000
    var maxLotAmount: Double = 3000
    var minChangePct: Double = 3
    var maxChangePct: Double = 5
    var minVolumeRatio: Double = 1
    var minTurnoverPct: Double = 5
    var maxTurnoverPct: Double? = 10
    var minFloatMarketCapYi: Double = 50
    var maxFloatMarketCapYi: Double = 200
    var volumeGrowthDays: Int = 3
    var maSlopeDays: Int = 3
    var klineLookbackDays: Int = 45
    var recentPositionDays: Int = 20
    var quoteBatchSize: Int = 80
    var quoteBatchIntervalMs: Int = 1000
    var klineRequestIntervalMs: Int = 1800
    var eastmoneyMinIntervalMs: Int = 1800
    var limit: Int = 50
}

struct ScheduleSettings: Codable, Equatable {
    var enabled: Bool = false
    var hour: Int = 14
    var minute: Int = 30
    var nextRunAt: Date?
    var lastRunText: String = ""
}

struct QuoteRow: Identifiable, Codable, Equatable {
    var id: String { code }
    let code: String
    let name: String
    let price: Double
    let changePct: Double
    let volumeRatio: Double
    let turnoverPct: Double
    let floatMarketCapYi: Double
    let marketCapYi: Double
    let amountWan: Double
}

struct KlineRow: Codable, Equatable {
    let date: String
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let volume: Double
    let amount: Double
}

struct KlineResult: Codable, Equatable {
    let rows: [KlineRow]
    let source: String
    let errors: [String]
}

struct ScreenedStock: Identifiable, Codable, Equatable {
    var id: String { code }
    let selected: Bool
    let rejectReason: String
    let code: String
    let name: String
    let price: Double
    let oneLotAmount: Double
    let changePct: Double
    let volumeRatio: Double
    let turnoverPct: Double
    let floatMarketCapYi: Double
    let marketCapYi: Double
    let priority: Int
    let priorityLabel: String
    let actionHint: String
    let positionLabel: String
    let recentPositionPct: Double?
    let klineSource: String
    let klineErrors: String
}

struct ScreeningSummary: Codable, Equatable {
    let asOf: String
    let quoteCount: Int
    let quoteFilterCount: Int
    let selectedCount: Int
    let rejectedCount: Int
    let returnedCount: Int
}

struct ScreeningResult: Identifiable, Codable, Equatable {
    let id: UUID
    let createdAt: Date
    let params: ScreenerParams
    let summary: ScreeningSummary
    let stocks: [ScreenedStock]
}

struct StockQueryResult: Identifiable, Codable, Equatable {
    let id: UUID
    let queriedAt: Date
    let params: ScreenerParams
    let stock: ScreenedStock
}

enum ResultFilter: String, CaseIterable, Identifiable {
    case all = "全部"
    case selected = "入选"
    case rejected = "未入选"

    var id: String { rawValue }
}

enum AppTab: String, CaseIterable, Identifiable {
    case screener = "筛选"
    case single = "单股"
    case history = "历史"
    case settings = "设置"

    var id: String { rawValue }
}

extension Double {
    var compactText: String {
        if truncatingRemainder(dividingBy: 1) == 0 {
            return String(format: "%.0f", self)
        }
        return String(format: "%.2f", self)
    }
}

extension Date {
    var displayText: String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter.string(from: self)
    }
}
