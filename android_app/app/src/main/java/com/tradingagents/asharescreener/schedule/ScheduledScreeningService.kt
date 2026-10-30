package com.tradingagents.asharescreener.schedule

import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.tradingagents.asharescreener.data.DatabaseProvider
import com.tradingagents.asharescreener.data.HistoryRepository
import com.tradingagents.asharescreener.data.SettingsRepository
import com.tradingagents.asharescreener.domain.AshareScreener
import com.tradingagents.asharescreener.domain.ScreeningResult
import com.tradingagents.asharescreener.domain.ScreeningSummary
import com.tradingagents.asharescreener.notification.NotificationHelper
import com.tradingagents.asharescreener.network.EastmoneyRateLimiter
import com.tradingagents.asharescreener.network.KlineRepository
import com.tradingagents.asharescreener.network.QuoteRepository
import com.tradingagents.asharescreener.network.TradingDayChecker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import java.time.Duration
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

class ScheduledScreeningService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action != ACTION_RUN) return START_NOT_STICKY
        val notifications = NotificationHelper(this)
        startAsForeground(notifications)
        scope.launch { runScheduled(notifications) }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun runScheduled(notifications: NotificationHelper) {
        val settingsRepository = SettingsRepository(this)
        val settings = settingsRepository.loadSchedule()
        val params = settingsRepository.loadParams()
        val client = OkHttpClient.Builder()
            .callTimeout(Duration.ofSeconds(25))
            .connectTimeout(Duration.ofSeconds(10))
            .readTimeout(Duration.ofSeconds(20))
            .build()
        val rateLimiter = EastmoneyRateLimiter(params.eastmoneyMinIntervalMs)

        try {
            if (!settings.enabled) {
                settingsRepository.updateScheduleLastRun("定时已关闭，未运行")
                return
            }
            val isTradingDay = runCatching {
                TradingDayChecker(client, rateLimiter).isTradingDay()
            }.getOrElse { exc ->
                val message = "交易日判断失败：${exc.message ?: exc::class.java.simpleName}"
                settingsRepository.updateScheduleLastRun(message)
                notifications.notifyFailed(message)
                return
            }
            if (!isTradingDay) {
                val message = "非交易日已跳过：${nowText()}"
                val db = DatabaseProvider.build(this)
                HistoryRepository(db.screeningDao()).save(skippedResult(params))
                db.close()
                settingsRepository.updateScheduleLastRun(message)
                notifications.notifySkipped(message)
                return
            }

            val db = DatabaseProvider.build(this)
            val historyRepository = HistoryRepository(db.screeningDao())
            val screener = AshareScreener(
                quoteRepository = QuoteRepository(client),
                klineRepository = KlineRepository(client, rateLimiter),
            )
            val result = screener.run(params) { }
            val runId = historyRepository.save(result)
            db.close()
            val message = "筛选完成：入选 ${result.summary.selectedCount} / 筛过 ${result.stocks.size}"
            settingsRepository.updateScheduleLastRun(message)
            notifications.notifyCompleted(runId, result)
        } catch (exc: Exception) {
            val message = "定时筛选失败：${exc.message ?: exc::class.java.simpleName}"
            settingsRepository.updateScheduleLastRun(message)
            notifications.notifyFailed(message)
        } finally {
            ScreeningAlarmScheduler(this).scheduleNext(settingsRepository.loadSchedule())
            stopForegroundCompat()
            stopSelf()
        }
    }

    private fun startAsForeground(notifications: NotificationHelper) {
        val notification = notifications.runningNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NotificationHelper.FOREGROUND_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NotificationHelper.FOREGROUND_ID, notification)
        }
    }

    @Suppress("DEPRECATION")
    private fun stopForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            stopForeground(true)
        }
    }

    private fun skippedResult(params: com.tradingagents.asharescreener.domain.ScreenerParams) = ScreeningResult(
        params = params,
        summary = ScreeningSummary(
            asOf = nowText(),
            quoteCount = 0,
            quoteFilterCount = 0,
            selectedCount = 0,
            rejectedCount = 0,
            returnedCount = 0,
        ),
        stocks = emptyList(),
    )

    private fun nowText(): String = LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))

    companion object {
        const val ACTION_RUN = "com.tradingagents.asharescreener.SCHEDULED_RUN"
    }
}
