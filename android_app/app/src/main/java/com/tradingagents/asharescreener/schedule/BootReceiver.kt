package com.tradingagents.asharescreener.schedule

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.tradingagents.asharescreener.data.SettingsRepository

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val settings = SettingsRepository(context).loadSchedule()
        if (settings.enabled) ScreeningAlarmScheduler(context).scheduleNext(settings)
    }
}
