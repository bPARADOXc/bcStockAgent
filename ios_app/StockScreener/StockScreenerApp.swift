import SwiftUI

@main
struct StockScreenerApp: App {
    @StateObject private var store: LocalStore
    @StateObject private var viewModel: AppViewModel

    init() {
        let localStore = LocalStore()
        let model = AppViewModel(store: localStore)
        _store = StateObject(wrappedValue: localStore)
        _viewModel = StateObject(wrappedValue: model)
        BackgroundTaskManager.register(store: localStore, viewModel: model)
        BackgroundTaskManager.schedule(settings: localStore.schedule)
        NotificationService.shared.scheduleDailyReminder(settings: localStore.schedule)
    }

    var body: some Scene {
        WindowGroup {
            ContentView(viewModel: viewModel)
                .environmentObject(store)
        }
    }
}
