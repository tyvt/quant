# 规则规范

**规则版本：v1.3.2**

本文件是当前冻结规则版本的唯一实现真相源。实现、配置和测试必须以本文件为准；外部 reference 仅用于溯源。外部 reference 的后续变化不能静默改变代码或历史结果。

## 变更管理

### 版本规则

使用 `vMAJOR.MINOR.PATCH`：

- `MAJOR`：改变公式、时间语义、决策语义或历史结果可比性；
- `MINOR`：新增完整、可验证且不改变既有规则输出的模块或 Profile；
- `PATCH`：不改变规则结果的文字澄清、fixture 补充或测试修正。

### 变更记录

每次修改必须在本节追加记录，至少包含：

- 版本、日期、提出者、批准者；
- 变更内容、精确差异和理由；
- 受影响模块；
- 需要同步的配置、代码、fixture 和测试；
- 状态与迁移/兼容性结论。

### 变更流程

1. 提出变更并给出完整差异与理由；
2. 项目负责人批准规则语义；
3. 更新本文件并升级 `rules_version`；
4. 同步实现、配置、fixture 与测试；
5. 记录历史运行是否可比以及迁移结论。

禁止静默改写、绕过变更记录直接改代码或配置、以及用新规则重新解释旧运行结果。

### 授权与兼容性

- v1.0.0/v1.1.0 的合成 fixture 结果保持可比；
- v1.1.0 的授权范围不包含真实数据研究。任何基于 v1.1.0 产生的真实数据研究、
  选股或回测产物均属于未经授权的审计产物，v1.2.0 不予承认，不得作为迁移、
  业绩引用或策略决策依据；若需保留，必须在后续完整链路 ready 后按新 manifest
  重新运行；
- 不得用 v1.2.0 或 v1.3.0 实现重新解释旧 manifest；
- v1.2.0 只授权本规范列明的阶段 A 真实数据读取；
- v1.3.0 授权 `premise/`、`market/position.py`、`strategy/` 与 `backtest/` 的纯逻辑、
  合成 fixture 和确定性输出实现。财报、分红、回购、行业、历史股本、证券状态、
  交易能力、公司行为、基准和历史成本域全部通过生产验收前，不得把这些模块接成
  真实选股或可发布回测，也不得把合成订单称为真实交易建议。
- v1.3.1 仅将已验收显式快照覆盖范围内的 H00985 基准 Reader 转为 `ready`。
  其他九个生产域及真实策略编排仍为 `not_ready`；基准可读不构成真实选股、
  可发布回测或交易授权。已发布快照不迁移、不改写。
- 两个已发布 H00985 快照均无快照级 `rule_version`：全历史快照的
  `domains.benchmark.details.exclusion_evidence[*].rule_version=v1.3.0`，干净
  区间快照无排除证据或例外 policy。Reader 不按抓取/发布时间推断版本；
  对含例外证据的快照按经内容身份核验的证据版本及批准版本表重建，
  只接受 `v1.3.0` 和 `v1.3.1`，未知版本硬失败。无例外的旧快照继续可读。
- 2026-09-30 的 H00985 抓取时点身份裁决与两日例外/v1 兼容编码裁决由
  v1.3.1 基准正文吸收；原裁决文档保留为证据。历史运行和快照不重释。

## 术语与单位

所有数值用 `Decimal` 处理。领域计算使用固定精度 `28`、`ROUND_HALF_EVEN` 的本地 Decimal 上下文，避免调用方修改全局上下文影响结果。百分数值采用 `5` 表示 `5%`，而不是 `0.05`。

实现应使用以下规范单位类型：

- `NonNegativePct`：非负百分数；
- `SignedPct`：可为负的百分数；
- `UnitRatio`：`[0, 1]` 区间比例；
- `SignedRatio`：可为负的无量纲小数比例；
- `BasisPoints`：基点；
- `NonNegativeDays`：非负整数天数；
- `Money`：带币种的金额，可否为负由字段规定。

外部数据字段为空表示 `UNKNOWN`，不允许类型层填充 0 或任何隐式默认值。方法参数只能由版本化配置明确给定。

## 变量字典

### 绝对估值

- `P`：估值日可交易收盘价；单位为价格货币/股；必须正；时间为 `as_of` 当日；适用于通用 FCF Profile；证据为行情快照。
- `S`：`as_of` 当日收盘后可见、与普通股经济权益一致的总股数；单位为股；必须正；
  时间与 `P` 同日；证据为独立历史股本快照。当前证券主表值不得回填历史。
- `MV`：市值，通常为 `P × S`；单位为 `Money`；必须正；时间与 `P` 同日；证据为行情与股本快照。
- `C`：未受限现金；单位为 `Money`；允许为零，不允许用缺失代替零；期间为财务
  报告期末；证据为资产负债表和受限资金附注。货币资金已知且受限金额明确为零时
  等于货币资金；受限金额已知为正时相减；任一必要值未知时为 `UNKNOWN`。
- `A`：一年内可变现且不重叠的金融资产；单位为 `Money`；允许为零；期间为财务报告期末；证据为资产负债表及附注。
- `B_debt`：有息债务；单位为 `Money`；允许为零；期间为财务报告期末；证据为资产负债表及附注。
- `E`：归母权益；单位为 `Money`；必须正；期间为财务报告期末；证据为资产负债表。
  `E_latest` 是截至 `as_of` 最近可见报表期末值；`Y0` 是截至 `as_of` 最近已有完整、
  可追溯年报可见的完整财年末。
- `N`：少数股东权益；单位为 `Money`；允许为零；缺失仅在同期总权益可验证等于 `E` 时视为零，否则 `UNKNOWN`。
- `alpha`：归属代理，`E / (E + max(N, 0))`；单位为 `UnitRatio`；必须在 `(0, 1]`。
- `OCF`：经营现金流；单位为 `Money`；可为负；期间为完整年度或可比 TTM；证据为现金流量表。
- `Capex`：现金资本开支；单位为 `Money`；以正支出表达；期间与 `OCF` 一致；证据为现金流量表或可核对附注。
- `Lease_cash_not_already_deducted`：未重复扣减的现金租赁支出；单位为 `Money`；允许为零；证据为附注。
- `F1..F5`：最新至最早的五个完整可比年度归母 FCF；实现输入字段名为 `annual_fcf_newest_to_oldest`，顺序固定为 `(F1, F2, F3, F4, F5)`；单位为 `Money`；负值必须保留；缺年不补零。
- `L`、`L_prev`：最新及上年同类、归母、可比的年化 FCF；单位为 `Money`；默认优先真实 TTM。
- `g`：确认实质衰退时有依据的年度线性变化率；单位为 `SignedRatio`，`-0.20` 表示年度线性变化率 `-20%`；必须小于等于零；未能可靠量化时取明确配置的 `0`，不能由季度跌幅机械推导。

