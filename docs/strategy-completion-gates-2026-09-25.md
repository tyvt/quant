# 策略完备确认门槛（2026-09-25）

## 2026-09-25 阶段 A 可验证基线

- 阶段 A 已有不可变证券、日历、原始行情、复权因子和中债利率快照；
  `RULE_SPEC v1.2.0` 的点时 Foundation Reader 已实现并通过真实快照只读验收，
  但仍不授权真实研究。
- B1.1 九个财报样本共 52 条科目，三表范围均有逐页法定证据；唯一共同阻塞
  是供应商没有历史修订序号，最新重述值不能回填原公告日。
- B2 分红的日期、每股金额、股本和总额已三方对账；实施公告后的支付状态为
  UNKNOWN，后续发行人报告从自身可用日起将其核实为 TRUE。普通/特别分类
  和全窗口覆盖仍未冻结。
- B3 回购的七个累计观测已经事件化并核实最终注销，但只能得到执行区间，
  不能得到 RULE_SPEC 要求的精确执行日；完整自然年全部计划覆盖也未证明。
- 当前全量回归为 162 项测试全部通过，源码分支覆盖率 81%，Foundation Reader
  自身分支覆盖率 80%。阶段 A Reader 已完成点时读取、结构化覆盖问题、过滤下推、
  撤销拒绝和 RunManifest 集成；未就绪财务 Reader 仍不访问快照且显式失败。
  所有 B 阶段夹具仍为 `research_eligible=false`。

## 已批准的 v1.2.0 提案摘要

以下主题及 Reader 细节已经合并并批准为 `v1.2.0-20260929-02`。本节仅用于
说明决策背景；如摘要与精确提案有差异，以已批准的精确提案全文为准。

### 1. 财报修订语义

推荐冻结为：

1. 法定原始报告及更正公告按各自保守 `available_at` 进入历史 PIT；
2. 免费接口的 `latest_restated_only` 值只能从 `first_observed_at` 起使用；
3. 本地 `observation_revision_sequence` 只描述开始采集后的变化，不冒充
   `provider_revision_sequence`；
4. 首次观察前无法恢复的修订保持 UNKNOWN，不以当前值回填；
5. 长历史回测若要求完整财报 PIT，必须取得有序修订源或逐份解析法定原文。

该方案允许诚实的向前研究，不会伪造历史；代价是免费源不能立即支持完整
长历史财报回测。

### 2. 普通现金股息分类与支付完成

推荐冻结为：

1. 明确属于年度利润分配的普通股基础现金股息，且文件未标注“特别、额外、
   一次性、清算、资本返还”等性质时，记为 `is_ordinary=TRUE`；
2. 明确的特别/额外/一次性部分记为 FALSE；混合方案能拆金额则拆事件，不能
   拆则 UNKNOWN；
3. 中期股息只有在法定文件明确属于常规分配政策时才为 TRUE，否则 UNKNOWN；
4. 实施公告中的预定支付日不自动证明完成；明确的完成公告或后续定期报告
   才能从自身 `available_at` 起令 `is_paid=TRUE`；更正或取消形成新修订；
5. 未证明查询窗口事件覆盖完整时，`D` 仍为 UNKNOWN。

### 3. 回购区间归属

推荐冻结为：区间累计差分只作为审计证据，不把区间首日、末日或公告日伪装
成 `executed_on`。主路径 `B_actual_365d` 和持续性判断必须使用逐日/逐笔
执行数据；缺少精确日期时保持 UNKNOWN。可以另报区间上下界，但不得代入
GG。

若批准“统一归到区间末日”等近似法，必须视为改变时间语义的规则变更，并
单独给出边界算例；本提案不推荐该做法。

### 4. 拆分 Parquet PIT Reader 的 ready_when

推荐将当前单一的 `turtle_quant/pit/parquet.py` 门槛拆成：

- `pit/parquet_foundation.py`：`ready`，只读取已发布且未撤销的阶段 A 域，
  实现证券池、交易日历、原始行情、复权因子和利率的点时读取；
- `pit/parquet_financial_statements.py`、`pit/parquet_dividends.py`、
  `pit/parquet_buybacks.py`：分别 `not_ready`，各自满足完整修订链、分红窗口覆盖
  或回购逐日执行覆盖后可独立转 ready；
- `pit/parquet_finance.py`：`not_ready aggregate facade`，三个专用模块全部 ready
  前不允许部分开放；
- Reader 必须校验 complete meta、文件 SHA-256、domain revocation、schema/
  normalization version 和 `available_at <= as_of`。

该拆分不授权真实选股或回测，只解除阶段 A Reader 被阶段 B 语义整体拖住的
工程阻塞。

2026-09-29 的实现前审计另发现多快照证券池身份、交易日历协议、强类型输出、
日行情当日可用时点、利率陈旧阈值和累积复权因子转换需要冻结；后续审阅又明确
了研究覆盖与成交日缓冲、结构化覆盖问题、因子可见集和独立财务域门槛。全部
精确语义已收入 `rule-proposals/v1.2.0-exact-amendment.md`，推荐契约与验收矩阵
见 `stage-a-parquet-reader-spec-2026-09-29.md`。

## v1.3.0 已冻结的策略层

项目负责人已于 2026-09-29 批准 `v1.3.0-20260929-02`，以下原策略缺口已冻结：

- `C/A/B_debt/E/N/OCF/Capex/O` 的逐行业科目映射与归属桥接；
- `premise/` 的通用企业硬门、评分规则、阈值、权重和 fixture；
- `market/position.py` 的行情 Profile、输出契约和历史 bar fixture；
- 证券池、市值/流动性阈值、信号时间、Top-N、权重、调仓频率和卖出规则；
- 成交价、手续费、印花税、滑点、T+1、停牌、涨跌停、退市、分红和拆并股的
  组合模拟语义；
- 基准、绩效指标和幸存者偏差/前视偏差验收。

这些内容现已纳入 `RULE_SPEC v1.3.0`，允许实现纯逻辑和合成 fixture；实现层仍
不得自行修改任何参数或把生产数据缺口降级为默认值。

批准全文和审计锚点见 `rule-proposals/v1.3.0-general-fcf-strategy.md`。
v1.3.1 已将 H00985 基准 Reader 在已验收快照覆盖内转为 `ready`；财务报表、
分红、回购、行业、历史股本、证券状态、交易能力、公司行为及历史费率九域
仍为 `not_ready`，真实运行继续被阻断。

## 本次确认的精确影响

项目负责人已批准 v1.2.0、v1.3.0 与 v1.3.1 精确提案全文，`RULE_SPEC`
已升级到 v1.3.1。
阶段 A Parquet Foundation Reader 与点时验收已经完成。v1.3.0 纯逻辑和合成
黄金 fixture 已推进至 2026-09-30 的 264 项回归通过；详细验收与保守阻断路径见
`testing/v13-strategy-golden.tdd.md`。真实运行的数据阻塞仍是法定财报历史修订链、分红窗口、
回购逐日执行、行业、历史股本、证券状态、交易能力、公司行为和历史费率。
H00985 全历史快照与 Reader 已完成技术验收并按 v1.3.1 限定转 ready；
跨域清单和其他九域仍待生产验收，不构成真实回测授权。

批准记录、逐条规则文本、模块状态和迁移结论分别见
`rule-proposals/v1.2.0-exact-amendment.md` 与
`rule-proposals/v1.3.0-general-fcf-strategy.md` 与
`rule-proposals/v1.3.1-benchmark-ready.md`。
