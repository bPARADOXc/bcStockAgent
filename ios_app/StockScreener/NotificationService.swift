import Foundation
import UserNotifications

final class NotificationService {
    static let shared = NotificationService()

    private init() {}

    func requestAuthorization() async -> Bool {
        do {
            return try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound])
        } catch {
            return false
        }
    }

    func scheduleDailyReminder(settings: ScheduleSettings) {
        UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: ["daily_screening_reminder"])
        guard settings.enabled else { return }
        var date = DateComponents()
        date.hour = settings.hour
        date.minute = settings.minute
        let content = UNMutableNotificationContent()
        content.title = "A股短线筛选"
        content.body = "到达设置时间，系统将尽力后台筛选；若未完成，请打开App手动运行。"
        content.sound = .default
        let trigger = UNCalendarNotificationTrigger(dateMatching: date, repeats: true)
        let request = UNNotificationRequest(identifier: "daily_screening_reminder", content: content, trigger: trigger)
        UNUserNotificationCenter.current().add(request)
    }

    func notifyCompleted(_ result: ScreeningResult) {
        let selected = result.stocks.filter(\.selected)
        let top = selected.prefix(3).map { "\($0.code) \($0.name)" }.joined(separator: "、")
        send(
            id: "screening_completed_\(result.id.uuidString)",
            title: "筛选完成",
            body: "入选 \(result.summary.selectedCount) 只，筛过 \(result.stocks.count) 只；前3：\(top.isEmpty ? "无入选股票" : top)"
        )
    }

    func notifySkipped(_ message: String) {
        send(id: "screening_skipped_\(UUID().uuidString)", title: "定时筛选已跳过", body: message)
    }

    func notifyFailed(_ message: String) {
        send(id: "screening_failed_\(UUID().uuidString)", title: "定时筛选失败", body: message)
    }

    private func send(id: String, title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        let request = UNNotificationRequest(identifier: id, content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request)
    }
}