### 穿透回报

- `O`：可分配年度归母现金容量；单位为 `Money`；不允许用绝对估值的 `F0` 自动替代；证据为最近完整年报、归属桥接和必要的最新约束。
- `D`：`(as_of - 365 自然日, as_of]` 内已实际支付、当时可知的普通现金股息；单位为 `Money`；左开右闭；特别股息与未支付宣派股息不纳入。
- `B_actual_365d`：`[as_of - 365 自然日, as_of]` 内实际执行且注销效果核实的回购额；单位为 `Money`；窗口含端点。
- `B_latest_complete_calendar_year`：截至 `as_of` 事件覆盖已核验完整的最近结束自然年合格回购额；单位为 `Money`；若覆盖不可核验则为 `UNKNOWN`。
- `B_buyback`：`min(B_actual_365d, B_latest_complete_calendar_year)`；单位为 `Money`；仅纳入满足持续性、注销效果和事件覆盖要求的回购。
- `tau`：股息税方法参数；单位为 `UnitRatio`；A 股默认场景由配置明确设为 `0`；回购不扣该税。
- `II`：要求回报；单位为 `NonNegativePct`；A 股为 `China_10Y_government_bond_yield + 2`，基准利率必须可追溯至估值日。
- `GG`：穿透回报；单位为 `NonNegativePct`；若必要输入未知则为 `UNKNOWN`，不是零。

### PIT 与运行元数据

- `available_at`：投资者可使用该数据的最早时间；不是抓取时间的隐式替代；用于 PIT 过滤。
- `provider_revision_sequence`：供应商声明有序的修订顺序；用于同经济期间可见版本选择。
- `as_of`：计算信号时点；任何 PIT 读取只返回 `available_at <= as_of` 的版本。日频
  市场 `as_of: date` 表示该日收盘后，该日 RAW 收盘价可用于生成信号，但组合
  模拟最早只能在下一可交易时点成交，禁止用产生信号的同一收盘价成交。
- `rules_version`：本文件版本；必须写入 `RunManifest`。

研究 `as_of` 覆盖与成交日推导缓冲严格分离：

- 所有信号生成和历史价格、因子、利率查询必须位于对应域快照配置的
  `config.start_date <= requested_date <= config.end_date`。越界抛出明确 coverage
  错误，不得返回部分区间、空集合冒充完整结果或最近旧值；
- 日历同步可保存 `(end_date, end_date + 10 天]`。采集层只可用它为
  `obs_date <= end_date` 的最后观测推导 `available_at`；Reader 只可用它回答
  `next_trading_day(end_date)`，以安排截止日收盘信号后的首个成交日；
- 缓冲日期可以作为未来成交安排结果，但不得作为研究 `as_of`，不得参与信号、
  证券池、历史价格、因子或利率查询，也不得从缓冲日期继续递归向后扩张。

财报和事件的 PIT 语义冻结为：

- 法定原始财报及更正公告各自按保守 `available_at` 进入 PIT；免费源
  `latest_restated_only` 只可从 `first_observed_at` 起使用；
- `observation_revision_sequence` 只描述本地开始采集后的观察顺序，不得冒充
  `provider_revision_sequence`。首次观察前无法恢复的版本为 UNKNOWN，禁止用
  当前值回填历史；
- 长历史财报回测若要求完整 PIT，必须取得有序供应商修订源，或逐份解析法定
  原文和更正公告；否则该期间财务输入为 UNKNOWN；
- 明确属于年度利润分配的普通股基础现金股息，且法定文件未标注特别、额外、
  一次性、清算或资本返还等性质时，`is_ordinary=TRUE`。明确的特别、额外或
  一次性部分为 FALSE；混合方案不能可靠拆分金额时整项为 UNKNOWN；
- 中期股息仅在法定文件明确属于常规分配政策时为 TRUE，否则 UNKNOWN；实施
  公告中的预定支付日不证明支付完成，只有明确完成公告或后续法定定期报告才能
  从自身 `available_at` 起令 `is_paid=TRUE`；
- 未证明查询窗口分红事件覆盖完整时，聚合 `D=UNKNOWN`；
- 回购累计进度差分只形成 `[interval_start, interval_end]` 区间审计证据，不得把
  区间首日、末日、公告日或 `available_at` 伪装成 `executed_on`。主路径
  `B_actual_365d`、最近完整自然年金额和持续性判断必须使用逐日或逐笔实际执行
  日期；缺少精确日期时为 UNKNOWN。区间金额不得代入 `GG`、价阶或持续性。

## D 组：绝对估值公式

```text
alpha = E / (E + max(N, 0))
FCF_ordinary = (OCF - Capex) * alpha
FCF_conservative = (OCF - Capex - Lease_cash_not_already_deducted) * alpha
K = (C + A - B_debt) * alpha

M5 = median(F1, F2, F3, F4, F5)
A3 = (F1 + F2 + F3) / 3
F_norm = min(M5, A3)

TTM = FY_previous + YTD_current - YTD_previous_comparable
F0 = max(0, min(F_norm, max(0, L)))
raw_delta = L - L_prev
delta_base = max(-0.10 * F0, min(0.10 * F0, raw_delta))

delta_used = delta_base
delta_used_if_material_decline = min(delta_base, F0 * g)
F(t) = max(0, F0 + t * delta_used), t = 1..6

R(n) = K + sum(F(t) for t = 1..n)
Coverage(n) = R(n) / MV
FlatCoverage(n) = (K + n * F0) / MV
SupportMV(n) = max(0, R(n))
SupportPrice(n) = P * SupportMV(n) / MV
Payback = k - 1 + (MV - R(k - 1)) / F(k)
```

特殊语义：

- `F1..F5` 不可省略负年份或用较早好年份替换近期坏年份。
- `M5`、`A3` 恰有一个为零时取另一个；两者均为零时为零；缺年不能填零触发该例外。
- 仅当 `F0`、`L`、`L_prev` 均为正时计算 `delta_base`；否则为零并记录原因。
- `L` 或 `F_norm` 缺失时不产生标准通过结果。
- `K` 可以为负；若 `K >= MV`，`Payback=0`。
- `Coverage(6) >= 1` 只表示绝对回本条件通过，不代替企业前提或穿透回报。

## E 组：穿透回报公式

