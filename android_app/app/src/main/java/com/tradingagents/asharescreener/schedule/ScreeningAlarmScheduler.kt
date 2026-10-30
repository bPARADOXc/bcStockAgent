package com.tradingagents.asharescreener.schedule

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import com.tradingagents.asharescreener.data.SettingsRepository
import com.tradingagents.asharescreener.domain.ScheduleSettings
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.ZoneId

class ScreeningAlarmScheduler(private val context: Context) {
    private val alarmManager = context.getSystemService(AlarmManager::class.java)

    fun scheduleNext(settings: ScheduleSettings): Long {
        if (!settings.enabled) {
            cancel()
            return 0L
        }
        val triggerAt = nextTriggerAt(settings.hour, settings.minute)
        val pending = pendingIntent()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && !alarmManager.canScheduleExactAlarms()) {
            alarmManager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
        } else {
            alarmManager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAt, pending)
        }
        SettingsRepository(context).updateScheduleNextRun(triggerAt)
        return triggerAt
    }

    fun cancel() {
        alarmManager.cancel(pendingIntent())
        SettingsRepository(context).updateScheduleNextRun(0L)
    }

    fun canScheduleExactAlarms(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S || alarmManager.canScheduleExactAlarms()

    private fun pendingIntent(): PendingIntent {
        val intent = Intent(context, ScreeningAlarmReceiver::class.java).apply { action = ACTION_RUN_SCHEDULED_SCREENING }
        return PendingIntent.getBroadcast(context, 20, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    companion object {
        const val ACTION_RUN_SCHEDULED_SCREENING = "com.tradingagents.asharescreener.RUN_SCHEDULED_SCREENING"

        fun nextTriggerAt(hour: Int, minute: Int, now: LocalDateTime = LocalDateTime.now()): Long {
            val zone = ZoneId.systemDefault()
            var target = LocalDateTime.of(now.toLocalDate(), LocalTime.of(hour.coerceIn(0, 23), minute.coerceIn(0, 59)))
            if (!target.isAfter(now)) target = target.plusDays(1)
            return target.atZone(zone).toInstant().toEpochMilli()
        }

        fun formatEpochMillis(value: Long): String =
            if (value <= 0L) "" else LocalDateTime.ofInstant(Instant.ofEpochMilli(value), ZoneId.systemDefault()).toString().replace("T", " ")
    }
}
