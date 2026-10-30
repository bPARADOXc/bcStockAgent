package com.tradingagents.asharescreener.data

import android.content.Context
import androidx.core.content.edit
import com.tradingagents.asharescreener.domain.ScheduleSettings
import com.tradingagents.asharescreener.domain.ScreenerParams

class SettingsRepository(context: Context) {
    private val prefs = context.getSharedPreferences("ashare_settings", Context.MODE_PRIVATE)

    fun loadParams(): ScreenerParams =
        runCatching { ScreenerParamsCodec.fromJson(prefs.getString(KEY_PARAMS, "").orEmpty()) }
            .getOrDefault(ScreenerParams())

    fun saveParams(params: ScreenerParams) {
        prefs.edit { putString(KEY_PARAMS, ScreenerParamsCodec.toJson(params)) }
    }

    fun loadSchedule(): ScheduleSettings = ScheduleSettings(
        enabled = prefs.getBoolean(KEY_SCHEDULE_ENABLED, false),
        hour = prefs.getInt(KEY_SCHEDULE_HOUR, 14),
        minute = prefs.getInt(KEY_SCHEDULE_MINUTE, 30),
        nextRunAt = prefs.getLong(KEY_SCHEDULE_NEXT, 0L),
        lastRunText = prefs.getString(KEY_SCHEDULE_LAST, "").orEmpty(),
    )

    fun saveSchedule(settings: ScheduleSettings) {
        prefs.edit {
            putBoolean(KEY_SCHEDULE_ENABLED, settings.enabled)
            putInt(KEY_SCHEDULE_HOUR, settings.hour.coerceIn(0, 23))
            putInt(KEY_SCHEDULE_MINUTE, settings.minute.coerceIn(0, 59))
            putLong(KEY_SCHEDULE_NEXT, settings.nextRunAt)
            putString(KEY_SCHEDULE_LAST, settings.lastRunText)
        }
    }

    fun updateScheduleNextRun(nextRunAt: Long) {
        prefs.edit { putLong(KEY_SCHEDULE_NEXT, nextRunAt) }
    }

    fun updateScheduleLastRun(text: String) {
        prefs.edit { putString(KEY_SCHEDULE_LAST, text) }
    }

    companion object {
        private const val KEY_PARAMS = "screener_params_json"
        private const val KEY_SCHEDULE_ENABLED = "schedule_enabled"
        private const val KEY_SCHEDULE_HOUR = "schedule_hour"
        private const val KEY_SCHEDULE_MINUTE = "schedule_minute"
        private const val KEY_SCHEDULE_NEXT = "schedule_next_run_at"
        private const val KEY_SCHEDULE_LAST = "schedule_last_run_text"
    }
}
