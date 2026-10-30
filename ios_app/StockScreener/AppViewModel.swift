import Foundation

@MainActor
final class AppViewModel: ObservableObject {
    @Published var selectedTab: AppTab = .screener
    @Published var progress: String = "等待运行"
    @Published var singleStockProgress: String = "输入代码后查询"
    @Published var isRunning = false
    @Published var isQueryingStock = false
    @Published var currentResult: ScreeningResult?
    @Published var currentStockQuery: StockQueryResult?
    @Published var shareURL: URL?

    let store: LocalStore
    private let rateLimiter: EastmoneyRateLimiter
    private let marketData: MarketDataService
    private let engine: ScreenerEngine

    init(store: LocalStore) {
        self.store = store
        let limiter = EastmoneyRateLimiter(minIntervalMs: store.params.eastmoneyMinIntervalMs)
        rateLimiter = limiter
        marketData = MarketDataService(eastmoneyLimiter: limiter)
        engine = ScreenerEngine(marketData: marketData)
    }

    func updateParams(_ params: ScreenerParams) {
        store.updateParams(params)
        Task { await rateLimiter.update(minIntervalMs: params.eastmoneyMinIntervalMs) }
    }

    func mutateParams(_ mutate: (inout ScreenerParams) -> Void) {
        var next = store.params
        mutate(&next)
        updateParams(next)
    }

    func saveSchedule(enabled: Bool, hour: Int, minute: Int) {
        var next = store.schedule
        next.enabled = enabled
        next.hour = min(max(hour, 0), 23)
        next.minute = min(max(minute, 0), 59)
        next.nextRunAt = enabled ? BackgroundTaskManager.nextRunDate(hour: next.hour, minute: next.minute) : nil
        store.updateSchedule(next)
        BackgroundTaskManager.schedule(settings: next)
        NotificationService.shared.scheduleDailyReminder(settings: next)
    }

    func requestNotificationAuthorization() {
        Task {
            _ = await NotificationService.shared.requestAuthorization()
            NotificationService.shared.scheduleDailyReminder(settings: store.schedule)
        }
    }

    func runManualScreening() {
        guard !isRunning else { return }
        currentResult = nil
        progress = "准备启动"
        isRunning = true
        Task {
            do {
                let result = try await engine.run(params: store.params) { [weak self] message in
                    self?.progress = message
                }
                currentResult = result
                store.addScreeningResult(result)
                progress = "筛选完成，已保存到历史"
            } catch {
                progress = "运行失败：\(error.localizedDescription)"
            }
            isRunning = false
        }
    }

    func queryStock(_ input: String) {
        guard !isQueryingStock else { return }
        currentStockQuery = nil
        singleStockProgress = "准备查询"
        isQueryingStock = true
        Task {
            do {
                singleStockProgress = "正在获取实时行情和K线"
                let result = try await engine.querySingleStock(input: input, params: store.params)
                currentStockQuery = result
                store.addStockQuery(result)
                singleStockProgress = "查询完成，已保存到历史"
            } catch {
                singleStockProgress = "查询失败：\(error.localizedDescription)"
            }
            isQueryingStock = false
        }
    }

    func runScheduledIfNeeded() async {
        guard store.schedule.enabled else { return }
        do {
            let isTradingDay = try await marketData.isTradingDay()
            if !isTradingDay {
                var schedule = store.schedule
                schedule.lastRunText = "非交易日已跳过：\(Date().displayText)"
                schedule.nextRunAt = BackgroundTaskManager.nextRunDate(hour: schedule.hour, minute: schedule.minute)
                store.updateSchedule(schedule)
                NotificationService.shared.notifySkipped(schedule.lastRunText)
                return
            }
            let result = try await engine.run(params: store.params) { _ in }
            store.addScreeningResult(result)
            var schedule = store.schedule
            schedule.lastRunText = "筛选完成：入选 \(result.summary.selectedCount) / 筛过 \(result.stocks.count)"
            schedule.nextRunAt = BackgroundTaskManager.nextRunDate(hour: schedule.hour, minute: schedule.minute)
            store.updateSchedule(schedule)
            NotificationService.shared.notifyCompleted(result)
        } catch {
            var schedule = store.schedule
            schedule.lastRunText = "定时筛选失败：\(error.localizedDescription)"
            schedule.nextRunAt = BackgroundTaskManager.nextRunDate(hour: schedule.hour, minute: schedule.minute)
            store.updateSchedule(schedule)
            NotificationService.shared.notifyFailed(schedule.lastRunText)
        }
        BackgroundTaskManager.schedule(settings: store.schedule)
    }

    func exportCurrentResult() {
        guard let currentResult else { return }
        do {
            shareURL = try HtmlReportExporter.export(result: currentResult)
        } catch {
            progress = "HTML报告生成失败：\(error.localizedDescription)"
        }
    }

    func exportHistoryResult(_ result: ScreeningResult) {
        do {
            shareURL = try HtmlReportExporter.export(result: result)
        } catch {
            progress = "HTML报告生成失败：\(error.localizedDescription)"
        }
    }
}
