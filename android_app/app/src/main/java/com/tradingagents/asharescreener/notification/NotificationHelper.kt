package com.tradingagents.asharescreener.notification

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.tradingagents.asharescreener.MainActivity
import com.tradingagents.asharescreener.domain.ScreeningResult

class NotificationHelper(private val context: Context) {
    init {
        ensureChannel()
    }

    fun runningNotification(): Notification =
        NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_notify_sync)
            .setContentTitle("A股短线筛选")
            .setContentText("正在筛选，请保持网络可用")
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(openAppIntent())
            .build()

    fun notifyCompleted(runId: Long, result: ScreeningResult) {
        val text = NotificationTextBuilder.completedText(result)
        safeNotify(
            NOTIFICATION_DONE,
            NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("筛选完成")
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setContentIntent(openRunIntent(runId))
                .setAutoCancel(true)
                .build()
        )
    }

    fun notifySkipped(message: String) {
        safeNotify(
            NOTIFICATION_DONE,
            NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("定时筛选已跳过")
                .setContentText(message)
                .setStyle(NotificationCompat.BigTextStyle().bigText(message))
                .setContentIntent(openAppIntent())
                .setAutoCancel(true)
                .build()
        )
    }

    fun notifyFailed(message: String) {
        safeNotify(
            NOTIFICATION_DONE,
            NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle("定时筛选失败")
                .setContentText(message)
                .setStyle(NotificationCompat.BigTextStyle().bigText(message))
                .setContentIntent(openAppIntent())
                .setAutoCancel(true)
                .build()
        )
    }

    private fun safeNotify(id: Int, notification: Notification) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        runCatching { NotificationManagerCompat.from(context).notify(id, notification) }
    }

    private fun openAppIntent(): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
        return PendingIntent.getActivity(context, 10, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun openRunIntent(runId: Long): PendingIntent {
        val intent = Intent(context, MainActivity::class.java).apply {
            putExtra(EXTRA_OPEN_RUN_ID, runId)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }
        return PendingIntent.getActivity(context, 11, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(CHANNEL_ID, "A股筛选通知", NotificationManager.IMPORTANCE_DEFAULT)
        manager.createNotificationChannel(channel)
    }

    companion object {
        const val CHANNEL_ID = "ashare_screening"
        const val FOREGROUND_ID = 1001
        const val NOTIFICATION_DONE = 1002
        const val EXTRA_OPEN_RUN_ID = "open_run_id"
    }
}

object NotificationTextBuilder {
    fun completedText(result: ScreeningResult): String {
        val top = result.stocks.filter { it.selected }
            .take(3)
            .joinToString("、") { "${it.code} ${it.name}" }
            .ifBlank { "无入选股票" }
        return "入选 ${result.summary.selectedCount} 只，筛过 ${result.stocks.size} 只；前3：$top"
    }
}
