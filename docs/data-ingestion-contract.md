# 数据落库契约

**契约版本：v1**

本文冻结原始数据同步的边界。它不授权真实研究或回测；v1.2.0 的
`ParquetFoundationReader` 只把五个阶段 A 域映射为点时 Reader，财务、研究和
回测仍受各自 `ready_when` 限制。

## 快照生命周期

1. `batch_id` 只标识一次拉取任务，由 `IngestConfig` 的 canonical JSON
   计算。
2. 所有写入先进入 `storage/.staging/<batch_id>/`。
3. partial meta、分片和 checkpoint 均以临时文件加 `os.replace` 原子更新。
4. 全部必需域通过质量门槛后，按内容计算 `snapshot_id`，发布到
   `storage/snapshots/<snapshot_id>/`。
5. 读取方只能使用 complete `meta.json` 白名单中的文件。
6. `RunManifest.snapshot_ids` 引用内容型 `snapshot_id`，不引用 `batch_id`。
7. 读取方还必须检查 `storage/catalog/domain-revocations.json`；被撤销的数据域
   即使所在 snapshot 为 complete，也不得用于计算。撤销记录只能追加原因
   和替代 snapshot，不得修改原 snapshot 内容。

公共只读入口 `turtle_quant.storage.verify_published_domain` 已实现上述发布状态、
配置正文哈希、稳定来源描述、内容身份、白名单文件 SHA-256、域逻辑哈希和撤销
检查。它不发现 latest 快照，也不自动跟随 replacement；Foundation Reader 必须先
通过此入口取得已验证文件及深度只读的配置、质量标记和域详情。

`fetch_time_utc` 只用于审计，不参与内容身份；schema、规范化版本、稳定
source descriptor、逻辑内容哈希和行数参与内容身份。

## 通用列

所有规范化数据集至少有：

| 列 | 语义 |
|---|---|
| `schema_version` | 数据集 schema 版本 |
| `normalization_version` | 代码、日期、单位等规范化规则版本 |
| `source_name` | 数据源稳定标识 |
| `source_row_hash` | 原始行 canonical 内容的 SHA-256 |
| `evidence_ref` | 可定位原始记录或请求的证据引用 |

金额、价格、比率和因子必须用有限 Decimal 字符串或固定精度
`decimal128` 保存，不得用浮点 NaN/Inf 表示缺失。缺失写 null，并保留状态
或质量原因。

## 证券代码

规范代码为 `<exchange>.<six_digit_code>`，如 `sh.600000`、
`sz.000001`。原始代码和供应商代码必须保留。无法无歧义识别交易所时
报错，不猜测。

阶段 A 的历史证券主表至少包含：

| 列 | 语义 |
|---|---|
| `security_id` | 规范代码 |
| `raw_code` / `vendor_symbol` | 原始标识 |
| `exchange` | `sh` 或 `sz` |
| `board` | 当期板块 |
| `board_effective_from/to` | 板块分类有效区间 |
| `listing_date` | 上市日 |
| `delisting_date` | 退市日或 null |
| `delisting_date_semantics` | 日期是最后交易日还是摘牌日 |

主板池按 `as_of` 在读取层过滤，不能由当前在市名单反推历史证券池。

## 阶段 A 字段矩阵

| 领域 | 关键列 | PIT/口径 | 阻断条件 |
|---|---|---|---|
| `security_master` | 上述证券主表列 | 上市、退市与板块有效期 | 无退市证券、代码歧义、日期倒置 |
| `calendar` | `exchange,date,is_trading_day` | 交易所日历 | 主键重复、日期非法 |
| `market/raw_daily` | `security_id,trade_date,open,high,low,close,volume,amount,paused,adjust_type` | 仅 `adjust_type=RAW` | OHLC 主键重复、数值非有限、非 RAW |
| `corporate_actions/adjustment_factors` | `security_id,ex_date,factor,factor_source,available_at` | 研究价按 `as_of` 截断因子 | 因子非正、证据或可用日缺失 |
| `macro/cn_yield_10y` | `obs_date,yield_10y_pct,curve_id,tenor,available_at,fetched_at` | 百分数 `5` 表示 `5%`；只取当时可用值 | 请求失败、期限/曲线错误、可用日未知 |