```text
D_alloc = min(max(D, 0), max(O, 0))
O_remaining = max(0, O - D_alloc)
B_alloc = min(max(B_buyback, 0), O_remaining)
ShareholderCash_net = D_alloc * (1 - tau) + B_alloc
GG = ShareholderCash_net / MV * 100

II_A = China_10Y_government_bond_yield + 2
KK = GG - II
ObservePrice = P * GG / II
HeavyPrice = P * GG / max(10, II)
StandardPrice = (ObservePrice + HeavyPrice) / 2
```

特殊语义：

- 股息先占税前容量，回购只使用剩余容量；不能在扣股息税后释放容量。
- `O=0` 且必要事件完整时，`GG=0`；任何必要事件未知时，`GG=UNKNOWN`。
- `B_buyback` 需在最近 `3×365` 日至少有三个执行日、跨度不少于 180 日、跨至少两个日历年、最近一次不早于 120 日，且最近完整自然年金额覆盖可靠。
- 已核实但持续性不达标的回购可作为零纳入主路径，实际执行金额另列。
- `executed_buyback_365d` 仅为历史执行参考，不能代入主路径 GG。
- 仅当 `P`、`GG`、`II` 都为正时计算价阶；`10` 表示 `10%`；标准价是价格中点。

## 复权规则

研究价格使用 `ADJUSTED_TO_AS_OF`（前复权到 `as_of` 尺度）：

- 估值日价格等于该日可交易原始收盘价；
- 历史价格按截至 `as_of` 的拆并股、除权除息等公司行为调整；
- `market_position` 与 `floor_price` 必须使用同一版本的因子序列；
- 交易模拟使用原始价格，并独立应用公司行为。

对 StockDB 已计算好的累积因子水平，先固定可见集合
`V(as_of) = {observation | available_at <= as_of}`。对任意 `d <= as_of`：

- `F(d)` 取 `V(as_of)` 中 `ex_date <= d`、`ex_date` 最大的观察；同一除权日有
  修订时再取 `available_at` 最大的一条；若不存在则为 `1`；
- `F(as_of)` 按相同方法在同一 `V(as_of)` 中求得；禁止把历次累积因子再次连乘；
- 同一 `(security_id, ex_date, available_at)` 出现冲突因子值时硬失败；
- `AdjustedPrice(d, as_of) = RawPrice(d) × F(d) / F(as_of)`。

## 阶段 A Reader 契约

调用方必须显式传入每个域的 `snapshot_id`；禁止扫描目录选择 latest，禁止自动
跟随撤销记录中的 replacement。构造时必须通过 `verify_published_domain` 核对
complete meta、内容身份、文件 SHA-256、域逻辑哈希、schema/normalization 白名单
和撤销目录。`security_master`、`market_daily`、`adjustment_factors` 必须来自同一
快照；日历和中债利率可来自显式指定的辅助快照。

### 行情输出与覆盖问题

`RawPriceBar` 使用规范证券 ID、`date`、有限非负 `Decimal` OHLC、可空但非负的
成交量/额、`bool | None` 停牌状态、`adjust_type=RAW`，以及可空的
`evidence_ref/source_row_hash`。证据缺失必须保留 None，不得伪造。

`PriceBarSeries` 是不可变对象，包含 `bars`、`coverage_issues`、`quality_flags`，
其 `coverage_complete` 派生为 `not coverage_issues`。`CoverageIssue` 包含
`issue_type`、`security_id`、闭区间 `date_range` 和可选 `evidence_ref`：

| issue_type | 下游处理 |
|---|---|
| `SECURITY_NOT_COVERED` | 该证券阶段 A 行情能力为 `NOT_SUPPORTED`，不得映射为 `NOT_APPLICABLE` |
| `MISSING_BAR` | 只使受影响日期为 UNKNOWN；要求完整窗口的规则为 UNKNOWN/NEEDS_REVIEW |
| `PAUSE_STATUS_UNKNOWN` | 数值价格仍可描述；流动性、可交易性、成交模拟和可交易 `P` 为 UNKNOWN |
| `EVIDENCE_MISSING` | 数值仅用于不要求可追溯性的计算或诊断；不得形成可发布通过结论，证据依赖规则为 NEEDS_REVIEW |

有效 bar 满足 `start <= trade_date <= min(end, as_of)`。单日估值 `P` 只接受
`as_of` 当日正的可交易 RAW close；非交易日、停牌、零占位或缺 bar 为 UNKNOWN，
不自动沿用前收盘。

### 利率与日历

- 唯一利率 series 标识为 `CN_GOVT_10Y_YIELD_PCT`，返回完整 `RateObservation`；
  未知标识抛参数错误；`1.7` 表示 `1.7%`；
- 选择最新 `available_at <= as_of` 的中债国债 10Y 记录。陈旧度是开区间
  `(available_at, as_of)` 内的交易日数量，允许值固定为 `0`；至少有一个交易日
  时返回 None/UNKNOWN，不继续寻找更旧值。周末和长假不增加陈旧度，端点不计入；
- `calendar_day`、`previous_trading_day` 和普通 `next_trading_day` 受研究覆盖约束；
  唯一缓冲例外是 `next_trading_day(end_date)`。当前只接受 `exchange="cn"`，
  日历覆盖中有缺日时不得返回部分推导。

### 运行清单

阶段 A Reader 必须将全部去重 snapshot ID、证券/行情 cohort 的 `universe_hash`、
所有已选域质量标记、规则版本和稳定来源版本提供给 `RunManifest`。域撤销始终是
硬失败；warning 不自动阻断读取，但依赖相应字段的规则必须传播 UNKNOWN 或
NEEDS_REVIEW。

## 通用 FCF Profile 输入

v1.3.0 只支持沪深主板人民币普通股中通用 FCF 模型适用的非金融、非房地产
开发企业。银行、保险、证券及其他金融企业、房地产开发企业和无法可靠分类的
企业返回 `NOT_SUPPORTED`，不得套用本 Profile。

所有财务流量优先使用同一币种、同一会计范围的合并报表；存量使用期末值，流量
使用完整年度或严格可比 TTM。合并/母公司范围混用、币种不一致、期间不连续或
来源修订链不完整时为 `UNKNOWN`。来源字段到规范项的映射必须版本化并保留证据，
未列明原始字段不得通过模糊名称自动并入。

### 科目归属与连续年度

- 五个年度 ROE 固定使用 `Y0..Y0-4` 的归母净利润以及 `Y0..Y0-5` 六个连续
  财年末的 `E`。每个观察都必须 `available_at <= as_of`；任一年度缺失、不可
  追溯、范围不一致或未来才可见时，`premise.roe_5y=UNKNOWN`。不得跳过缺年，
  也不得用 `Y0-6` 或更早权益替代 `Y0-5`；
