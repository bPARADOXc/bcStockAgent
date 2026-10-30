# iOS 本地版 A股短线筛选

这是独立的条件规则筛选 App，与本仓库的 TradingAgents 多智能体研究程序分别运行。App 在手机本地按固定行情条件筛选股票，不调用六类分析师或多空辩论，不需要 Python 服务或大模型 API Key。

这是一个独立的 SwiftUI iOS 工程，只放在 `ios_app/` 下，不依赖也不修改 Android App 或 Python 筛选代码。

## 功能

- 筛选页：设置常用参数、手动运行全市场主板筛选、查看当前结果、分享 HTML 报告。
- 单股页：输入 6 位代码或带 `sh` / `sz` 前缀代码，查询实时指标、K线、放量、MA、优先级和未满足原因。
- 历史页：保存每次筛选结果，支持详情页按全部/入选/未入选过滤。
- 设置页：暴露全部筛选参数，支持换手上限不限，支持定时运行设置。
- 本地保存：使用 App 私有目录 JSON 文件保存参数、筛选历史、单股查询历史，不生成 CSV。
- 通知：定时提醒、筛选完成/跳过/失败通知。

## iOS 定时运行说明

这是纯 iOS 本地版，因此无法像 Android 前台服务那样保证每天 14:30 准时联网跑完整筛选。

当前实现使用：

- `BGTaskScheduler`：系统允许时尽力后台刷新。
- `UNUserNotificationCenter`：到点本地提醒。

实际表现取决于 iOS 后台策略、电量、网络、用户是否频繁打开 App。全市场筛选耗时较长，后台任务可能被系统提前终止；这种情况下请打开 App 手动运行。

## 构建方式

1. 在 Mac 上安装 Xcode 15 或更新版本。
2. 打开：

   ```text
   ios_app/StockScreener.xcodeproj
   ```

3. 在 Xcode 中选择 `StockScreener` target。
4. 修改 Signing & Capabilities：
   - Team：选择你的 Apple Developer 账号
   - Bundle Identifier：如有冲突，改成你自己的，例如 `com.yourname.stockscreener`
5. 选择 iPhone 模拟器或真机，点击 Run。

命令行构建示例：

```bash
cd ios_app
xcodebuild -project StockScreener.xcodeproj -scheme StockScreener -configuration Debug -destination 'generic/platform=iOS Simulator' build
```

## 首次运行

- 进入“设置”页，确认筛选参数。
- 点击“通知权限”授权通知。
- 如需定时，开启“定时运行”并保存。
- 手动筛选建议先放宽参数和返回数量，确认网络数据源可用后再收紧。

## 数据源

- 实时行情：腾讯行情接口。
- K线：优先新浪，失败后尝试东方财富。
- 交易日判断：东方财富上证指数日 K 最新日期。

东方财富请求通过串行限流，默认最小间隔来自 `eastmoneyMinIntervalMs` 参数。

## 当前边界

- 第一版不维护批量自选列表，只支持单股查询和单股查询历史。
- App 图标当前是占位资源，真机分发前请在 `Assets.xcassets/AppIcon.appiconset` 补完整图标。
- 未接入 APNs，因此 App 被系统长时间挂起时无法保证筛选完成通知。