复权验收必须从快照数据复现 `RULE_SPEC.md` 的 FX-001，并保证估值日价格
等于原始收盘价。

### v1.2.0 阶段 A 读取绑定

`turtle_quant.pit.ParquetFoundationReader` 的调用方必须显式传入五个域的
snapshot ID。证券主表、行情和因子必须是同一 snapshot；日历和利率可以来自
显式辅助 snapshot。构造时逐域执行发布校验，并只接受以下版本：

| 域 | schema | normalization |
|---|---:|---|
| `security_master` | 1 | `cn_equity_v1` |
| `market_daily` | 1 | `market_raw_v1` |
| `adjustment_factors` | 1 | `adjustment_factor_v1` |
| `calendar` | 1 | `cn_calendar_v1` |
| `chinabond_10y` | 1 | `chinabond_10y_v1` |

行情按规范证券代码的前五位数字定位已验证分片，并带证券和日期谓词读取；禁止把
全市场 12,004,094 行先转换为 Python list。同步器可能为一个完全无行情的证券
前缀写出零行、零列 Parquet 分片；Reader 只在文件哈希已经验证且物理行数为零时
接受这种空 schema，任何非零行缺列仍硬失败。对应证券必须由
`domain.details.missing_security_ids` 产生 `SECURITY_NOT_COVERED`，不得把空分片
解释为完整的空行情。

日历研究边界是配置的 `[start_date, end_date]`；额外
`(end_date, end_date + 10 天]` 只供最后观测的可用日和
`next_trading_day(end_date)` 推导，不得成为新的研究日期。行情返回
`PriceBarSeries`，分别报告证券未覆盖、交易日缺 bar、停牌状态未知和证据缺失。
利率陈旧度只数开区间 `(available_at, as_of)` 内的交易日。详细验收见
`docs/testing/stage-a-parquet-foundation.tdd.md`。

2026-09-24 的真实端点探针确认：中债 `historyQuery` 接受 GET 查询参数并返回
HTML 表格；适配器按自然年切片（单次不跨年）解析 `日期` 和 `10年`，记录
endpoint、完整参数指纹和响应行证据。若官方端点后续改变协议，必须升级
adapter/source descriptor，不得静默切换为第三方封装。

## 阶段 B 样本契约

### 财务报表

全量同步前必须从真实样本确认：

- `security_id`、`period_end`、合并/母公司范围、报告类型；
- 可追溯的公告日及来源；
- `first_observed_at`、`provider_revision_sequence`；
- 原始数值、币种、单位/缩放、证据和行哈希。

`available_at` 不能用抓取时间替代。没有可信公告日的记录不进入 PIT。
免费源仅提供最新重述值时，写
`financials:latest_restated_only`，并禁止用于早于首次观察日的历史回测。

2026-09-25 完成的阶段 B1.1 冻结九个固定样本的最小字段矩阵。规范化采用
长表，每条记录包含公共审计字段及一个 `item_code/value/value_unit`：

- `statement_type`、`period_end`、`report_type`、`report_period_kind`；
- `statement_scope` 与 `statement_scope_evidence_ref`；非 `UNKNOWN` 声明必须
  有逐样本法定原文证据，不得根据 `reportType` 或科目猜测；
- `announcement_date`、`candidate_announcement_available_date`、
  `first_observed_at`、`available_at`；
- `source_update_date`、`provider_revision_sequence`、`revision_status`；
- `source_interface`、`source_endpoint`、`source_row_hash`、`evidence_ref`；
- `currency`、`source_unit_scale`、`value_status`、`blocking_reasons`。

对于 `financials:latest_restated_only`，候选公告可用日只用于审计，实际
`available_at=first_observed_at`。`UPDATE_DATE` 不是修订顺序。B1.1 记录统一
`research_eligible=false`，不得由同步 CLI 发布。字段矩阵和样本证据见
`docs/data-pilots/2026-09-25-financial-statements-b1.md`。