- `N` 只有在同期总权益可核实等于 `E` 时，缺失才可解释为零；
- `C` 的货币资金和受限金额各自保留已知/未知状态，计算严格分为：
  - 货币资金已知、受限金额有证据地等于 `0`：`C=货币资金`；
  - 货币资金已知、受限金额已知为正数：`C=货币资金-受限金额`；
  - 货币资金已知、受限金额未知：`C=UNKNOWN`；
  - 货币资金未知：`C=UNKNOWN`，无论受限金额状态为何；
  - 受限金额为负或大于已知货币资金是数据完整性错误，硬失败而非 UNKNOWN。
    缺字段不是明确的零；
- `A` 只包含一年内可变现、明确属于金融资产且未计入 `C` 的项目。交易性金融
  资产、债权投资、其他债权投资和一年内到期的金融资产按附注明细纳入；
  `OTHER_CURRENT_ASSET` 不因名称含“流动”而自动纳入；
- `B_debt` 包含短期借款、明确属于有息债务的一年内到期负债、应付短期债券、
  长期借款、应付债券和租赁负债；无法从混合科目拆出有息部分时为 `UNKNOWN`；
- `Lease_cash_not_already_deducted` 只计未包含在 OCF 或 Capex 中的现金租赁支出；
  无法排除重复扣减时为 `UNKNOWN`。

### 标准保守 FCF 路径

```text
alpha_y = E_y / (E_y + max(N_y, 0))
FCF_y = (OCF_y - Capex_y - Lease_cash_not_already_deducted_y) * alpha_y
F1..F5 = 最新至最早五个完整年度的 FCF_y

L = FCF_FY_previous + FCF_YTD_current - FCF_YTD_previous_comparable
O = 最新完整年度的 (OCF - Capex - Lease_cash_not_already_deducted) * alpha
```

`FCF_ordinary` 只作诊断，不得替代 `F1..F5`。负值保留，缺年不跳过或用更早年份
补位。若最新可见期恰为完整年度，`L` 为该年度 FCF；`L_prev` 使用向前平移一年
的同口径值。TTM 三段的报表范围、币种、累计口径或期间不可比时为 `UNKNOWN`。
`O` 不使用 `F_norm`、`F0`、预测值或季度机械年化替代；原始负值保留，由 E 组
共享容量公式执行 `max(O, 0)`。

## `GENERAL_FCF` 企业前提与评分

### 六项硬门

以下规则均为 `HARD_GATE`：

1. `premise.profile_supported`：点时行业明确为通用非金融、非房地产开发；
2. `premise.statement_integrity`：五个完整年度及 TTM 所需期间同范围、同币种、
   可追溯；最新年报审计意见为无保留意见，且无持续经营重大不确定性；
3. `premise.positive_equity`：最新 `E > 0`；
4. `premise.roe_5y`：五年年度 ROE 中位数至少 `10%`。年度 ROE 为
   `parent_net_profit / average(E_begin, E_end) × 100`；六个连续年末权益中任一
   不可用即为 UNKNOWN；
5. `premise.fcf_consistency`：五个标准保守 FCF 中至少四个严格大于零；
6. `premise.leverage`：`net_debt=max(0, B_debt-C-A)`。`F_norm>0` 时要求
   `net_debt/F_norm <= 3`；`F_norm<=0` 时失败；必要输入未知时为 UNKNOWN。

风险警示、立案调查或重大违法状态不伪装成企业财务前提；它们在证券池规则中
独立处理并保留各自点时证据。

### 质量评分

通过全部硬门后，四个 `SCORE` 分项按下式计算：

```text
roe_score = clamp((median_roe_5y - 10) / 10, 0, 1) * 100
fcf_stability_score = positive_fcf_years / 5 * 100
cash_conversion = sum(OCF_y * alpha_y) / sum(parent_net_profit_y), y=1..5
cash_conversion_score = clamp(cash_conversion / 1.2, 0, 1) * 100
balance_score = 100,                                      if net_debt = 0
                clamp(1 - net_debt / (3 * F_norm), 0, 1) * 100, otherwise

quality_score = 0.35 * roe_score
              + 0.25 * fcf_stability_score
              + 0.25 * cash_conversion_score
              + 0.15 * balance_score
```

评分配置必须使用非负有限 `Decimal`，键集合恰好为四个分项且精确合计 `1.00`；
不使用浮点容差，不接受多余或缺失键。`sum(parent_net_profit_y)<=0` 时现金转换分项
为 UNKNOWN。任一适用分项未知时，`quality_score=None`，`score_coverage` 等于已知
分项原始权重之和；不得重分配权重或重新归一化。可以另报 `reference_raw_score`，
但不得进入 Tier 或官方排序。

规则结果聚合固定为：`HARD_GATE`、`SCORE` 或 `EVIDENCE` 的 UNKNOWN/NEEDS_REVIEW
阻断标准结论；纯 `INFORMATION` 的 UNKNOWN/NEEDS_REVIEW 只附注。阻断型未知优先
于已知硬门失败，避免关键输入未知时声称已证明淘汰；纯 INFORMATION 不参与该
优先级。

## 行情位置 Profile

`market.position` 使用与绝对估值相同的 `as_of`、同一因子可见集和
`ADJUSTED_TO_AS_OF` 收盘价：

- 回看截至 `as_of` 的最近 `756` 个交易日；
- 至少需要 `504` 个有证据的正收盘价；不前向填充停牌或缺失日；
- 窗口内存在无法由明确停牌解释的 `MISSING_BAR`、因子冲突或证据缺失时，标准
  结果为 `UNKNOWN/NEEDS_REVIEW`；
- 计算如下：

```text
position_pct = (count(price < P) + 0.5 * count(price = P)) / n * 100
drawdown_from_high_pct = (P / max(price) - 1) * 100
market_position_score = 100 - position_pct
```

全部历史价格相等时 `position_pct=50`。标签固定为 `[0,20] LOW`、
`(20,40] LOWER_MID`、`(40,60] MID`、`(60,80] UPPER_MID`、`(80,100] HIGH`。
标签仅解释，不单独淘汰证券；结果未知时不改变单证券 D/E 候选事实，但该证券
不能进入官方横截面排序。

## 点时证券池、信号与诊断边界

每个信号日按以下顺序形成结构证券池：

1. `security_ids_as_of(as_of)` 中仍处于主板有效区间的沪深 A 股；
2. 上市已满 `504` 个交易日；
3. 点时行业为 `GENERAL_FCF` 支持范围；
4. 当日未处于 ST、*ST、退市整理、暂停上市或已公告终止上市状态；
5. `MV >= CNY 5,000,000,000`；
6. 最近 60 个交易日中至少 50 个有证据、可交易的 amount，且其中位数
   `>= CNY 20,000,000`；
