import Foundation

final class LocalStore: ObservableObject {
    @Published private(set) var params: ScreenerParams = ScreenerParams()
    @Published private(set) var schedule: ScheduleSettings = ScheduleSettings()
    @Published private(set) var screeningHistory: [ScreeningResult] = []
    @Published private(set) var stockQueryHistory: [StockQueryResult] = []

    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private let paramsURL: URL
    private let scheduleURL: URL
    private let screeningHistoryURL: URL
    private let stockQueryHistoryURL: URL

    init() {
        let root = Self.appSupportDirectory()
        paramsURL = root.appendingPathComponent("screener_params.json")
        scheduleURL = root.appendingPathComponent("schedule_settings.json")
        screeningHistoryURL = root.appendingPathComponent("screening_history.json")
        stockQueryHistoryURL = root.appendingPathComponent("stock_query_history.json")
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        loadAll()
    }

    func updateParams(_ next: ScreenerParams) {
        params = next
        save(params, to: paramsURL)
    }

    func updateSchedule(_ next: ScheduleSettings) {
        schedule = next
        save(schedule, to: scheduleURL)
    }

    func addScreeningResult(_ result: ScreeningResult) {
        screeningHistory.insert(result, at: 0)
        save(screeningHistory, to: screeningHistoryURL)
    }

    func deleteScreeningResult(_ id: UUID) {
        screeningHistory.removeAll { $0.id == id }
        save(screeningHistory, to: screeningHistoryURL)
    }

    func addStockQuery(_ result: StockQueryResult) {
        stockQueryHistory.insert(result, at: 0)
        save(stockQueryHistory, to: stockQueryHistoryURL)
    }

    func deleteStockQuery(_ id: UUID) {
        stockQueryHistory.removeAll { $0.id == id }
        save(stockQueryHistory, to: stockQueryHistoryURL)
    }

    private func loadAll() {
        params = load(ScreenerParams.self, from: paramsURL) ?? ScreenerParams()
        schedule = load(ScheduleSettings.self, from: scheduleURL) ?? ScheduleSettings()
        screeningHistory = load([ScreeningResult].self, from: screeningHistoryURL) ?? []
        stockQueryHistory = load([StockQueryResult].self, from: stockQueryHistoryURL) ?? []
    }

    private func load<T: Decodable>(_ type: T.Type, from url: URL) -> T? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? decoder.decode(type, from: data)
    }

    private func save<T: Encodable>(_ value: T, to url: URL) {
        do {
            let data = try encoder.encode(value)
            try data.write(to: url, options: .atomic)
        } catch {
            print("保存失败：\(error.localizedDescription)")
        }
    }

    private static func appSupportDirectory() -> URL {
        let manager = FileManager.default
        let root = manager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("StockScreener", isDirectory: true)
        try? manager.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }
}
