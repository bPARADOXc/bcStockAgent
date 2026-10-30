import SwiftUI
import UIKit

struct ContentView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        TabView(selection: $viewModel.selectedTab) {
            ScreenerView(viewModel: viewModel)
                .tabItem { Label("筛选", systemImage: "line.3.horizontal.decrease.circle") }
                .tag(AppTab.screener)
            SingleStockView(viewModel: viewModel)
                .tabItem { Label("单股", systemImage: "magnifyingglass.circle") }
                .tag(AppTab.single)
            HistoryView(viewModel: viewModel)
                .tabItem { Label("历史", systemImage: "clock") }
                .tag(AppTab.history)
            SettingsView(viewModel: viewModel)
                .tabItem { Label("设置", systemImage: "gearshape") }
                .tag(AppTab.settings)
        }
        .sheet(item: shareURLBinding) { url in
            ShareSheet(url: url)
        }
    }

    private var shareURLBinding: Binding<ShareURL?> {
        Binding(
            get: { viewModel.shareURL.map(ShareURL.init(url:)) },
            set: { next in viewModel.shareURL = next?.url }
        )
    }
}

private struct ScreenerView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ParameterForm(viewModel: viewModel, includeAdvanced: false)
                }
                Section {
                    VStack(alignment: .leading, spacing: 12) {
                        HStack {
                            Button("开始筛选") { viewModel.runManualScreening() }
                                .buttonStyle(.borderedProminent)
                                .disabled(viewModel.isRunning)
                            Button("分享HTML") { viewModel.exportCurrentResult() }
                                .buttonStyle(.bordered)
                                .disabled(viewModel.currentResult == nil)
                        }
                        StatusCard(title: viewModel.isRunning ? "运行中" : "状态", text: viewModel.progress, active: viewModel.isRunning)
                    }
                }
                if let result = viewModel.currentResult {
                    Section("当前结果：入选 \(result.summary.selectedCount) / 保存 \(result.stocks.count)") {
                        ForEach(result.stocks) { stock in
                            StockCard(stock: stock)
                        }
                    }
                }
            }
            .navigationTitle("A股短线筛选")
        }
    }
}

private struct SingleStockView: View {
    @ObservedObject var viewModel: AppViewModel
    @State private var code = ""

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("股票代码，例如 600000", text: $code)
                        .keyboardType(.numbersAndPunctuation)
                    Button("查询") { viewModel.queryStock(code) }
                        .buttonStyle(.borderedProminent)
                        .disabled(viewModel.isQueryingStock)
                    StatusCard(title: viewModel.isQueryingStock ? "查询中" : "状态", text: viewModel.singleStockProgress, active: viewModel.isQueryingStock)
                }
                if let query = viewModel.currentStockQuery {
                    Section("当前查询") {
                        StockCard(stock: query.stock)
                    }
                }
                Section("查询历史") {
                    ForEach(viewModel.store.stockQueryHistory) { query in
                        NavigationLink {
                            StockQueryDetailView(query: query)
                        } label: {
                            StockQueryRow(query: query)
                        }
                    }
                    .onDelete { indexSet in
                        indexSet.map { viewModel.store.stockQueryHistory[$0].id }.forEach(viewModel.store.deleteStockQuery)
                    }
                }
            }
            .navigationTitle("单股")
        }
    }
}

private struct HistoryView: View {
    @ObservedObject var viewModel: AppViewModel