7. 阶段 A 覆盖、股本、行业或状态未知时，该证券为 `NEEDS_REVIEW`，不得伪装成
   “不在池中”。

两个金额阈值是预先冻结的项目基线，不是制度事实或回测优化结果。信号日为每个
自然月最后一个中国交易日，`as_of` 表示收盘后。只有全部硬门已知且通过、
`Coverage(6)>=1`、`GG>=II` 且所有适用评分完整时才是 `CANDIDATE`。

官方候选表要求结构证券池中的每只证券都有可审计终态
`CANDIDATE/REJECTED/NOT_SUPPORTED`。存在任一 `NEEDS_REVIEW` 时，该月只能生成
诊断报告，不得生成官方 Top-N 或可发布回测。诊断报告可以包含证券的硬门、评分、
证据状态、缺失字段、原因和数据质量旗标；不得包含横截面分位数、
`composite_score`、任何排名、Top-N、推荐顺序、目标权重、订单计划、持仓或净值。
文件名、schema 和标题必须标明 `diagnostic_only=true`、
`official_selection=false`。

## 排序与目标组合

只对同一信号日的 `CANDIDATE` 排序。横截面百分位使用 mid-rank：

```text
percentile_rank(x) = (count(value < x) + 0.5 * count(value = x)) / n
coverage_rank = percentile_rank(Coverage(6)) * 100
gg_margin_rank = percentile_rank(GG - II) * 100

composite_score = 0.30 * quality_score
                + 0.30 * coverage_rank
                + 0.30 * gg_margin_rank
                + 0.10 * market_position_score
```

只有一个候选时百分位为 `0.5`。按 `composite_score` 降序、`security_id` 升序稳定
排序并取前 20 名；不作行业内二次排名，也不因候选不足而放宽规则。

```text
selected_count = min(candidate_count, 20)
target_weight_i = min(5%, 1 / selected_count), selected_count > 0
```

少于 20 只时每只仍不超过 5%，剩余持有现金；不加杠杆、不做空、不自动分摊
现金。标准初始资金为 `CNY 10,000,000`。零候选时目标组合为 100% 现金，已有
持仓生成退出订单。

## 调仓、订单与成交

- 每月信号后的首个可交易日调仓，禁止信号收盘价成交；现有持仓不再是候选或不在
  Top 20 时目标权重为零；不设排名缓冲、止盈、止损或盘中择时；
- 同一成交时点先卖后买。买入向下取整到 100 股；卖出可一次处理剩余零股；目标
  差额不足一手时不下单；
- 目标持仓金额固定为信号日收盘净值乘目标权重；目标股数用信号日 RAW 收盘价
  向下取整，不得用次日开盘价反算；
- 次日跳空和费用导致现金不足时，买单先按同一比例缩减并向下取整到整手，再按
  `composite_score` 降序、`security_id` 升序逐手补配；不得突破原目标股数、参与率
  或现金余额，未执行差额不因价格变化自动扩大；
- 快照 `end_date` 信号只能由日历缓冲安排下一成交日。成交日行情不在显式市场
  快照覆盖内时订单为 `PENDING_OUT_OF_COVERAGE`，不得产生虚构成交；
- 成交基准价为可执行日 RAW 开盘价；买入乘 `(1 + 10 bps)`，卖出乘
  `(1 - 10 bps)`；
- 日参与率上限为执行日前严格连续 20 个中国交易日平均成交额的 `5%`。每个日期
  都须有可追溯 amount；有证据的停牌零成交额以 `0` 计入，分母始终为 20。缺 bar、
  amount 未知、证据不足、日历缺口或不足 20 日时，当日不成交并记录
  `PARTICIPATION_RATE_UNKNOWN`，不得跳过缺日或改用更早日期；
- 证券池“60 日中至少 50 日”只是最低流动性筛选，不能替代成交所需完整 20 日；
- 未成交数量最多顺延 5 个交易日，每天重新检查交易能力和参与率，到期取消；
- 必须读取点时 `can_buy/can_sell`、停牌和涨跌停状态，不得从 OHLC、前收盘或名称
  猜测。状态未知时当日不成交并标记质量问题；
- 买入股份自下一交易日起可卖，逐成交批次执行 T+1。同日卖出所得现金可用于买入，
  但未交收股份不可卖出。

## 成本、公司行为与异常退出

标准成本参数全部进入配置哈希：券商净佣金 `3 bps`、每笔最低 `CNY 5`；模型
滑点 `10 bps` 双边进入成交价；交易所经手费和中国结算过户费按成交日有效费率
双边计收；证券交易印花税按成交日有效税率仅向卖方计收。净佣金不包含后三者。
费率表必须按生效日版本化，禁止用当前费率回填历史；缺费率时成本为 UNKNOWN，
对应运行不可发布。

- 现金股息只在核实的实际支付日计入现金；基线报告为交易成本后、股息税前；
- 送股、转增、拆并股在除权日开盘前调整持仓股数和单位成本，不凭空改变资产总额；
- 配股、权证、换股、要约收购及无法定价重组没有专用规则时使持仓路径
  `NEEDS_REVIEW`；
- 停牌或跌停无法成交时继续持有。仅在有独立停牌证据时，组合记账可沿用停牌前
  最后一个有证据 RAW 收盘价并记录陈旧天数；该值不得成为估值输入 `P`、信号价、
  流动性 bar 或成交价；
- 退市前按相同卖出规则尝试执行；最终退出现金流或剩余权利未知时，不得用最后
  收盘价、零或事后恢复价格替代，整段可发布绩效被阻断。

现金余额不计利息。融资、融券、申购新股和盘后固定价格交易不在本版本范围。

## 基准、绩效与可复现输出

主基准固定为中证全指全收益指数 `H00985`。候选生产来源固定为中证指数有限公司
官方 JSON 接口 `https://www.csindex.com.cn/csindex-home/perf/index-perf`，
`source_id=csindex_official_index_perf_v1`。生产适配器必须直接请求官方接口，参数为 `indexCode=H00985`、
`startDate=YYYYMMDD`、`endDate=YYYYMMDD`；原始 JSON 原样保存并哈希。
每一官方响应行（包括获批隔离行）必须同时满足
`indexCode=H00985`、`indexNameCnAll=中证全指全收益指数`、
`indexNameEnAll=CSI All Share Total Return Index`，且 close 为正的有限数值。
任一身份字段缺失或不匹配均为身份漂移，硬失败；不得以第三方封装作为
数据权威或自动后备。适配器、schema、日历对账、不可变发布、撤销和真实 fixture
验收已对显式快照 `snapshot-d9fa4c6d8933fe39` 与
`snapshot-9b72a2666190542a` 的各自覆盖区间完成。基准域的 `ready` 仅限
已发布快照的已验证覆盖区间和下文 `ready_when` 的 Reader 条件；新快照或
扩展覆盖必须单独验收，不自动继承。

