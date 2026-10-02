# 财报字段矩阵与不可变样本 B1.1（2026-09-25）

## 结论

九个固定真实样本已经形成确定性字段矩阵、内容哈希固定的最小原始夹具和
纯规范化实现，共输出 52 条长表科目记录。覆盖三类样本：当前上市银行
`SH600000`、退市通用公司 `SH600001`、当前上市非金融通用公司
`SH600519`，每类均包含资产负债表、利润表和现金流量表。

九个样本现在都有逐表法定范围证据：浦发银行和贵州茅台三表均核对为
`CONSOLIDATED`；邯郸钢铁三季报只列公司报表，核对为 `PARENT`。
所有样本仍为 `research_eligible=false`：免费接口只暴露当前最新重述值，
没有供应商声明的修订序号，不能安全回填到原公告时点。

## 采集证据

- 采集时点：`2026-09-25T04:09:31Z`；
- AKShare：`1.18.74`；
- 未使用 Tushare；
- 当前证券：`SH600000`、`SH600519`；退市证券：`SH600001`；
- 夹具：
  `tests/fixtures/financials/eastmoney-financial-statement-samples-v1.json`；
- 夹具 SHA-256：
  `9850b85e2cf9f51b2b5180892b23e2f905655ad8eccea3084ed4eb3e07f76f63`。

样本只保留契约所需的最小投影，数值按十进制文本保存。原始 DataFrame
行列规模仍写入夹具，用于接口漂移审计。

| 变体 | 机构类型 | 证券 | 报表 | 实测行×列 | 投影科目数 |
|---|---|---|---|---:|---:|
| 当前 | 银行 | SH600000 | 资产负债表 | 105×221 | 5 |
| 当前 | 银行 | SH600000 | 利润表 | 108×170 | 4 |
| 当前 | 银行 | SH600000 | 现金流量表 | 92×316 | 4 |
| 退市 | 通用 | SH600001 | 资产负债表 | 44×319 | 5 |
| 退市 | 通用 | SH600001 | 利润表 | 44×203 | 5 |
| 退市 | 通用 | SH600001 | 现金流量表 | 36×254 | 4 |
| 当前 | 通用 | SH600519 | 资产负债表 | 103×319 | 15 |
| 当前 | 通用 | SH600519 | 利润表 | 103×203 | 5 |
| 当前 | 通用 | SH600519 | 现金流量表 | 99×254 | 5 |

## 报表范围证据

范围声明不能根据接口名、`REPORT_TYPE` 或科目集合猜测。九个样本分别用
以下法定原文逐表核对。

贵州茅台范围证据为巨潮资讯《贵州茅台酒股份有限公司 2025 年年度报告》：

- 原文：`https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF`；
- PDF SHA-256：
  `474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288`；
- 合并资产负债表、合并利润表、合并现金流量表分别在 PDF 第 56、61、64 页；
- 母公司三表分别在第 59、63、66 页；
- 固定样本数值与对应合并报表一致，并与母公司报表值有可辨差异。

浦发银行范围证据为发行人官网《上海浦东发展银行股份有限公司 2025 年
年度报告》：

- 原文：
  `https://news.spdb.com.cn/investor_relation/periodic_report/202603/P020260330690876003415.pdf`；
- PDF SHA-256：
  `e4d1cff0461c0ef24d26551ca68e31ad323a1b3eadd8a3c03f00feada364de22`；
- PDF 第 157、160、163 页分别为资产负债表、利润表和现金流量表，均并列
  “本集团/本行”栏；固定样本总资产、营业收入、净利润和现金流量等数值
  均与“本集团”栏一致，因此为 `CONSOLIDATED`。

邯郸钢铁范围证据为巨潮资讯《邯郸钢铁股份有限公司 2009 年第三季度报告》：

- 原文：`https://static.cninfo.com.cn/finalpage/2009-10-31/57234723.PDF`；
- PDF SHA-256：
  `844360d273aa95625241553544e1bf03b57062e1a261b4c91659ed23ed7b80e8`；
- PDF 第 7、9、10 页分别只列由邯郸钢铁股份有限公司编制的资产负债表、
  利润表和现金流量表，没有集团/合并栏，固定样本与其一致，因此为
  `PARENT`；
- 前一期经审计年报也明确审计“公司资产负债表、公司利润表、公司现金流量
  表”，并只列公司三表（PDF 第 23、24、26、27 页）。辅助原文为
  `https://static.cninfo.com.cn/finalpage/2009-03-31/50765415.PDF`，SHA-256
  为 `efbe692bc773778f953dd8cf54dd14acdf3ab53f754b66eb716760d2074c56f6`。

每个固定样本均写入 `statement_scope` 和逐页
`statement_scope_evidence_ref`。这些结论不得自动推广到其他证券、期间或
接口。

## 公共字段契约

