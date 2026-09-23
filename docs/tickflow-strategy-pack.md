# TickFlow 增量策略包

本次导入 41 个策略，按策略 ID 或名称去重，跳过 19 个重复策略。目标项目原有内置策略保留。

## 加载与插拔

- 策略文件位于运行数据目录的 `strategies/custom/`，复用现有策略加载器，无需修改注册表或前端页面。默认运行数据目录为项目根 `data/`；设置 `DATA_DIR` 时请将文件放到对应目录。
- 重新启动后自动加载。需要暂时禁用某个策略时，将文件名加上 `_` 前缀；恢复原名并重新启动即可启用。
- 移除策略文件并重新启动即可卸载；不会删除历史回测或参数配置。
- 12 个连板回踩策略共同依赖 `_board_pullback.py`。仅禁用某个连板回踩策略时保留此依赖文件。
- 自定义策略属于用户数据，`data/` 不进入 Git。迁移或发布时需单独复制策略包。

## 必要公共兼容能力

在现有统一执行路径增量支持策略 `TAKE_PROFIT` 默认值、成交时点元数据、收盘止损、条件止损及可选执行计划（等量加仓与计划退出）。保留目标版本的数据源、缓存 generation、因子与分钟入场价覆盖能力。

加仓预留仓位由策略是否声明执行计划决定，不根据未来加仓信号决定初始买入数量。分组元数据按原定义保留，目标界面继续使用现有自定义策略列表。

## 新增策略

| 策略名称 | 稳定 ID | 文件 |
| --- | --- | --- |
| 空中加油 | `air_refueling` | `air_refueling.py` |
| 快速深踩修复 | `board_pullback_deep` | `board_pullback_deep.py` |
| 首板支撑反弹 | `board_pullback_first` | `board_pullback_first.py` |
| KDJ低位修复 | `board_pullback_kdj` | `board_pullback_kdj.py` |
| 延迟筑底突破 | `board_pullback_late` | `board_pullback_late.py` |
| MA10回踩企稳 | `board_pullback_ma10` | `board_pullback_ma10.py` |
| MACD零轴上二次增强 | `board_pullback_macd` | `board_pullback_macd.py` |
| 二板半分位修复 | `board_pullback_midpoint` | `board_pullback_midpoint.py` |
| 强前势MACD动量回踩 | `board_pullback_momentum` | `board_pullback_momentum.py` |
| 破5返5反包阳（连板回踩） | `board_pullback_reclaim5` | `board_pullback_reclaim5.py` |
| 快速浅踩反包 | `board_pullback_shallow` | `board_pullback_shallow.py` |
| 趋势延续突破 | `board_pullback_trend` | `board_pullback_trend.py` |
| 缩量回踩放量启动 | `board_pullback_volume` | `board_pullback_volume.py` |
| 凹字多方炮 | `concave_multi_cannon` | `concave_multi_cannon.py` |
| 二龙戏水 | `double_dragon_playing_water` | `double_dragon_playing_water.py` |
| 双响炮 | `double_limit_up_cannon` | `double_limit_up_cannon.py` |
| 二板涨停回调低吸 | `double_limit_up_golden_pullback` | `double_limit_up_golden_pullback.py` |
| 破5返5反包阳 | `double_limit_up_ma5_reclaim` | `double_limit_up_ma5_reclaim.py` |
| 双线流高倍战法 | `double_line_high_multiple` | `double_line_high_multiple.py` |
| 倍量阳·缩量破线 | `double_volume_bullish_breakout` | `double_volume_bullish_breakout.py` |
| 跳空回马枪 | `gap_up_recoil` | `gap_up_recoil.py` |
| 龙头首阴--5弯10 | `leader_first_bearish_ma5_ma10` | `leader_first_bearish_ma5_ma10.py` |
| 倍量过左峰缩量确认 | `left_peak_volume_retest` | `left_peak_volume_retest.py` |
| 涨停突破回踩 | `limit_up_breakout_retest` | `limit_up_breakout_retest.py` |
| 涨停多头筹码 | `limit_up_bull_chip` | `limit_up_bull_chip.py` |
| 涨停倍量阴 | `limit_up_double_volume_bearish` | `limit_up_double_volume_bearish.py` |
| 10日涨停回踩缩量反转 | `limit_up_ma10_volume_reversal` | `limit_up_ma10_volume_reversal.py` |
| 涨停倍量阴整理启动 | `limit_up_bearish_volume_ma_startup` | `limit_up_ma_consolidation_breakout.py` |
| 涨停穿线断板整理突破 | `limit_up_ma_consolidation_breakout` | `limit_up_ma_consolidation_breakout_extracted.py` |
| 喜鹊闹梅 | `magpies_on_plum` | `magpies_on_plum.py` |
| 空中飞饼 | `night_grass_close_enhanced` | `night_grass_close_enhanced.py` |
| 一夜持股法(尾盘短线擒龙) | `overnight_dragon` | `overnight_dragon.py` |
| 平台突破 | `platform_breakout` | `platform_breakout.py` |
| 2560战法 | `strategy_2560` | `strategy_2560.py` |
| 520战法 | `strategy_520` | `strategy_520.py` |
| 三军点炮 | `three_armies_cannon` | `three_armies_cannon.py` |
| 三阳开泰 | `three_yang_breakout` | `three_yang_breakout.py` |
| 三线逐浪 | `triple_volume_bullish_first_breakout` | `triple_volume_bullish_first_breakout.py` |
| 三倍量均线向上发散 | `triple_volume_ma_spread` | `triple_volume_ma_spread.py` |
| 三倍量回调缩量双阳 | `triple_volume_pullback_double_bull` | `triple_volume_pullback_double_bull.py` |
| 尾盘选股 | `custom_msnabhqp` | `custom_msnabhqp.py` |

## 跳过的重复策略

- 布林突破（`boll_breakout`）
- 断板反包（`broken_board_recovery`）
- 均线多头（`bullish_alignment`）
- 连板股（`consecutive_limit_ups`）
- 高换手拉升（`high_turnover_surge`）
- 连板接力（`limit_up_momentum`）
- 低波动龙头（`low_volatility_leader`）
- MA 金叉（`ma_golden_cross`）
- MACD 金叉放量（`macd_golden`）
- 新低反转（`n_day_low_reversal`）
- 逼近涨停（`near_limit_up`）
- 超跌反弹（`oversold_bounce`）
- 超跌反转（`oversold_reversal`）
- 均线回踩反弹（`pullback_ma20_bounce`）
- 缩量回踩（`pullback_to_support`）
- 强势高开（`strong_open`）
- 趋势突破（`trend_breakout`）
- 量价齐升（`volume_price_surge`）
- 空中加油（`custom_air_refueling`）

## 验证结果

新增策略定向测试、全部 `tests/backtest/`、策略注册和可插拔测试合计 561 项通过。`git diff --check` 通过。新增策略与测试 Ruff 定向检查通过；回测引擎保留 4 条既有 E741 告警。未修改前端，未提交或推送代码。