    var body: some View {
        NavigationStack {
            List {
                ForEach(viewModel.store.screeningHistory) { result in
                    NavigationLink {
                        ScreeningDetailView(viewModel: viewModel, result: result)
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(result.createdAt.displayText).font(.headline)
                            Text("入选 \(result.summary.selectedCount) / 保存 \(result.stocks.count)")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .onDelete { indexSet in
                    indexSet.map { viewModel.store.screeningHistory[$0].id }.forEach(viewModel.store.deleteScreeningResult)
                }
            }
            .navigationTitle("筛选历史")
        }
    }
}

private struct ScreeningDetailView: View {
    @ObservedObject var viewModel: AppViewModel
    let result: ScreeningResult
    @State private var filter: ResultFilter = .all

    private var stocks: [ScreenedStock] {
        result.stocks.filter {
            filter == .all || (filter == .selected && $0.selected) || (filter == .rejected && !$0.selected)
        }
    }

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 6) {
                    Text(result.createdAt.displayText).font(.headline)
                    Text("入选 \(result.summary.selectedCount) / 保存 \(result.stocks.count)")
                    Button("分享HTML") { viewModel.exportHistoryResult(result) }
                        .buttonStyle(.bordered)
                }
            }
            Section {
                Picker("范围", selection: $filter) {
                    ForEach(ResultFilter.allCases) { item in
                        Text(item.rawValue).tag(item)
                    }
                }
                .pickerStyle(.segmented)
            }
            Section(filter.rawValue) {
                ForEach(stocks) { stock in
                    StockCard(stock: stock)
                }
            }
        }
        .navigationTitle("历史详情")
    }
}

private struct SettingsView: View {
    @ObservedObject var viewModel: AppViewModel
    @State private var enabled = false
    @State private var hour = 14
    @State private var minute = 30

    var body: some View {
        NavigationStack {
            List {
                Section("常用与高级参数") {
                    ParameterForm(viewModel: viewModel, includeAdvanced: true)
                }
                Section("定时运行") {
                    Toggle("启用", isOn: $enabled)
                    Stepper("小时：\(hour)", value: $hour, in: 0...23)
                    Stepper("分钟：\(minute)", value: $minute, in: 0...59)
                    if let next = viewModel.store.schedule.nextRunAt {
                        Text("下一次：\(next.displayText)")
                    } else {
                        Text("下一次：未计划")
                    }
                    if !viewModel.store.schedule.lastRunText.isEmpty {
                        Text("上次：\(viewModel.store.schedule.lastRunText)")
                            .foregroundStyle(.secondary)
                    }
                    Button("保存定时") {
                        viewModel.saveSchedule(enabled: enabled, hour: hour, minute: minute)
                    }
                    Button("通知权限") {
                        viewModel.requestNotificationAuthorization()
                    }
                }
            }
            .navigationTitle("设置")
            .onAppear {
                enabled = viewModel.store.schedule.enabled
                hour = viewModel.store.schedule.hour
                minute = viewModel.store.schedule.minute
            }
        }
    }
}

private struct ParameterForm: View {
    @ObservedObject var viewModel: AppViewModel
    let includeAdvanced: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                DoubleField("一手最低", value: binding(\.minLotAmount))
                DoubleField("一手最高", value: binding(\.maxLotAmount))
            }
            HStack {
                DoubleField("涨幅最低", value: binding(\.minChangePct))
                DoubleField("涨幅最高", value: binding(\.maxChangePct))
            }
            HStack {
                DoubleField("量比大于", value: binding(\.minVolumeRatio))
                DoubleField("换手最低", value: binding(\.minTurnoverPct))
            }
            Toggle(
                "换手上限不限",
                isOn: Binding(
                    get: { viewModel.store.params.maxTurnoverPct == nil },
                    set: { unlimited in viewModel.mutateParams { $0.maxTurnoverPct = unlimited ? nil : 10 } }
                )
            )
            if viewModel.store.params.maxTurnoverPct != nil {
                DoubleField(
                    "换手最高",
                    value: Binding(
                        get: { viewModel.store.params.maxTurnoverPct ?? 10 },
                        set: { value in viewModel.mutateParams { $0.maxTurnoverPct = value } }
                    )
                )
            }
            HStack {
                DoubleField("流通市值低", value: binding(\.minFloatMarketCapYi))
                DoubleField("流通市值高", value: binding(\.maxFloatMarketCapYi))
            }
            if includeAdvanced {
                Divider()
                HStack {
                    IntField("放量天数", value: intBinding(\.volumeGrowthDays, min: 1))
                    IntField("MA天数", value: intBinding(\.maSlopeDays, min: 1))
                }
                HStack {
                    IntField("K线回看", value: intBinding(\.klineLookbackDays, min: 25))
                    IntField("位置区间", value: intBinding(\.recentPositionDays, min: 2))
                }
                HStack {
                    IntField("批次大小", value: intBinding(\.quoteBatchSize, min: 10))
                    IntField("返回数量", value: intBinding(\.limit, min: 1))
                }
                HStack {
                    IntField("批次间隔ms", value: intBinding(\.quoteBatchIntervalMs, min: 300))
                    IntField("K线间隔ms", value: intBinding(\.klineRequestIntervalMs, min: 500))
                }
                IntField("东财间隔ms", value: intBinding(\.eastmoneyMinIntervalMs, min: 1000))
            } else {
                Text("高级参数在设置页调整")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func binding(_ keyPath: WritableKeyPath<ScreenerParams, Double>) -> Binding<Double> {
        Binding(
            get: { viewModel.store.params[keyPath: keyPath] },
            set: { value in viewModel.mutateParams { $0[keyPath: keyPath] = value } }
        )
    }

    private func intBinding(_ keyPath: WritableKeyPath<ScreenerParams, Int>, min: Int) -> Binding<Int> {
        Binding(
            get: { viewModel.store.params[keyPath: keyPath] },
            set: { value in viewModel.mutateParams { $0[keyPath: keyPath] = max(value, min) } }
        )
    }
}

