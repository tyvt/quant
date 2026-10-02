# 阶段 A Parquet PIT Reader 实施与验收规格（2026-09-29）

状态：**v1.2.0 阶段 A 真实读取已实现并通过合成与真实快照验收。**

本文是 `RULE_SPEC v1.2.0` 阶段 A Reader 的实施规格。它授权点时读取与验收，
但不授权真实研究筛选、选股或组合回测。

## 已核实的本地数据面

| 域 | 拟使用快照 | 行数 | schema / normalization | 已知质量状态 |
|---|---|---:|---|---|
| `security_master` | `snapshot-16de9d9c4679347d` | 6,524 | `1 / cn_equity_v1` | 与全量行情同一快照 |
| `market_daily` | `snapshot-16de9d9c4679347d` | 12,004,094 | `1 / market_raw_v1` | 3,441/3,455，覆盖率 99.59%，有 0 OHLC 警告 |
| `adjustment_factors` | `snapshot-16de9d9c4679347d` | 43,651 | `1 / adjustment_factor_v1` | 累积因子，须保留来源语义 |
| `calendar` | `snapshot-2abff764afcbfb52` | 7,947 | `1 / cn_calendar_v1` | complete；含截止日后 10 天可用日解析缓冲 |
| `chinabond_10y` | `snapshot-2abff764afcbfb52` | 5,147 | `1 / chinabond_10y_v1` | 2005 年源缺口警告 |

旧快照 `snapshot-a3066c7c6ab6dcd4` 的 `chinabond_10y` 已被域撤销，原因是
试点解析器未限定政府债曲线；Reader 必须拒绝它，不能自动跟随 replacement。

上述两个拟用快照的 `universe_hash` 分别为 `f1b1a511ce16eef3` 和
`4777dacd564bdf28`。后者是日历/宏观同步任务的空证券选择结果，不应覆盖
证券与行情快照的研究证券池身份。因此不能简单要求所有辅助域的
`universe_hash` 相等。

### 累积复权因子实证

以 `snapshot-16de9d9c4679347d` 的浦发银行为样本，将除权前一交易日收盘价按
`previous_cumulative_factor / new_cumulative_factor` 调整：

| 除权日 | 前收盘 | 前/新累积因子 | 调整后前收盘 | 除权日收盘 | 差额 |
|---|---:|---:|---:|---:|---:|
| 2022-07-21 | 7.79 | 10.818 / 11.424 | 7.3768 | 7.33 | 0.0468 |
| 2023-07-21 | 7.42 | 11.424 / 11.938 | 7.1005 | 7.12 | -0.0195 |
| 2024-07-18 | 9.04 | 11.938 / 12.380 | 8.7172 | 8.77 | -0.0528 |
| 2025-07-16 | 13.93 | 12.380 / 12.751 | 13.5247 | 13.48 | 0.0447 |
| 2026-07-16 | 9.31 | 12.751 / 13.350 | 8.8923 | 8.85 | 0.0423 |

五次事件均在正常单日波动范围内连续，支持把 StockDB 字段解释为累积因子，
而不是单次价格乘数。

### 利率可见性实证

对 5,147 条中债记录和 7,947 条交易日历逐日合并，并严格限制在快照配置区间
`[2005-01-01, 2026-09-24]`：利率开始后的 5,003 个可评价交易日，最新记录
均有 `available_at=as_of`；长假造成的观测日自然日龄最高为 11 天，但没有经过
额外交易日。2005 年源缺口没有合格观测，保持 UNKNOWN。日历的截止日后 10 天
是同步器为计算最后几条利率的下一交易日 `available_at` 而保存的前向缓冲，
不扩大研究数据覆盖截止日。

## 已完成的前置能力

`turtle_quant.storage.verify_published_domain` 已提供 fail-closed 的只读验证：

- 只接受显式、格式合法的 `snapshot_id` 和域名；
- 核对 complete meta、完整内容哈希、短 snapshot ID 和必需域状态；
- 只返回 meta 白名单文件，并逐文件核对 SHA-256 与域逻辑哈希；
- 强制读取 `catalog/domain-revocations.json`，目录缺失或损坏即失败；
- 撤销域报错，不自动发现“最新”或切换 replacement；
- 返回行数、质量标记、内容哈希和证券池哈希，供运行清单记录。

