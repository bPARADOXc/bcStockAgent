package com.tradingagents.asharescreener.data

import android.content.Context
import androidx.room.Room
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

object DatabaseProvider {
    val MIGRATION_1_2 = object : Migration(1, 2) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL(
                """
                CREATE TABLE IF NOT EXISTS `stock_queries` (
                    `id` INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                    `queriedAt` INTEGER NOT NULL,
                    `code` TEXT NOT NULL,
                    `name` TEXT NOT NULL,
                    `paramsJson` TEXT NOT NULL,
                    `selected` INTEGER NOT NULL,
                    `rejectReason` TEXT NOT NULL,
                    `price` REAL NOT NULL,
                    `oneLotAmount` REAL NOT NULL,
                    `changePct` REAL NOT NULL,
                    `volumeRatio` REAL NOT NULL,
                    `turnoverPct` REAL NOT NULL,
                    `floatMarketCapYi` REAL NOT NULL,
                    `marketCapYi` REAL NOT NULL,
                    `priority` INTEGER NOT NULL,
                    `priorityLabel` TEXT NOT NULL,
                    `actionHint` TEXT NOT NULL,
                    `positionLabel` TEXT NOT NULL,
                    `recentPositionPct` REAL,
                    `klineSource` TEXT NOT NULL,
                    `klineErrors` TEXT NOT NULL
                )
                """.trimIndent()
            )
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_stock_queries_code` ON `stock_queries` (`code`)")
            db.execSQL("CREATE INDEX IF NOT EXISTS `index_stock_queries_queriedAt` ON `stock_queries` (`queriedAt`)")
        }
    }

    fun build(context: Context): AppDatabase =
        Room.databaseBuilder(context.applicationContext, AppDatabase::class.java, "ashare_screener.db")
            .addMigrations(MIGRATION_1_2)
            .build()
}
