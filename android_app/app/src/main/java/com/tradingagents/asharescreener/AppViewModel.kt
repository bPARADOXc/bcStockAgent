package com.tradingagents.asharescreener

import android.app.Application
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.tradingagents.asharescreener.data.DatabaseProvider
import com.tradingagents.asharescreener.data.HistoryRepository
import com.tradingagents.asharescreener.data.ScreeningRunEntity
import com.tradingagents.asharescreener.data.ScreeningRunWithStocks
import com.tradingagents.asharescreener.data.SettingsRepository
import com.tradingagents.asharescreener.data.SingleStockRepository
import com.tradingagents.asharescreener.data.StockQueryEntity
import com.tradingagents.asharescreener.domain.AshareScreener
import com.tradingagents.asharescreener.domain.ScheduleSettings
import com.tradingagents.asharescreener.domain.ScreenerParams
import com.tradingagents.asharescreener.domain.ScreeningResult
import com.tradingagents.asharescreener.domain.StockQueryResult
import com.tradingagents.asharescreener.export.HtmlReportExporter
import com.tradingagents.asharescreener.network.EastmoneyRateLimiter
import com.tradingagents.asharescreener.network.KlineRepository
import com.tradingagents.asharescreener.network.QuoteRepository
import com.tradingagents.asharescreener.schedule.ScreeningAlarmScheduler
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import java.time.Duration

