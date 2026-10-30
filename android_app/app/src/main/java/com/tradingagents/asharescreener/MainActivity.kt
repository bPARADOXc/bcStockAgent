package com.tradingagents.asharescreener

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tradingagents.asharescreener.data.ScreenedStockEntity
import com.tradingagents.asharescreener.data.ScreeningRunEntity
import com.tradingagents.asharescreener.data.StockQueryEntity
import com.tradingagents.asharescreener.domain.ScheduleSettings
import com.tradingagents.asharescreener.domain.ScreenedStock
import com.tradingagents.asharescreener.domain.ScreenerParams
import com.tradingagents.asharescreener.domain.StockQueryResult
import com.tradingagents.asharescreener.notification.NotificationHelper
import com.tradingagents.asharescreener.schedule.ScreeningAlarmScheduler
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : ComponentActivity() {
    private val viewModel: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        handleIntent(intent)
        setContent {
            MaterialTheme {
                Surface(Modifier.fillMaxSize()) {
                    val notificationPermissionLauncher = rememberLauncherForActivityResult(
                        ActivityResultContracts.RequestPermission()
                    ) { }
                    val uri = viewModel.shareUri
                    LaunchedEffect(uri) {
                        if (uri != null) {
                            startActivity(
                                Intent(Intent.ACTION_SEND).apply {
                                    type = "text/html"
                                    putExtra(Intent.EXTRA_STREAM, uri)
                                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                                }.let { Intent.createChooser(it, "分享筛选报告") }
                            )
                            viewModel.consumeShareUri()
                        }
                    }
                    AppRoot(
                        vm = viewModel,
                        onRequestNotificationPermission = {
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                            }
                        },
                        onOpenExactAlarmSettings = { openExactAlarmSettings() },
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        viewModel.refreshScheduleState()
    }

    private fun handleIntent(intent: Intent?) {
        val runId = intent?.getLongExtra(NotificationHelper.EXTRA_OPEN_RUN_ID, -1L) ?: -1L
        if (runId > 0) viewModel.openRun(runId)
    }

    private fun openExactAlarmSettings() {
        val packageUri = Uri.parse("package:$packageName")
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, packageUri)
        } else {
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, packageUri)
        }
        runCatching { startActivity(intent) }
            .onFailure { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, packageUri)) }
    }
}

@Composable
private fun AppRoot(
    vm: AppViewModel,
    onRequestNotificationPermission: () -> Unit,
    onOpenExactAlarmSettings: () -> Unit,
) {
    Scaffold(
        bottomBar = {
            Surface(tonalElevation = 3.dp) {
                Row(Modifier.fillMaxWidth().padding(6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    NavItem("筛选", vm.screen == AppScreen.Home, vm::showHome, Modifier.weight(1f))
                    NavItem("单股", vm.screen == AppScreen.SingleStock || vm.screen == AppScreen.SingleStockDetail, vm::showSingleStock, Modifier.weight(1f))
                    NavItem("历史", vm.screen == AppScreen.History || vm.screen == AppScreen.Detail, vm::showHistory, Modifier.weight(1f))
                    NavItem("设置", vm.screen == AppScreen.Settings, vm::showSettings, Modifier.weight(1f))
                }
            }
        }
    ) { padding ->
        Surface(Modifier.fillMaxSize().padding(padding)) {
            when (vm.screen) {
                AppScreen.Home -> HomeScreen(vm)
                AppScreen.SingleStock -> SingleStockScreen(vm)
                AppScreen.SingleStockDetail -> SingleStockDetailScreen(vm)
                AppScreen.History -> HistoryScreen(vm)
                AppScreen.Detail -> DetailScreen(vm)
                AppScreen.Settings -> SettingsScreen(vm, onRequestNotificationPermission, onOpenExactAlarmSettings)
            }
        }
    }
}

@Composable
private fun NavItem(label: String, selected: Boolean, onClick: () -> Unit, modifier: Modifier = Modifier) {
    if (selected) {
        Button(onClick = onClick, modifier = modifier) { Text(label) }
    } else {
        TextButton(onClick = onClick, modifier = modifier) { Text(label) }
    }
}

@Composable
private fun HomeScreen(vm: AppViewModel) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            HeaderBar(title = "A股短线筛选", subtitle = "手动运行会保存到App历史，并可分享HTML报告")
        }
        item {
            ParamForm(
                params = vm.params,
                onChange = vm::updateParams,
                includeAdvanced = false,
            )
        }
        item {
            Card {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("运行", fontWeight = FontWeight.Bold)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = !vm.running, onClick = vm::runScreening) { Text("开始筛选") }
                        OutlinedButton(enabled = vm.running, onClick = vm::cancelRun) { Text("取消") }
                        OutlinedButton(enabled = vm.currentResult != null, onClick = vm::shareCurrent) { Text("分享HTML") }
                    }
                }
            }
        }
        item { ProgressCard(vm.progress, vm.running) }
        vm.currentResult?.let { result ->
            item {
                Text("当前结果：入选 ${result.summary.selectedCount} / 保存 ${result.stocks.size}", fontWeight = FontWeight.Bold)
            }
            items(result.stocks) { stock -> StockCard(stock) }
        }
    }
}