显式两日例外：官方响应与独立日历对账时，只能从规范化交易日序列隔离
逐字列明的 `2005-01-01` 与 `2018-06-18`；已知官方 close 分别为
`984.40` 与 `5161.74`。这是 `explicit_whitelist_v1`，不按周末、节假日、
月份或日期范围推断其他例外。原始响应保留全部行。官方点位改变、日历将
其中一日改判为交易日、源行重复、白名单外额外日期、交易日缺口或任意
请求区间外行，均硬失败。新增例外须项目负责人另行裁决并更新规则白名单。

v1 快照审计编码：对含获批隔离行的快照，顶层 `data_quality_flags` 保持
字符串列表，其中 `"benchmark_excluded_dates"` 仅作例外存在的索引。
按日期排序的完整日期列表和逐项结构化证据分别存于
`domains.benchmark.details.benchmark_excluded_dates` 与
`domains.benchmark.details.exclusion_evidence`；这是基准例外内容的单一
真相源。`source_provenance.csindex.exclusion_policy` 固定为
`"explicit_whitelist_v1"`。无隔离行的既有快照可不含标记、日期、证据和
policy，不因此失效；有隔离行时上述字段必须齐全。此编码只约束基准域，
其他生产域不得未经各自 ready 提案自动套用。

`verify_published_domain` 校验顶层和域内标记存在当且仅当 details 有
非空例外日期和逐项完整证据；任一侧不一致即硬失败。Reader 复核原始响应、
独立日历和规范化行，并在任意非空子区间返回值中附完整快照级标记、日期
和证据，不按查询区间过滤；空子区间仍可从 Reader 自身读取完整快照级状态。

抓取时点与身份：`fetched_at_utc` 只记录于快照
`source_provenance.csindex.fetch_time_utc`，供审计且不参与内容身份；
规范化 Parquet 行只存稳定 `response_hash`。Reader 只附上当前显式
snapshot ID 自身 meta 的抓取时点，不按响应哈希跨快照寻找时点。

基准缺日不前向填充，策略和基准在共同可评估交易日对齐。至少报告期初/期末净值、
累计收益、CAGR、固定 252 的年化波动率、最大回撤及起止日、当日可见中债 10Y
为无风险利率的 Sharpe、超额 CAGR、跟踪误差、信息比率、月度胜率、年度收益、
换手率、持仓数、现金比例、各类成本和执行/质量问题次数。

```text
daily_return_t = NAV_t / NAV_(t-1) - 1
calendar_years = (end_date - start_date).days / 365.2425
CAGR = (NAV_end / NAV_start)^(1 / calendar_years) - 1
annualized_vol = sample_std(daily_return) * sqrt(252)
risk_free_daily_t = (1 + yield_pct_t / 100)^(1 / 252) - 1
Sharpe = mean(daily_return - risk_free_daily) / sample_std(excess_daily) * sqrt(252)
tracking_error = sample_std(daily_return - benchmark_return) * sqrt(252)
information_ratio = mean(daily_return - benchmark_return)
                    / sample_std(daily_return - benchmark_return) * sqrt(252)
one_way_turnover = sum(abs(buy_notional) + abs(sell_notional))
                   / (2 * mean(daily_NAV))
```

标准差使用 `n-1` 样本分母。最大回撤同幅度并列时取最早峰值和最早谷值；月度胜率
只比较共同完整自然月。分母为零、少于两个日收益、所需利率/基准未知或样本不足时
对应指标为 UNKNOWN，且不得把整次运行标为完整。

订单、持仓和净值表按冻结主键稳定排序，把 schema 版本、列名、规范类型和值编码
成确定性 canonical row stream，再计算 SHA-256 `logical_content_hash`；不要求
Parquet 物理字节相同。`StrategyRunManifest` 引用基础 `RunManifest.content_hash()`，
并记录策略/执行政策 ID、初始资金、信号区间、生产域 snapshot ID、基准、费率表、
配置、代码/规则版本、完整性摘要及三个输出内容哈希；使用 canonical JSON。

## 生产数据门槛

除 v1.2.0 阶段 A 五域外，基准域按上节和 `ready_when` 的限定条件为
`ready`；以下其余九域仍为 `not_ready`：

