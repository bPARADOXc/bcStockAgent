package com.tradingagents.asharescreener.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Delete
import androidx.room.Embedded
import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Relation
import androidx.room.RoomDatabase
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "screening_runs")
data class ScreeningRunEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val createdAt: Long,
    val paramsJson: String,
    val summaryJson: String,
    val selectedCount: Int,
    val screenedCount: Int,
)

@Entity(
    tableName = "screened_stocks",
    foreignKeys = [
        ForeignKey(
            entity = ScreeningRunEntity::class,
            parentColumns = ["id"],
            childColumns = ["runId"],
            onDelete = ForeignKey.CASCADE,
        )
    ],
    indices = [Index("runId"), Index("code")],
)
data class ScreenedStockEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val runId: Long,
    val selected: Boolean,
    val rejectReason: String,
    val code: String,
    val name: String,
    val price: Double,
    val changePct: Double,
    val volumeRatio: Double,
    val turnoverPct: Double,
    val floatMarketCapYi: Double,
    val priority: Int,
    val priorityLabel: String,
    val positionLabel: String,
    val klineSource: String,
    val klineErrors: String,
)

data class ScreeningRunWithStocks(
    @Embedded val run: ScreeningRunEntity,
    @Relation(parentColumn = "id", entityColumn = "runId")
    val stocks: List<ScreenedStockEntity>,
)

@Entity(tableName = "stock_queries", indices = [Index("code"), Index("queriedAt")])
data class StockQueryEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val queriedAt: Long,
    val code: String,
    val name: String,
    val paramsJson: String,
    val selected: Boolean,
    val rejectReason: String,
    val price: Double,
    val oneLotAmount: Double,
    val changePct: Double,
    val volumeRatio: Double,
    val turnoverPct: Double,
    val floatMarketCapYi: Double,
    val marketCapYi: Double,
    val priority: Int,
    val priorityLabel: String,
    val actionHint: String,
    val positionLabel: String,
    val recentPositionPct: Double?,
    val klineSource: String,
    val klineErrors: String,
)

@Dao
interface ScreeningDao {
    @Query("SELECT * FROM screening_runs ORDER BY createdAt DESC")
    fun observeRuns(): Flow<List<ScreeningRunEntity>>

    @Transaction
    @Query("SELECT * FROM screening_runs WHERE id = :runId")
    fun observeRun(runId: Long): Flow<ScreeningRunWithStocks?>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertRun(run: ScreeningRunEntity): Long

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertStocks(stocks: List<ScreenedStockEntity>)

    @Query("DELETE FROM screening_runs WHERE id = :runId")
    suspend fun deleteRun(runId: Long)

    @Query("SELECT * FROM stock_queries ORDER BY queriedAt DESC")
    fun observeStockQueries(): Flow<List<StockQueryEntity>>

    @Query("SELECT * FROM stock_queries WHERE id = :queryId")
    fun observeStockQuery(queryId: Long): Flow<StockQueryEntity?>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertStockQuery(query: StockQueryEntity): Long

    @Query("DELETE FROM stock_queries WHERE id = :queryId")
    suspend fun deleteStockQuery(queryId: Long)
}

@Database(
    entities = [ScreeningRunEntity::class, ScreenedStockEntity::class, StockQueryEntity::class],
    version = 2,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun screeningDao(): ScreeningDao
}