@Composable
private fun SingleStockScreen(vm: AppViewModel) {
    var code by remember { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { HeaderBar(title = "单股查询", subtitle = "查询实时指标、K线条件、均线趋势和当前参数匹配结果") }
        item {
            Card {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedTextField(
                        value = code,
                        onValueChange = { code = it.take(12) },
                        label = { Text("股票代码") },
                        placeholder = { Text("例如 600000 或 sh600000") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = !vm.queryingStock, onClick = { vm.queryStock(code) }) { Text("查询") }
                    }
                }
            }
        }
        item { ProgressCard(vm.singleStockProgress, vm.queryingStock) }
        vm.currentStockQuery?.let { result ->
            item { StockQueryCard(result) }
        }
        item { Text("查询历史", fontWeight = FontWeight.Bold) }
        items(vm.stockQueries) { query ->
            StockQueryEntityCard(
                query = query,
                onOpen = { vm.openStockQuery(query.id) },
                onDelete = { vm.deleteStockQuery(query.id) },
            )
        }
    }
}

@Composable
private fun SingleStockDetailScreen(vm: AppViewModel) {
    val query = vm.selectedStockQuery
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            HeaderBar(
                title = "单股详情",
                subtitle = "历史查询记录",
                left = { OutlinedButton(onClick = vm::showSingleStock) { Text("返回") } },
            )
        }
        if (query == null) {
            item { Text("正在加载...") }
        } else {
            item { StockQueryEntityCard(query, onOpen = {}, onDelete = { vm.deleteStockQuery(query.id) }, showActions = false) }
        }
    }
}

@Composable
private fun HistoryScreen(vm: AppViewModel) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { HeaderBar(title = "筛选历史", subtitle = "按运行时间倒序保存所有实时行情通过的股票") }
        items(vm.runs) { run -> RunCard(run, onOpen = { vm.openRun(run.id) }, onDelete = { vm.deleteRun(run.id) }) }
    }
}

@Composable
private fun DetailScreen(vm: AppViewModel) {
    val detail = vm.selectedRun
    var filter by remember { mutableStateOf("全部") }
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            HeaderBar(
                title = "历史详情",
                subtitle = "入选和未入选股票均保留，便于复盘原因",
                left = { OutlinedButton(onClick = vm::showHistory) { Text("返回") } },
                right = { Button(onClick = vm::shareSelectedRun, enabled = detail != null) { Text("分享HTML") } },
            )
        }
        if (detail == null) {
            item { Text("正在加载...") }
        } else {
            item {
                Text("入选 ${detail.run.selectedCount} / 保存 ${detail.run.screenedCount}", fontWeight = FontWeight.Bold)
            }
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("全部", "入选", "未入选").forEach { item ->
                        FilterChip(selected = filter == item, onClick = { filter = item }, label = { Text(item) })
                    }
                }
            }
            val stocks = detail.stocks.filter {
                filter == "全部" || (filter == "入选" && it.selected) || (filter == "未入选" && !it.selected)
            }
            items(stocks) { stock -> StockEntityCard(stock) }
        }
    }
}