| 域 | 状态 | 必需能力/来源 |
|---|---|---|
| 财务报表 | `not_ready` | 目标范围完整法定修订链、范围、审计意见、持续经营状态和规范科目 |
| 分红 | `not_ready` | 全窗口事件、普通性、实际支付日、金额和修订 |
| 回购 | `not_ready` | 全计划、逐日/逐笔执行、注销和完整自然年覆盖 |
| 行业 | `not_ready` | 点时行业分类及分类标准版本；来源待验收 |
| 股本 | `not_ready` | 点时总股数及公司行为桥接；**来源待定** |
| 证券状态 | `not_ready` | ST/*ST、退市整理、暂停/恢复上市、终止上市决定及可用日 |
| 交易能力 | `not_ready` | 每日 can_buy/can_sell、停复牌、涨跌停状态及规则版本 |
| 公司行为 | `not_ready` | 现金分红、送转、拆并股、配股、换股和退出现金流 |
| 基准 | `ready`，仅限已验收快照覆盖 | 官方中证 JSON API；完整条件见 `ready_when` |
| 成本 | `not_ready` | 按生效日版本化的税费表 |

所有域必须绑定 snapshot ID 并写入运行清单。历史股本是独立阻塞；不得用当前总
股本、当前市值、复权因子或事后公司行为反推回填。任一门槛未满足时，只能运行
纯逻辑、合成 fixture 或数据验收，不得发布真实选股、净值或绩效。

## v1.3.0 黄金验收

实现至少证明：未来财报/行业/状态/股本不可见；历史退市证券不被当前列表抹去；
五年 FCF 不跳过负年；现金明确零不等于缺失；混合科目未知传播；评分缺项不重新
归一化；诊断报告不含排名/权重/订单/净值；行情位置与估值使用同一因子可见集；
信号只能在下一交易日以后成交；20 日参与率不跳过缺日；涨跌停、停牌、T+1、
部分成交、五日取消和手数有边界算例；历史费率正确切换；公司行为和未知退出不
产生虚构现金流；重复运行逻辑内容哈希和 canonical manifest 相同；`as_of` 之后的
数据不能改变此前信号、订单或净值。

## 自建算例

### FX-001：前复权价格

来源：自建。目的：验证历史价格和估值日价格处于同一尺度。

输入：

```text
T0 原始收盘价 = 20
T1 除权后原始收盘价 = 10
as_of = T1
T0 到 T1 的调整因子 = 0.5
```

推导：

```text
AdjustedPrice(T0, as_of) = 20 × 0.5 = 10
AdjustedPrice(T1, as_of) = 10
```

断言：两点均为 `10`；估值日价格保持可交易原始收盘价 `10`。

### LB-001：股息与回购窗口边界

来源：自建，时间边界来自 `lookthrough-return.md`。

输入：

```text
as_of = 2025-12-31
Dividend at 2024-12-31 = 10
Dividend at 2025-01-01 = 20
Buyback at 2024-12-31 = 30
Buyback at 2025-01-01 = 40
```

推导：

```text
D 窗口为 (2024-12-31, 2025-12-31]，所以只计 20
B 窗口为 [2024-12-31, 2025-12-31]，所以计 30 + 40 = 70
```

断言：`D=20`，`B_actual_365d=70`。

## ready_when

本节是唯一实施推进门槛。只有状态为 `ready` 的文件允许写实现；未就绪模块只能声明接口与 `NotImplementedError`。

- `turtle_quant/core/types.py`
  - 状态：`ready`
  - 条件：单位语义、空值语义和 fixture 已冻结。
  - 阻塞项：无。
- `turtle_quant/core/result.py`
  - 状态：`ready`
  - 条件：状态枚举和 `rule_kind` 已冻结。
  - 阻塞项：无。
- `turtle_quant/core/pit.py`
  - 状态：`ready`
  - 条件：`available_at`、修订选择算法和 PIT fixture 已冻结。
  - 阻塞项：无。
- `turtle_quant/core/manifest.py`
  - 状态：`ready`
  - 条件：RunManifest 字段已冻结。
  - 阻塞项：无。
- `turtle_quant/core/protocols.py`
  - 状态：`ready`
  - 条件：加入 `TradingCalendarReader`；证券、行情、因子和利率 Reader 使用阶段 A
    强类型边界，行情序列显式返回覆盖问题。
  - 阻塞项：无。
- `turtle_quant/storage/`
  - 状态：`ready`
  - 条件：仅实现原始快照的内容寻址、staging 原子发布、完整性校验和运行元数据；数据契约见 `docs/data-ingestion-contract.md`。
  - 阻塞项：无。此状态不代表真实数据已具备 PIT 研究资格。
- `turtle_quant/adapters/`
  - 状态：`ready`
  - 条件：仅实现历史证券主表、交易日历、原始日 K、复权因子和中债 10 年期收益率的采集与规范化；未知值不得降级为零。
  - 阻塞项：财报、分红和回购只允许样本契约探针，未通过数据契约前不得全量发布。
- `scripts/sync_local_data.py`
  - 状态：`ready`
  - 条件：仅编排不可变原始快照；必须执行锁、断点恢复、必需域质量门槛和内容型 `snapshot_id` 校验。
  - 阻塞项：不得调用领域计算、不得输出真实选股或回测结论。
- `turtle_quant/pit/parquet_foundation.py`
  - 状态：`ready`
  - 条件：只实现证券、日历、RAW 行情、累积复权因子和中债 10Y 的阶段 A 读取、
    显式多快照选择、完整性/撤销/版本/覆盖校验、PIT 截断和 RunManifest 输入。
  - 阻塞项：不得读取财报、股息或回购，不得产出研究筛选或回测结果。
- `turtle_quant/pit/parquet_benchmark.py`
  - 状态：`ready`，仅限显式绑定且已验收的 H00985 快照覆盖区间。
  - 条件：直接使用中证官网官方 JSON API；原始响应不可变留存并哈希；
    显式 snapshot ID、内容身份、撤销检查和真实 fixture 均通过；与独立
    已发布日历逐日对账；仅隔离上文两日白名单；Reader 复核原始响应、
    规范化 Parquet 和快照级审计元数据。
  - 阻塞项：其他九域和真实研究/回测编排继续 `not_ready`；本 Reader 的
    ready 不授权真实策略输出。扩覆盖、新例外或新快照须重新验收。
  - 后续真实接入约束：策略配置须显式冻结 `benchmark_snapshot_id` 并写入
    `StrategyRunManifest`；这是未来真实策略编排的条件，**不是**本 Reader
    当前转 ready 的前置条件。基准日值与合成策略可作未来纯技术联调，
    但不得产出可发布绩效或称为真实回测；该联调亦非当前 ready 前置条件。
- `turtle_quant/pit/parquet_financial_statements.py`
  - 状态：`not_ready`
  - 条件：法定原文与更正公告完整清点，逐版本可用日、范围、映射和修订顺序通过
    真实 PIT fixture 后可独立转 ready。
  - 阻塞项：当前只有九个样本和向前观察链，无目标范围完整修订覆盖。
- `turtle_quant/pit/parquet_dividends.py`
  - 状态：`not_ready`
  - 条件：目标窗口全部分红事件覆盖、普通/特别分类、金额和支付完成修订通过真实
    PIT fixture 后可独立转 ready。
  - 阻塞项：普通性和全窗口事件覆盖尚未验收。
- `turtle_quant/pit/parquet_buybacks.py`
  - 状态：`not_ready`
  - 条件：全部回购计划及逐日/逐笔执行日期、金额、注销和完整自然年覆盖通过真实
    PIT fixture 后可独立转 ready。
  - 阻塞项：现有样本缺精确执行日和全部计划覆盖。
- `turtle_quant/pit/parquet_finance.py`
  - 状态：`not_ready aggregate facade`
  - 条件：三个财务专用模块全部 ready，且跨域选择、UNKNOWN 传播和组合测试通过。
  - 阻塞项：不允许部分开放；任一子域未就绪时继续显式失败。
- `turtle_quant/pit/parquet.py`
  - 状态：`not_ready compatibility stub`
  - 条件：旧 `ParquetPITReader` 继续显式失败并指向 foundation、三个财务专用模块
    和聚合门面，不得静默改成 foundation Reader。
  - 阻塞项：旧接口范围含混，禁止恢复读取。
- `turtle_quant/valuation/absolute.py`
  - 状态：`ready`
  - 条件：D 组公式、单位、时间口径和黄金算例已冻结。
  - 阻塞项：无。
- `turtle_quant/valuation/lookthrough.py`
  - 状态：`ready`
  - 条件：E 组公式、D/B 窗口和黄金算例已冻结。
  - 阻塞项：无。
- `turtle_quant/pipeline/decision.py`
  - 状态：`ready`
  - 条件：优先级、规则性质和评分覆盖率语义已冻结；纯 INFORMATION 未知不阻断。
  - 阻塞项：无。
- `turtle_quant/evidence/validate.py`
  - 状态：`ready`
  - 条件：只实现已知零、未知、非法差额等证据状态纯校验，不进行 I/O。
  - 阻塞项：无。
- `turtle_quant/market/position.py`
  - 状态：`ready`
  - 条件：只实现 756/504 窗口、证据完整性、mid-rank、回撤、标签和因子视图身份
    的纯计算。
  - 阻塞项：生产行情仍受阶段 A 与 v1.3.0 跨域门槛约束。
- `turtle_quant/premise/`
  - 状态：`ready`
  - 条件：只实现通用 FCF 科目桥接、六项硬门、四项评分和合成 fixture。
  - 阻塞项：生产财报、行业和股本 Reader 仍为 `not_ready`。
- `turtle_quant/strategy/`
  - 状态：`ready`
  - 条件：实现点时证券池判定、整月完整性、诊断边界、排序、目标权重和订单计划
    的纯逻辑及合成 fixture。
  - 阻塞项：真实研究编排保持 `not_ready`，直到全部生产域通过验收。
- `turtle_quant/backtest/`
  - 状态：`ready`
  - 条件：实现成交、费用、T+1、公司行为、记账、绩效、逻辑内容哈希和
    `StrategyRunManifest` 的确定性纯逻辑及合成 fixture。
  - 阻塞项：生产交易能力、公司行为和成本域仍为 `not_ready`；基准仅限已验收
    快照覆盖可读。真实研究编排及其他生产域未就绪，不得接成可发布回测。

状态变更必须在变更记录中记录日期、操作者和对应规则版本。

## 变更记录

- `v1.0.0` — 2026-09-24 — 初始冻结。来源：本地 `absolute-valuation.md`、`lookthrough-return.md`、`calculation-examples.md`，以及已确认的 PIT、单位、决策和复权约束。
- `v1.1.0` — 2026-09-24 — 提出者/批准者：项目负责人。放行原始数据采集与不可变快照基础设施，不改变 D/E 公式或既有领域输出。新增 `storage/`、基础 `adapters/` 与同步 CLI 的 `ready_when`；真实数据在 Parquet PIT Reader 就绪前只可用于落库验证。受影响范围：`ARCHITECTURE.md`、`README.md`、`docs/data-ingestion-contract.md`、同步代码与合成测试。历史 v1.0.0 计算结果保持可比。
- `v1.2.0` — 2026-09-29 — 提出者：Codex；批准者：项目负责人。批准提案
  `v1.2.0-20260929-02`：冻结财报修订、普通现金股息、支付完成和回购执行日期的
  UNKNOWN 边界；放行阶段 A Parquet Foundation Reader，新增收盘后 as_of、下一
  交易时点成交、显式多快照、强类型行情/因子/利率/日历、结构化覆盖问题、零
  交易日利率陈旧容忍及累积因子前复权公式。D/E 公式与既有合成 fixture 输出
  不变；v1.1.0 授权范围外真实研究不得迁移，完整研究/回测仍受后续 ready_when
  约束。受影响范围：`RULE_SPEC.md`、`core/protocols.py`、`pit/`、RunManifest
  集成、README、ARCHITECTURE、数据契约和对应测试。
- `v1.3.0` — 2026-09-29 — 提出者：Codex；批准者：项目负责人。批准提案
  `v1.3.0-20260929-02`（批准前文本 SHA-256
  `EC86E4D1D23A41E1C0D756B84B0153758014F77C46F68D2D0743F6E8054B5197`）：冻结
  `GENERAL_FCF` 科目桥接、六项硬门、四项质量评分、行情位置、点时证券池、月度
  Top 20、目标权重、订单、成交、成本、公司行为、H00985 基准、绩效指标和逻辑
  内容哈希。放行 `evidence/`、`premise/`、`market/position.py`、`strategy/` 与
  `backtest/` 的纯逻辑和合成 fixture；所有新增生产数据域继续 `not_ready`，历史
  股本来源待定，真实选股与可发布回测继续被阻断。D/E 公式和旧 manifest 保持兼容。
- `v1.3.1` — 2026-09-30 — 提出者：Codex 代项目负责人；批准者：项目负责人
  （本次对 `v1.3.1-20260930-02` 的批准）。基线 `RULE_SPEC v1.3.0`
  SHA-256 `40c8ecd270de2def118d73746c079fe223f437f2b233cdd792035d35515c2608`；
  批准前提案 SHA-256 `cc941feb07740e3dec6db6a1a327033468e4a15cc6efe7e7054ac7e4eb94d2a8`。
  H00985 基准域及 `turtle_quant/pit/parquet_benchmark.py` 在已验收显式快照覆盖
  区间内由 `not_ready` 转为 `ready`；吸收两日显式白名单、v1 兼容编码与当前
  快照自身抓取时点裁决。任意请求区间外行继续硬失败；其他九域仍为
  `not_ready`。历史快照不迁移、不改写，真实选股和可发布回测仍不放行。
  受影响范围：本规范的基准、生产门槛、`ready_when`、兼容性，基准解析器、
  Reader、测试和审计文档。当前非 Git 工作目录的发布记录另见
  `docs/releases/v1.3.1.md`，未执行 `git tag`。
- `v1.3.2` — 2026-10-01 — 提出者：Codex；批准者：项目负责人。
  批准提案 `v1.3.2-20261001-01`。仅补全 §9 基准正文的 H00985 身份字段：
  - 明确请求参数为 `indexCode=H00985`、`startDate=YYYYMMDD`、`endDate=YYYYMMDD`；
  - 明确每一官方响应行（包括获批隔离行）必须同时满足
    `indexCode=H00985`、`indexNameCnAll=中证全指全收益指数`、
    `indexNameEnAll=CSI All Share Total Return Index`，且 close 为正的有限数值；
  - 明确任一身份字段缺失或不匹配均为身份漂移，硬失败。
  这是对既有批准语义（v1.3.0 §9、v1.3.1 §9）与既有实现
  （`csindex_benchmark.py` 已逐行校验）的 PATCH 级文字补全。
  现行 §9 的两日白名单、完整响应、快照级抓取时点、v1 元数据编码、
  日历对账、两份显式快照限定 ready，以及其他九域 `not_ready` 文字均不变。
  D/E 公式、`GENERAL_FCF` 六项硬门、评分权重、证券池与整月诊断门槛、
  成交参与率均不变。旧运行、旧快照、旧 manifest 不迁移、不重释。
  受影响范围：本规范 §9 基准正文、版本号、变更记录；同步的测试补充仅验证
  既有身份校验，配置、生产代码和旧 fixture 均不变。非 Git 发布记录见
  `docs/releases/v1.3.2.md`。