## 推荐构造契约

Reader 必须由调用方显式传入“域 → snapshot ID”映射，而不是扫描目录选择
最新快照。建议构造对象至少包含：

```text
storage_root
security_master_snapshot_id
market_daily_snapshot_id
adjustment_factors_snapshot_id
calendar_snapshot_id
rate_snapshot_id
```

构造阶段一次性验证所有域并冻结选择；同一 Reader 生命周期内不得重新发现或
切换快照。`RunManifest.snapshot_ids` 记录全部去重后的 ID；研究
`universe_hash` 取证券主表/行情 cohort 的值。证券主表、行情和复权因子必须
来自同一快照，或由测试证明证券池身份完全一致；日历和宏观利率可以来自辅助
快照，其证券池哈希不参与覆盖主研究证券池。

研究 `as_of` 查询必须位于对应快照 `config.start_date..config.end_date`；越界
属于调用错误，不能返回部分数据或最近旧值。日历域额外保存的
`(end_date, end_date + 10 天]` 是独立的成交日推导缓冲：采集层可用它解析最后
观测的 `available_at`，Reader 只可用它回答 `next_trading_day(end_date)`，安排
`end_date` 收盘信号后的首个成交日。该成交日期不成为新的研究 `as_of`，不得
用于信号、价格、因子、利率或证券池查询。

## 推荐输出边界

现有 `core/protocols.py` 的行情、因子和利率返回 `object`，且没有交易日历协议。
生产 Reader 放行时应同时冻结只读值对象，至少包括：

- `RawPriceBar`：规范证券代码、交易日、OHLC、成交量、成交额、停牌三态，以及
  可空的 `evidence_ref`/`source_row_hash`；缺失证据保留为 None 并生成
  `EVIDENCE_MISSING`，不得伪造；
- `PriceBarSeries`：不可变 `bars`、`coverage_issues`、`quality_flags` 元组，以及
  由问题元组是否为空派生、不可单独赋值的 `coverage_complete`；
- `CoverageIssue`：问题枚举、证券、日期范围及可选证据；至少区分证券未覆盖、
  缺 bar、停牌状态未知和证据缺失；
- `AdjustmentFactorObservation`：证券、除权日、累积因子、因子来源、
  `available_at`、证据；
- `RateObservation`：观测日、百分数值、曲线、期限、`available_at`、证据；
- `TradingCalendarReader`：按交易所查询交易日与前/后交易日，不能由行情缺行
  反推日历。

所有数值在边界转成有限 `Decimal`；日期严格解析为 `date`；缺失值保留
`None`/三态，不得填零。规范证券代码统一为 `sh.600000` 形式。市场数据必须
保持 `adjust_type=RAW`，研究复权和交易模拟不能混用同一价格列。

## 已冻结、可直接测试的读取行为

- 历史证券池使用主板有效区间、上市日和退市日；当前核心 fixture 已冻结区间
  端点包含语义。
- 行情查询必须满足 `start <= trade_date <= min(end, as_of)`，按日期稳定排序，
  不返回其他证券或复权价格；快照区间内缺 bar 或列入
  `missing_security_ids` 时显式返回对应 `CoverageIssue`，不能用空序列冒充
  “没有行情”。证券未覆盖映射 `NOT_SUPPORTED` 而非 `NOT_APPLICABLE`；其他
  问题只污染依赖相应日期、停牌状态或证据链的规则。
- `coverage_complete` 仅在 `coverage_issues` 为空时为 TRUE。证据缺失不抹掉已有
  数值，但该数值只能进入不要求可追溯性的计算或诊断，不能形成可发布的标准
  通过结论；依赖证据链的规则为 NEEDS_REVIEW。