@Composable
private fun SettingsScreen(
    vm: AppViewModel,
    onRequestNotificationPermission: () -> Unit,
    onOpenExactAlarmSettings: () -> Unit,
) {
    LazyColumn(Modifier.fillMaxSize().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { HeaderBar(title = "设置", subtitle = "手动筛选和定时筛选共用这些参数") }
        item {
            ParamForm(
                params = vm.params,
                onChange = vm::updateParams,
                includeAdvanced = true,
            )
        }
        item {
            ScheduleCard(
                schedule = vm.schedule,
                canExact = vm.canScheduleExactAlarm,
                onSave = vm::updateSchedule,
                onRequestNotificationPermission = onRequestNotificationPermission,
                onOpenExactAlarmSettings = onOpenExactAlarmSettings,
            )
        }
    }
}

@Composable
private fun ParamForm(params: ScreenerParams, onChange: (ScreenerParams) -> Unit, includeAdvanced: Boolean) {
    Card {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("常用参数", fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                NumberField("一手最低(元)", params.minLotAmount, { onChange(params.copy(minLotAmount = it)) }, Modifier.weight(1f))
                NumberField("一手最高(元)", params.maxLotAmount, { onChange(params.copy(maxLotAmount = it)) }, Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                NumberField("涨幅最低(%)", params.minChangePct, { onChange(params.copy(minChangePct = it)) }, Modifier.weight(1f))
                NumberField("涨幅最高(%)", params.maxChangePct, { onChange(params.copy(maxChangePct = it)) }, Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                NumberField("量比大于", params.minVolumeRatio, { onChange(params.copy(minVolumeRatio = it)) }, Modifier.weight(1f))
                NumberField("换手最低(%)", params.minTurnoverPct, { onChange(params.copy(minTurnoverPct = it)) }, Modifier.weight(1f))
            }
            MaxTurnoverRow(params, onChange)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                NumberField("流通市值低(亿)", params.minFloatMarketCapYi, { onChange(params.copy(minFloatMarketCapYi = it)) }, Modifier.weight(1f))
                NumberField("流通市值高(亿)", params.maxFloatMarketCapYi, { onChange(params.copy(maxFloatMarketCapYi = it)) }, Modifier.weight(1f))
            }
            if (includeAdvanced) {
                HorizontalDivider()
                Text("高级参数", fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    IntField("放量天数", params.volumeGrowthDays, { onChange(params.copy(volumeGrowthDays = it.coerceAtLeast(1))) }, Modifier.weight(1f))
                    IntField("MA天数", params.maSlopeDays, { onChange(params.copy(maSlopeDays = it.coerceAtLeast(1))) }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    IntField("K线回看", params.klineLookbackDays, { onChange(params.copy(klineLookbackDays = it.coerceAtLeast(25))) }, Modifier.weight(1f))
                    IntField("位置区间", params.recentPositionDays, { onChange(params.copy(recentPositionDays = it.coerceAtLeast(2))) }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    IntField("批次大小", params.quoteBatchSize, { onChange(params.copy(quoteBatchSize = it.coerceIn(10, 200))) }, Modifier.weight(1f))
                    LongField("批次间隔ms", params.quoteBatchIntervalMs, { onChange(params.copy(quoteBatchIntervalMs = it.coerceAtLeast(300L))) }, Modifier.weight(1f))
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    LongField("K线间隔ms", params.klineRequestIntervalMs, { onChange(params.copy(klineRequestIntervalMs = it.coerceAtLeast(500L))) }, Modifier.weight(1f))
                    LongField("东财间隔ms", params.eastmoneyMinIntervalMs, { onChange(params.copy(eastmoneyMinIntervalMs = it.coerceAtLeast(1000L))) }, Modifier.weight(1f))
                }
                IntField("返回数量", params.limit, { onChange(params.copy(limit = it.coerceAtLeast(1))) }, Modifier.fillMaxWidth())
            } else {
                Text("高级参数在“设置”页调整。", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun MaxTurnoverRow(params: ScreenerParams, onChange: (ScreenerParams) -> Unit) {
    val unlimited = params.maxTurnoverPct == null
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("换手上限", fontWeight = FontWeight.Medium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("不限")
                Switch(
                    checked = unlimited,
                    onCheckedChange = { checked ->
                        onChange(params.copy(maxTurnoverPct = if (checked) null else 10.0))
                    },
                )
            }
        }
        if (!unlimited) {
            NumberField("换手最高(%)", params.maxTurnoverPct ?: 10.0, { onChange(params.copy(maxTurnoverPct = it)) }, Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun ScheduleCard(
    schedule: ScheduleSettings,
    canExact: Boolean,
    onSave: (Boolean, Int, Int) -> Unit,
    onRequestNotificationPermission: () -> Unit,
    onOpenExactAlarmSettings: () -> Unit,
) {
    var enabled by remember(schedule.enabled) { mutableStateOf(schedule.enabled) }
    var hour by remember(schedule.hour) { mutableStateOf(schedule.hour.toString()) }
    var minute by remember(schedule.minute) { mutableStateOf(schedule.minute.toString().padStart(2, '0')) }
    Card {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("定时运行", fontWeight = FontWeight.Bold)
                Switch(checked = enabled, onCheckedChange = { enabled = it })
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextFieldRaw("小时", hour, { hour = it.filter(Char::isDigit).take(2) }, Modifier.weight(1f))
                TextFieldRaw("分钟", minute, { minute = it.filter(Char::isDigit).take(2) }, Modifier.weight(1f))
            }
            Text("下一次：${ScreeningAlarmScheduler.formatEpochMillis(schedule.nextRunAt).ifBlank { "未计划" }}")
            if (schedule.lastRunText.isNotBlank()) Text("上次：${schedule.lastRunText}")
            Text(if (canExact) "精确闹钟权限：已可用" else "精确闹钟权限：未授权，将尽量靠近运行")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(
                    onClick = {
                        onSave(enabled, hour.toIntOrNull() ?: 14, minute.toIntOrNull() ?: 30)
                    }
                ) { Text("保存定时") }
                OutlinedButton(onClick = onOpenExactAlarmSettings) { Text("精确闹钟") }
                OutlinedButton(onClick = onRequestNotificationPermission) { Text("通知权限") }
            }
        }
    }
}

@Composable
private fun HeaderBar(
    title: String,
    subtitle: String,
    left: (@Composable () -> Unit)? = null,
    right: (@Composable () -> Unit)? = null,
) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(subtitle, style = MaterialTheme.typography.bodySmall)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            left?.invoke()
            right?.invoke()
        }
    }
}

@Composable
private fun TextFieldRaw(label: String, value: String, onChange: (String) -> Unit, modifier: Modifier = Modifier) {
    OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true, modifier = modifier)
}

@Composable
private fun NumberField(label: String, value: Double, onValue: (Double) -> Unit, modifier: Modifier = Modifier) {
    var text by remember(value) { mutableStateOf(formatNumber(value)) }
    TextFieldRaw(label, text, { next ->
        text = next
        next.toDoubleOrNull()?.let(onValue)
    }, modifier)
}

@Composable
private fun IntField(label: String, value: Int, onValue: (Int) -> Unit, modifier: Modifier = Modifier) {
    var text by remember(value) { mutableStateOf(value.toString()) }
    TextFieldRaw(label, text, { next ->
        text = next
        next.toIntOrNull()?.let(onValue)
    }, modifier)
}

@Composable
private fun LongField(label: String, value: Long, onValue: (Long) -> Unit, modifier: Modifier = Modifier) {
    var text by remember(value) { mutableStateOf(value.toString()) }
    TextFieldRaw(label, text, { next ->
        text = next
        next.toLongOrNull()?.let(onValue)
    }, modifier)
}

@Composable
private fun ProgressCard(text: String, running: Boolean) {
    Card(colors = CardDefaults.cardColors(containerColor = if (running) Color(0xFFEAF3FF) else Color(0xFFF3F5F7))) {
        Column(Modifier.fillMaxWidth().padding(12.dp)) {
            Text(if (running) "运行中" else "状态", fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            Text(text)
        }
    }
}

@Composable
private fun StockCard(stock: ScreenedStock) {
    Card(colors = CardDefaults.cardColors(containerColor = if (stock.selected) Color(0xFFEAF7EF) else Color(0xFFFFF0F0))) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${stock.code} ${stock.name}", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                AssistChip(onClick = {}, label = { Text(if (stock.selected) "入选" else "未入选") })
            }
            MetricText(stock.price, stock.changePct, stock.volumeRatio, stock.turnoverPct, stock.floatMarketCapYi)
            Text("P${stock.priority} ${stock.priorityLabel}  ${stock.positionLabel}  K线：${stock.klineSource}")
            if (!stock.selected) Text("原因：${stock.rejectReason.ifBlank { "未说明" }}", color = Color(0xFF8A2D2D))
        }
    }
}