B1.1 的向前观察链只生成本地 `observation_revision_sequence`：相同经济键下
连续相同内容折叠，内容变化或恢复形成新片段，同一观察时点的冲突内容拒绝。
该序号不得写入 `provider_revision_sequence`，也不能恢复首次观察前的修订。

### 分红

保存公告、实施、登记、除权和支付日期、税前每股现金、股本基数及来源。
`is_ordinary`、`is_paid` 使用三态：`TRUE/FALSE/UNKNOWN`。任何必要状态、
支付日或总额未知时，未来 `D` 为 `UNKNOWN`，不能聚合为零。

阶段 B2 已用浦发银行 2022 年度现金分红冻结一个固定样本，并对法定实施
公告、AKShare 与 Baostock 做三方交叉核验。规范化至少保留：

- `announcement_date`、`record_date`、`ex_date`、`scheduled_pay_date`；
- `cash_per_share_before_tax`、`eligible_share_count`、`gross_cash_amount`；
- 每个日期与金额的来源、`source_row_hash`、`evidence_ref` 和 `available_at`；
- `is_ordinary`、`is_paid` 及其证据状态，不从方案描述或日历推断为真。

实施公告中的支付日是计划/实施日期，不自动等于“支付已完成”。“普通股现金
分红”也不自动等于领域规则中的“普通而非特别股息”。B2 的初始状态因而
保持 `is_ordinary=UNKNOWN`、`is_paid=UNKNOWN`。后续定期报告明确写明方案
已实施完毕后，另建从该报告公告日下一交易日起可见的修订，才将
`is_paid=TRUE`；不得回填至预定支付日。普通性和窗口覆盖仍未知，所以两个
修订均为 `research_eligible=false`。详情与阻塞项见
`docs/data-pilots/2026-09-25-dividends-b2.md`。

### 回购

保存公告日、实际执行日、实际执行金额、计划金额和累计进度的独立列。
公告日不能回填实际执行日；累计进度不能直接当单次执行额。

`cancellation_status` 使用
`VERIFIED_TRUE/VERIFIED_FALSE/UNKNOWN`。AKShare 未经法定公告核验时一律
为 `UNKNOWN`。巨潮核验和完整自然年覆盖上线前，
`latest_calendar_year_coverage_complete=false`，因此 `B_buyback` 保持
`UNKNOWN`。

阶段 B3 已用贵州茅台 2024 年首次披露的注销式回购计划冻结七个累计进度
观测。事件化规则为：同一计划按截止日排序，折叠同值重复证据，拒绝同日
冲突、累计倒退及金额/股数单边变化，再以相邻累计值之差生成区间增量。
每个增量必须保留：

- `(interval_start_exclusive, interval_end_inclusive)`，且
  `executed_on=null`；
- `amount_delta`、`shares_delta`、两端累计值及两端法定证据；
- 进度公告独立的 `available_at`，不得使用计划开始日或公告日冒充执行日；
- 注销核验的独立证据和独立 `available_at`。

年报已经核实最终回购股份完成注销，但未披露精确注销日期；七个区间也不能
提供逐日实际执行日，且样本未证明同一证券完整自然年的全部计划覆盖。因此
B3 仍为 `research_eligible=false`，不得进入 `B_actual_365d`。详情见
`docs/data-pilots/2026-09-25-buybacks-b3.md`。

## 质量与发布

阻断发布：

- schema、主键、代码或日期不合法；
- 数值出现 NaN/Inf，单位/币种缺失；
- 预期分片缺失或文件哈希不匹配；
- 必需域失败或覆盖率低于版本化配置阈值；
- resume 的 config、schema、adapter/source descriptor 与 partial meta 不同。

可发布但必须标记：

- OHLC 逻辑异常；
- 跨源抽样差异；
- 停牌或退市覆盖异常；
- 财报恒等式超出容差。

meta 对每个域记录状态、行数、文件哈希、逻辑内容哈希、质量结果和错误
摘要。只有所有请求且必需的域都是 `complete`，才可发布 snapshot。
