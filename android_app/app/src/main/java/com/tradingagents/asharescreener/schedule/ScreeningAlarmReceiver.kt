package com.tradingagents.asharescreener.schedule

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

class ScreeningAlarmReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ScreeningAlarmScheduler.ACTION_RUN_SCHEDULED_SCREENING) return
        ContextCompat.startForegroundService(
            context,
            Intent(context, ScheduledScreeningService::class.java).apply {
                action = ScheduledScreeningService.ACTION_RUN
            },
        )
    }
}