enum class AppScreen { Home, SingleStock, SingleStockDetail, History, Detail, Settings }

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val db = DatabaseProvider.build(application)
    private val settingsRepository = SettingsRepository(application)
    private val historyRepository = HistoryRepository(db.screeningDao())
    private val scheduler = ScreeningAlarmScheduler(application)
    private val client = OkHttpClient.Builder()
        .callTimeout(Duration.ofSeconds(25))
        .connectTimeout(Duration.ofSeconds(10))
        .readTimeout(Duration.ofSeconds(20))
        .build()
    private val exporter = HtmlReportExporter(application)

    var screen by mutableStateOf(AppScreen.Home)
        private set
    var params by mutableStateOf(settingsRepository.loadParams())
        private set
    var schedule by mutableStateOf(settingsRepository.loadSchedule())
        private set
    var canScheduleExactAlarm by mutableStateOf(scheduler.canScheduleExactAlarms())
        private set
    var runs by mutableStateOf<List<ScreeningRunEntity>>(emptyList())
        private set
    var selectedRun by mutableStateOf<ScreeningRunWithStocks?>(null)
        private set
    var stockQueries by mutableStateOf<List<StockQueryEntity>>(emptyList())
        private set
    var selectedStockQuery by mutableStateOf<StockQueryEntity?>(null)
        private set
    var currentResult by mutableStateOf<ScreeningResult?>(null)
        private set
    var currentStockQuery by mutableStateOf<StockQueryResult?>(null)
        private set
    var progress by mutableStateOf("等待运行")
        private set
    var singleStockProgress by mutableStateOf("输入代码后查询")
        private set
    var running by mutableStateOf(false)
        private set
    var queryingStock by mutableStateOf(false)
        private set
    var shareUri by mutableStateOf<Uri?>(null)
        private set

    private var runJob: Job? = null
    private var detailJob: Job? = null
    private var queryJob: Job? = null
    private var queryDetailJob: Job? = null

    init {
        viewModelScope.launch {
            historyRepository.observeRuns().collectLatest { runs = it }
        }
        viewModelScope.launch {
            historyRepository.observeStockQueries().collectLatest { stockQueries = it }
        }
    }

    fun showHome() {
        screen = AppScreen.Home
    }

    fun showSingleStock() {
        screen = AppScreen.SingleStock
    }

    fun showHistory() {
        screen = AppScreen.History
    }

    fun showSettings() {
        refreshScheduleState()
        screen = AppScreen.Settings
    }

    fun openRun(runId: Long) {
        detailJob?.cancel()
        screen = AppScreen.Detail
        detailJob = viewModelScope.launch {
            historyRepository.observeRun(runId).collectLatest { selectedRun = it }
        }
    }

    fun openStockQuery(queryId: Long) {
        queryDetailJob?.cancel()
        screen = AppScreen.SingleStockDetail
        queryDetailJob = viewModelScope.launch {
            historyRepository.observeStockQuery(queryId).collectLatest { selectedStockQuery = it }
        }
    }

    fun updateParams(next: ScreenerParams) {
        params = next
        settingsRepository.saveParams(next)
    }

    fun updateSchedule(enabled: Boolean, hour: Int, minute: Int) {
        val base = schedule.copy(enabled = enabled, hour = hour.coerceIn(0, 23), minute = minute.coerceIn(0, 59))
        settingsRepository.saveSchedule(base)
        val nextRunAt = if (enabled) scheduler.scheduleNext(base) else {
            scheduler.cancel()
            0L
        }
        schedule = settingsRepository.loadSchedule().copy(nextRunAt = nextRunAt)
        settingsRepository.saveSchedule(schedule)
        refreshScheduleState()
    }

    fun refreshScheduleState() {
        canScheduleExactAlarm = scheduler.canScheduleExactAlarms()
        schedule = settingsRepository.loadSchedule()
    }

    fun runScreening() {
        if (running) return
        currentResult = null
        progress = "准备启动"
        running = true
        runJob = viewModelScope.launch {
            val rateLimiter = EastmoneyRateLimiter(params.eastmoneyMinIntervalMs)
            val screener = AshareScreener(
                quoteRepository = QuoteRepository(client),
                klineRepository = KlineRepository(client, rateLimiter),
            )
            runCatching {
                screener.run(params) { message -> progress = message }
            }.onSuccess { result ->
                currentResult = result
                historyRepository.save(result)
                progress = "筛选完成，已保存到历史"
            }.onFailure { exc ->
                progress = "运行失败：${exc.message ?: exc::class.java.simpleName}"
            }
            running = false
        }
    }

    fun cancelRun() {
        runJob?.cancel()
        running = false
        progress = "已取消"
    }

    fun queryStock(input: String) {
        if (queryingStock) return
        currentStockQuery = null
        singleStockProgress = "准备查询"
        queryingStock = true
        queryJob = viewModelScope.launch {
            val rateLimiter = EastmoneyRateLimiter(params.eastmoneyMinIntervalMs)
            val repository = SingleStockRepository(
                quoteRepository = QuoteRepository(client),
                klineRepository = KlineRepository(client, rateLimiter),
            )
            runCatching {
                singleStockProgress = "正在获取实时行情和K线"
                repository.query(input, params)
            }.onSuccess { result ->
                currentStockQuery = result
                historyRepository.saveStockQuery(result)
                singleStockProgress = "查询完成，已保存到历史"
            }.onFailure { exc ->
                singleStockProgress = "查询失败：${exc.message ?: exc::class.java.simpleName}"
            }
            queryingStock = false
        }
    }

    fun deleteRun(runId: Long) {
        viewModelScope.launch {
            historyRepository.delete(runId)
            if (selectedRun?.run?.id == runId) {
                selectedRun = null
                screen = AppScreen.History
            }
        }
    }

    fun deleteStockQuery(queryId: Long) {
        viewModelScope.launch {
            historyRepository.deleteStockQuery(queryId)
            if (selectedStockQuery?.id == queryId) {
                selectedStockQuery = null
                screen = AppScreen.SingleStock
            }
        }
    }

    fun shareCurrent() {
        val result = currentResult ?: return
        shareUri = exporter.exportCurrent(result)
    }

    fun shareSelectedRun() {
        val detail = selectedRun ?: return
        shareUri = exporter.exportHistory(detail.run, detail.stocks)
    }

    fun consumeShareUri() {
        shareUri = null
    }
}