@Composable
private fun StockEntityCard(stock: ScreenedStockEntity) {
    Card(colors = CardDefaults.cardColors(containerColor = if (stock.selected) Color(0xFFEAF7EF) else Color(0xFFFFF0F0))) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${stock.code} ${stock.name}", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                AssistChip(onClick = {}, label = { Text(if (stock.selected) "入选" else "未入选") })
            }
            MetricText(stock.price, stock.changePct, stock.volumeRatio, stock.turnoverPct, stock.floatMarketCapYi)
            Text("P${stock.priority} ${stock.priorityLabel}  ${stock.positionLabel}  K线：${stock.klineSource}")
            if (!stock.selected) Text("原因：${stock.rejectReason.ifBlank { "未说明" }}", color = Color(0xFF8A2D2D))
        }
    }
}

@Composable
private fun StockQueryCard(result: StockQueryResult) {
    StockCard(result.stock)
}

@Composable
private fun StockQueryEntityCard(
    query: StockQueryEntity,
    onOpen: () -> Unit,
    onDelete: () -> Unit,
    showActions: Boolean = true,
) {
    val time = remember(query.queriedAt) { formatTime(query.queriedAt) }
    Card(colors = CardDefaults.cardColors(containerColor = if (query.selected) Color(0xFFEAF7EF) else Color(0xFFFFF0F0))) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${query.code} ${query.name}", fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                AssistChip(onClick = {}, label = { Text(if (query.selected) "满足" else "不满足") })
            }
            Text(time, style = MaterialTheme.typography.bodySmall)
            MetricText(query.price, query.changePct, query.volumeRatio, query.turnoverPct, query.floatMarketCapYi)
            Text("P${query.priority} ${query.priorityLabel}  ${query.positionLabel}  K线：${query.klineSource}")
            if (!query.selected) Text("原因：${query.rejectReason.ifBlank { "未说明" }}", color = Color(0xFF8A2D2D))
            if (showActions) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onOpen) { Text("打开") }
                    OutlinedButton(onClick = onDelete) { Text("删除") }
                }
            }
        }
    }
}

@Composable
private fun MetricText(price: Double, changePct: Double, volumeRatio: Double, turnoverPct: Double, floatMarketCapYi: Double) {
    Text("价格 ${formatNumber(price)}  涨幅 ${formatNumber(changePct)}%  量比 ${formatNumber(volumeRatio)}")
    Text("换手 ${formatNumber(turnoverPct)}%  流通市值 ${formatNumber(floatMarketCapYi)}亿")
}

@Composable
private fun RunCard(run: ScreeningRunEntity, onOpen: () -> Unit, onDelete: () -> Unit) {
    val time = remember(run.createdAt) { formatTime(run.createdAt) }
    Card {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(time, fontWeight = FontWeight.Bold)
            Text("入选 ${run.selectedCount} / 保存 ${run.screenedCount}")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onOpen) { Text("打开") }
                OutlinedButton(onClick = onDelete) { Text("删除") }
            }
        }
    }
}

private fun formatTime(millis: Long): String =
    SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.CHINA).format(Date(millis))

private fun formatNumber(value: Double): String =
    if (value % 1.0 == 0.0) value.toInt().toString() else String.format(Locale.US, "%.2f", value)
