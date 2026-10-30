import BackgroundTasks
import Foundation

enum BackgroundTaskManager {
    static let identifier = "com.tradingagents.stockscreener.refresh"

    static func register(store: LocalStore, viewModel: AppViewModel) {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: identifier, using: nil) { task in
            Task { @MainActor in
                guard let refreshTask = task as? BGAppRefreshTask else {
                    task.setTaskCompleted(success: false)
                    return
                }
                handle(task: refreshTask, store: store, viewModel: viewModel)
            }
        }
    }

    static func schedule(settings: ScheduleSettings) {
        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: identifier)
        guard settings.enabled else { return }
        let request = BGAppRefreshTaskRequest(identifier: identifier)
        request.earliestBeginDate = nextRunDate(hour: settings.hour, minute: settings.minute)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            print("后台任务计划失败：\(error.localizedDescription)")
        }
    }

    static func nextRunDate(hour: Int, minute: Int, now: Date = Date()) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.locale = Locale(identifier: "zh_CN")
        var components = calendar.dateComponents([.year, .month, .day], from: now)
        components.hour = min(max(hour, 0), 23)
        components.minute = min(max(minute, 0), 59)
        components.second = 0
        let today = calendar.date(from: components) ?? now
        return today > now ? today : (calendar.date(byAdding: .day, value: 1, to: today) ?? now.addingTimeInterval(24 * 3600))
    }

    @MainActor
    private static func handle(task: BGAppRefreshTask, store: LocalStore, viewModel: AppViewModel) {
        schedule(settings: store.schedule)
        let operation = Task {
            await viewModel.runScheduledIfNeeded()
            task.setTaskCompleted(success: true)
        }
        task.expirationHandler = {
            operation.cancel()
            task.setTaskCompleted(success: false)
        }
    }
}