| 原始字段 | 规范语义 | 规则 |
|---|---|---|
| `SECUCODE` / `SECURITY_CODE` | `security_id` / 原始代码 | 两者必须一致；规范为 `sh.600000` 形式 |
| `ORG_CODE` / `ORG_TYPE` | 组织标识及矩阵分派 | 只放行已冻结的 `银行`、`通用` 样本组合 |
| `REPORT_DATE` | `period_end` | 必须与年报/一季报/中报/三季报期末一致 |
| `REPORT_TYPE` | 报告类型 | 仅表示报告期间，不用于推断合并范围 |
| `NOTICE_DATE` | 公告日 | 保存公告日及下一交易日候选可用日 |
| `UPDATE_DATE` | 来源更新日 | 仅审计，不当作修订顺序 |
| `CURRENCY` | 币种 | 只接受三个 ASCII 大写字母；样本为 `CNY` |
| 首次观察时点 | `first_observed_at` / `available_at` | 最新重述值只能从首次观察时点起可见 |
| 法定原文页 | `statement_scope_evidence_ref` | 非 `UNKNOWN` 范围声明必须提供 |

`available_at` 不使用原始公告日回填。规范行同时保存
`candidate_announcement_available_date`，但由于完整修订链未知，实际
`available_at=first_observed_at`。这可以防止把后来更新的年报值错误地放回
最初公告后的交易日使用。

## 科目矩阵

当前银行与退市通用样本保留原 B1 最小矩阵：资产负债表 5 项、利润表
4/5 项、现金流量表 4 项。当前上市通用样本扩展为：

- 资产负债表：`MONETARYFUNDS`、`TRADE_FINASSET`、
  `OTHER_CURRENT_ASSET`、`NONCURRENT_ASSET_1YEAR`、`SHORT_LOAN`、
  `NONCURRENT_LIAB_1YEAR`、`SHORT_BOND_PAYABLE`、`LONG_LOAN`、
  `BOND_PAYABLE`、`LEASE_LIAB`，以及资产、负债、归母权益、少数股东权益、
  总权益五个合计项；
- 利润表：`TOTAL_OPERATE_INCOME`、`OPERATE_INCOME`、
  `PARENT_NETPROFIT`、`NETPROFIT`、`BASIC_EPS`；
- 现金流量表：`NETCASH_OPERATE`、`CONSTRUCT_LONG_ASSET`、
  `NETCASH_INVEST`、`NETCASH_FINANCE`、`CCE_ADD`。

这些字段仍是原始科目，不代表已经冻结 RULE_SPEC 中现金、金融资产、
有息负债、OCF、Capex 或 FCF 的聚合公式。金额单位为原始 `CURRENCY`，
缩放为 `1`；`BASIC_EPS` 单位为币种/股。空值写 null 并标记
`value_status=UNKNOWN`，不得写成零。

## 向前观察修订链

样本模块新增了保守的跨批次观察链原型：

- 经济键包含来源接口、证券、报表类型、期末日和报表范围；
- 时间统一到 UTC 秒；同一时点出现不同内容哈希时拒绝；
- 连续相同内容合并为同一观察片段；内容先变化再恢复时创建新片段；
- 本地序号只写 `observation_revision_sequence`，绝不冒充
  `provider_revision_sequence`；
- 结果状态为 `financials:observed_forward_only`，只能描述开始采集后的变化。

它不能恢复首次采集之前的历史修订，也没有改变固定样本的
`financials:latest_restated_only` 状态。

## 实现边界

`turtle_quant/adapters/financial_statement_samples.py`：

- 没有网络抓取客户端，不导入同步 runner；
- 不发布 complete snapshot，不接入研究 Reader；
- 每个科目输出一条长表记录；
- 固定 `research_eligible=false`；
- 九个已有范围证据的样本只保留
  `provider_revision_sequence_unavailable`；
- 新证券、期间或接口如果没有逐表法定证据，仍必须保持
  `statement_scope=UNKNOWN` 并带 `statement_scope_unknown`。

## 后续门槛

财报生产接入前仍须完成：

1. 对更多上市通用公司、报告期和修订场景做真实样本验收，避免把单证券矩阵
   当作全市场契约；
2. 将周期性原始快照、观察链和质量门槛接入 staging → immutable snapshot，
   并定义首次上线前历史修订缺口如何处理；
3. 冻结 RULE_SPEC 所需的现金、金融资产、有息负债、归母权益、少数股东
   权益、OCF、Capex 等聚合映射及未知值传播；
4. 明确研究层接受供应商修订序号，还是接受仅向前可观测的本地序号；该语义
   会影响历史可复现性，不能由适配器自行决定；
5. 验收后按变更流程修改 `RULE_SPEC.md` 的 `ready_when`，再实现生产适配器
   和 Parquet PIT Reader。

2026-10-01 后续[法定 PDF 修订链探针](2026-10-01-financial-revision-000637.md)
固定了深市主板茂化实华 2025 年报原版、更正版、更正公告、重列报表与审计专项说明；
同一合并经营现金流科目在 2026-08-06 更正时由正转负，且更正版封面仍写原版
日期。该样本证明一条具体修订可追溯，不解除本节所列的全历史完整性阻塞。