- 复权因子至少满足 `available_at <= as_of`，未知可用日的因子不得进入研究。
- 利率只允许曲线 `ycqx`、期限 `10Y`，并按 `available_at <= as_of` 过滤；
  没有合格观测时返回 UNKNOWN，而不是 0。
- 任一域 schema/normalization 版本不在显式白名单时，整个读取失败；不得静默
  尝试兼容。
- 可发布 warning 必须进入 `RunManifest.data_quality_flags`；撤销不是 warning，
  而是硬失败。

## v1.2.0 已批准的 Reader 语义

以下为可直接批准的推荐值：

1. `as_of: date` 表示当日收盘后可见；可返回当日原始收盘价，但后续回测最早
   只能在下一可交易时点成交，禁止用同一收盘价成交。
2. 中债 10 年收益率选择最近一个 `available_at <= as_of` 的观测；开区间
   `(available_at, as_of)` 内不得有交易日，即
   `max_rate_staleness_trading_days=0`。周五到下周一计 0，周四到下周一因包含
   周五计 1；长假无交易日则不增加陈旧度。超过即 UNKNOWN；实现不得计入两个
   端点，也不得使用日历日差。
3. 唯一稳定 series 标识为 `CN_GOVT_10Y_YIELD_PCT`，返回完整
   `RateObservation`；未知 series 直接报参数错误，不设别名或隐式 fallback。
4. 先固定 `available_at <= as_of` 的 StockDB 累积因子观察。`F(d)` 取其中
   `ex_date <= d`、`ex_date` 最大且同日修订 `available_at` 最大的**累积因子
   水平**，没有则为 1；`F(as_of)` 同理。同一证券、除权日和可用日出现冲突值
   时硬失败。
   两者使用同一个 as-of 可见集合，不读取未来观察，也不把历次累积值再次相乘。
   研究前复权价为
   `AdjustedPrice(d, as_of) = RawPrice(d) × F(d) / F(as_of)`。FX-001 对应
   `F(T0)=1, F(T1)=2`，区间乘数为 `0.5`。不得把累积因子直接当单次乘数；
   当前 `adjusted_close_to_as_of` 及其黄金测试已实现同一公式，生产 Reader
   必须复用或等价调用，不能另写不同口径。
5. `paused=null` 保持 UNKNOWN，不能当作 FALSE；依赖明确停牌状态的规则须
   `NEEDS_REVIEW` 或阻断，直至来源补齐。
6. v1.2.0 同步新增 `TradingCalendarReader`、`RawPriceBar`、`PriceBarSeries`、
   `CoverageIssue`、`AdjustmentFactorObservation` 和 `RateObservation`，替换
   三个无类型 `object` 返回边界。

批准记录与精确条文见 `rule-proposals/v1.2.0-exact-amendment.md`。

## 验收矩阵

实现必须先写失败测试，再覆盖：

1. complete/meta/content ID/文件 SHA/逻辑哈希/撤销目录的全部拒绝路径；
2. 显式多快照选择、禁止 latest 发现、禁止自动 replacement；
3. schema 与 normalization 版本白名单；
4. 证券上市、退市、板块迁移的左右端点；
5. 行情证券、日期、RAW 口径和 `as_of` 截断；
6. 因子 `available_at` 截断、同版本复权及 FX-001；
7. 利率观测日与可用日错位、周末/节假日、陈旧阈值和无数据 UNKNOWN；
8. 被撤销旧中债域失败、替代快照显式选择成功；
9. 12,004,094 行行情使用 Parquet 过滤下推，不能全表转 Python list；
10. 所有 snapshot ID、质量 warning、规则版本和证券池哈希进入 `RunManifest`。

实现已按“强类型记录与协议 → 合成快照 RED 测试 → Foundation Reader →
真实快照只读验收 → RunManifest 集成”的顺序完成。全量回归为 **162 项测试全部
通过**，源码分支覆盖率 **81%**，Foundation Reader 自身分支覆盖率 **80%**；
详细证据见 `testing/stage-a-parquet-foundation.tdd.md`。财报、分红和回购继续由
三个专用模块独立过门；`parquet_finance.py` 聚合门面必须等三者全部 ready。
