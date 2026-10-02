# v1.3.0 策略纯逻辑黄金验收（2026-09-30）

状态：纯逻辑与合成 fixture 可执行；真实研究、订单与可发布绩效仍未获授权。
规则依据为已批准的 `RULE_SPEC v1.3.0`。本页记录实现验收，不变更策略阈值。

## 日历与点时契约

- `UniverseInput` 必须带 `as_of` 和截至该日的 60 个预期交易日；缺整日为
  `liquidity_window_incomplete`，未来行不能改变旧判定。
- `analyze_market_position` 必须带截至 `as_of` 的预期交易日序列；仅使用尾部
  756 日，缺整日为 `MISSING_BAR`，有证据的停牌日不前填价格。
- `run_order_book` 要求 session 与预期交易日逐日一致；不能通过省略 session
  缩短五日尝试计时或掩盖缺失净值日。
- `calculate_performance` 对齐预期交易日；缺净值日为 `NAV_INCOMPLETE`，月度
  胜率仅使用日历覆盖完整自然月的月末。未来基准、利率和流动性行不参与早期计算。
- 这里的“预期交易日”须来自已验收的日历快照，不能由实得行情行反推；
  `calendar_complete_through` 是日历覆盖声明，不是推测的末次行情日期。

## 成交、公司行为与内容身份

- 每日先处理拆并股，随后先卖后买；实际支付股息在成交后、收盘记账前入现金。
  股息必须附登记日、已核实权益数量及其证据，不能按支付日当前持仓数量推算。
  缺权益证据为 `DIVIDEND_ENTITLEMENT_UNKNOWN`，不产生现金。
- 已知拆并股与尚未完成的旧订单相遇时，旧订单没有批准的重算规则；当前
  保守取消并标记 `CORPORATE_ACTION_ORDER_UNKNOWN`，该运行不可发布。
  未支持公司行为和未知退市结算保留权利，不虚构现金流，并阻断完整性。
- 订单内容身份由 canonical 订单结果流与逐笔成交流共同计算；包括信号/执行
  日期、数量、状态、问题码、成交价、滑点、各项费用及现金变化。
  持仓和净值各自按逻辑行计算 SHA-256，不依赖 Parquet 物理字节。
  相同输入重复执行的三个哈希及 `StrategyRunManifest.canonical_json()` 相同。

## 验收测试

| 边界 | 对应测试 |
|---|---|
| 未来属性及修订不可见 | `test_strategy_pit_and_config_v13.py` |
| 60 日/756 日缺整行及未来流动性行 | `test_strategy_selection_v13.py`、`test_market_position_v13.py` |
| 20 日参与率、涨跌停、T+1、费率、五日取消 | `test_backtest_execution_v13.py`、`test_backtest_engine_v13.py` |
| 登记日股息权益、拆并股、未知退出 | `test_backtest_portfolio_v13.py`、`test_backtest_engine_v13.py` |
| 缺净值日、完整自然月、基准和利率 | `test_backtest_metrics_v13.py` |
| 重复运行内容哈希和清单 | `test_backtest_reproducibility_v13.py`、`test_backtest_engine_v13.py` |

运行：`python -m unittest discover -s tests -q`，本次为 264 项全部通过。

## 尚未完成的生产验收

真实财报修订、分红全窗口与权益、回购逐日执行、行业、历史股本、证券状态、
交易能力、公司行为、历史费率及跨域快照清单仍须逐域 ready。官方 H00985
全历史快照与 Reader 已按 v1.3.1 在已验收覆盖内转 ready；不放行真实回测。
这些缺口不能由纯逻辑测试代替。真实数据运行入口保持关闭；只有合成 fixture
可以构造上述值对象。拆并股遇未完成订单的正式重算/取消政策亦需规则批准后才能
放开该路径的可发布结果。
