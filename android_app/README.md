# A股短线筛选 Android App

这是独立的条件规则筛选 App，与本仓库的 TradingAgents 多智能体研究程序分别运行。App 在手机本地按固定行情条件筛选股票，不调用六类分析师或多空辩论，不需要 Python 服务或大模型 API Key。

这是项目内独立的 Android 客户端工程，面向 Android 12+ 内部 APK。

## 功能

- 手机本地运行 A 股主板短线筛选。
- 实时行情通过腾讯 quote 接口获取。
- K 线按 `百度 -> 新浪 -> 东方财富` 顺序读取。
- 东方财富请求串行限流，默认最小间隔 1.8 秒。
- 每次筛选结果自动保存到 App 内历史。
- 保存全部实时行情通过股票，包含入选状态和未选中原因。
- 支持分享移动端友好的 HTML 报告。
- 不生成 CSV 文件。

## 构建

推荐用 Android Studio 打开 `android_app/` 目录，然后执行：

```bash
./gradlew :app:assembleDebug
```

或在 Android Studio 中选择 `Build > Build APK(s)`。

## 兼容

- `minSdk = 31`，Android 12+
- `targetSdk = 35`，Android 15
- Kotlin/Java 原生实现，不打 native `.so`，无需按天玑 9400 单独分包。

## 报告保存

长期保存使用 Room 数据库中的 App 内历史；HTML 文件仅在分享时写入 App cache，并通过系统分享面板发送给浏览器、微信或文件管理器。