private struct DoubleField: View {
    let label: String
    @Binding var value: Double

    init(_ label: String, value: Binding<Double>) {
        self.label = label
        _value = value
    }

    var body: some View {
        TextField(label, value: $value, format: .number)
            .keyboardType(.decimalPad)
            .textFieldStyle(.roundedBorder)
    }
}

private struct IntField: View {
    let label: String
    @Binding var value: Int

    init(_ label: String, value: Binding<Int>) {
        self.label = label
        _value = value
    }

    var body: some View {
        TextField(label, value: $value, format: .number)
            .keyboardType(.numberPad)
            .textFieldStyle(.roundedBorder)
    }
}

private struct StatusCard: View {
    let title: String
    let text: String
    let active: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.headline)
            Text(text).font(.subheadline)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(active ? Color.blue.opacity(0.12) : Color.gray.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct StockCard: View {
    let stock: ScreenedStock

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("\(stock.code) \(stock.name)").font(.headline)
                    Text("P\(stock.priority) \(stock.priorityLabel) · \(stock.positionLabel)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Text(stock.selected ? "入选" : "未入选")
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(stock.selected ? Color.green.opacity(0.16) : Color.red.opacity(0.16))
                    .clipShape(Capsule())
            }
            Text("价格 \(stock.price.compactText)  涨幅 \(stock.changePct.compactText)%  量比 \(stock.volumeRatio.compactText)")
            Text("换手 \(stock.turnoverPct.compactText)%  流通市值 \(stock.floatMarketCapYi.compactText)亿")
            Text("K线：\(stock.klineSource)")
                .font(.footnote)
                .foregroundStyle(.secondary)
            if !stock.selected {
                Text("原因：\(stock.rejectReason.isEmpty ? "未说明" : stock.rejectReason)")
                    .foregroundStyle(.red)
            }
        }
        .padding(.vertical, 6)
    }
}

private struct StockQueryRow: View {
    let query: StockQueryResult

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(query.stock.code) \(query.stock.name)").font(.headline)
            Text("\(query.queriedAt.displayText) · \(query.stock.selected ? "满足" : "不满足")")
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
    }
}

private struct StockQueryDetailView: View {
    let query: StockQueryResult

    var body: some View {
        List {
            Section {
                Text(query.queriedAt.displayText)
                StockCard(stock: query.stock)
            }
        }
        .navigationTitle("单股详情")
    }
}

private struct ShareURL: Identifiable {
    let url: URL
    var id: URL { url }
}

private struct ShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
