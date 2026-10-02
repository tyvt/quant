# 贝因美 2022 核心财务科目：限定样本诊断（diagnostic_only=true）

## 本报告不宣称

- 这是单证券、单 as_of、限定输出范围的诊断，不是完整真实 PIT 策略运行。
- 这不是官方 Top-N、可发布回测或真实选股结果，不生成排名、目标权重、订单、持仓或净值。
- UNKNOWN 未作为数值参与计算，未填零、未跨证券借用、未插值或前向填充。
- 原文版本对照可以展示历史观察值；这些值不自动成为指定 as_of 的可用规则输入。
- 本报告不构成投资建议，不对外发布原始数据或报告，不用于商业用途。

## 冻结范围

- 证券：`sz.002570`；`as_of=2026-09-30`（请求历史收盘截止）。
- 复核日：`2026-10-02`；经济期间：`2022-01-01 — 2022-12-31`。
- 输出范围：`core_field_version_comparison, gross_profit_and_margin_arithmetic, financial_input_gaps, premise_unknown_propagation`。
- `diagnostic_only=true`、`official_selection=false`；生产 Reader 与真实编排状态不变。

## 时点假设

- 处理：`UNKNOWN_UNLESS_VERIFIED`；`available_at=null`。
- 目录日期/时刻不等于最早公众可用；本次不采用当日或下一交易日可用假设。抓取晚于 as_of 不倒填。
- 目录时刻逐文件列于末节，供复核，不作为已核实的最早公开时点。
- 接纳到 PIT 规则中的真实数值观察为 **0**；原文对照数值仍完整展示。

## 原文观察与必要输入

| 字段 | 经济日期 | 版本 | 原文观察值 | 指定 as_of 输入 | 物理页证据 |
|---|---|---|---|---|---|
| 一、营业总收入 | 2022-12-31 | `original_annual` | 2654624655.97 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:78` |
| 其中：营业成本 | 2022-12-31 | `original_annual` | 1503441070.62 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:78` |
| 投资性房地产 | 2022-12-31 | `original_annual` | 302928100.09 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:74` |
| 固定资产 | 2022-12-31 | `original_annual` | 872526576.41 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:74` |
| 无形资产 | 2022-12-31 | `original_annual` | 159161422.48 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:74` |
| 其他非流动金融资产 | 2022-12-31 | `original_annual` | 74631520.32 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:74` |
| 其他非流动资产 | 2022-12-31 | `original_annual` | 71002840.72 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:75` |
| 其他应付款 | 2022-12-31 | `original_annual` | 400069089.61 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:75` |
| 其他非流动负债 | 2022-12-31 | `original_annual` | 空白（非零） | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:76` |
| 经营活动产生的现金流量净额 | 2022-12-31 | `original_annual` | 377416659.60 | UNKNOWN | `pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:82` |
| 一、营业总收入 | 2022-12-31 | `first_corrected_annual` | 2509171932.67 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:78` |
| 其中：营业成本 | 2022-12-31 | `first_corrected_annual` | 1357988347.32 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:78` |
| 投资性房地产 | 2022-12-31 | `first_corrected_annual` | 302928100.09 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74` |
| 固定资产 | 2022-12-31 | `first_corrected_annual` | 872526576.41 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74` |
| 无形资产 | 2022-12-31 | `first_corrected_annual` | 159161422.48 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74` |
| 其他非流动金融资产 | 2022-12-31 | `first_corrected_annual` | 74631520.32 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74` |
| 其他非流动资产 | 2022-12-31 | `first_corrected_annual` | 71002840.72 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:75` |
| 其他应付款 | 2022-12-31 | `first_corrected_annual` | 400069089.61 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:75` |
| 其他非流动负债 | 2022-12-31 | `first_corrected_annual` | 空白（非零） | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:76` |
| 经营活动产生的现金流量净额 | 2022-12-31 | `first_corrected_annual` | 377416659.60 | UNKNOWN | `pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:82` |
| 一、营业总收入 | 2022-12-31 | `second_corrected_annual` | 2509171932.67 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:78` |
| 其中：营业成本 | 2022-12-31 | `second_corrected_annual` | 1357988347.32 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:78` |
| 投资性房地产 | 2022-12-31 | `second_corrected_annual` | 42915188.04 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74` |
| 固定资产 | 2022-12-31 | `second_corrected_annual` | 1131862577.55 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74` |
| 无形资产 | 2022-12-31 | `second_corrected_annual` | 159838333.39 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74` |
| 其他非流动金融资产 | 2022-12-31 | `second_corrected_annual` | 56271520.32 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74` |
| 其他非流动资产 | 2022-12-31 | `second_corrected_annual` | 89362840.72 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:75` |
| 其他应付款 | 2022-12-31 | `second_corrected_annual` | 382069089.61 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:75` |
| 其他非流动负债 | 2022-12-31 | `second_corrected_annual` | 18000000.00 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:76` |
| 经营活动产生的现金流量净额 | 2022-12-31 | `second_corrected_annual` | 377416659.60 | UNKNOWN | `pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:82` |

## 已知部分的算术 / 纯逻辑缺口传播

以下算术只针对上述原文观察，不作为已证实的历史 PIT 结论。纯逻辑门控若全部 UNKNOWN，表示输入不满足，而非对公司质量的完整判断。

```json
{
  "amended_whole_statement_audit_status": "UNKNOWN",
  "audit_evidence_refs": [
    "pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:70",
    "pdf:sha256:1972c8d10734bb8dea43a45dd92ec3cd37273eab9e10859620b0e2c2919fa6aa:physical-page:3",
    "pdf:sha256:8ac7933cb5c4b1678de41562ded55bff05078cf275e9e7d97bdf0b62dc70bdb9:physical-page:3",
    "pdf:sha256:8ac7933cb5c4b1678de41562ded55bff05078cf275e9e7d97bdf0b62dc70bdb9:physical-page:4"
  ],
  "audit_warning": "专项审核/鉴证不是整份重审；第二轮标题/对象为 2022—2023，用途与页眉出现 2024，不能静默统一。此缺口不阻止本报告原文对照。",
  "first_cost_delta_cny": "-145452723.30",
  "first_revenue_delta_cny": "-145452723.30",
  "gross_profit_difference_cny": "0.00",
  "latest_visible_version": null,
  "premise_execution": {
    "admitted_inputs": {
      "annual_observations": [],
      "as_of": "2026-09-30",
      "cash": null,
      "going_concern_uncertainty": null,
      "industry_profile": null,
      "interest_bearing_debt": null,
      "latest_audit_unmodified": null,
      "latest_equity": null,
      "liquid_assets": null,
      "quality_weights": {
        "balance_score": "0.15",
        "cash_conversion_score": "0.25",
        "fcf_stability_score": "0.25",
        "roe_score": "0.35"
      },
      "statements_comparable": null
    },
    "admitted_real_numeric_observation_count": 0,
    "execution_scope": "strict_unknown_propagation_only_not_complete_company_assessment",
    "hard_gates": [
      {
        "evidence_refs": [],
        "kind": "HARD_GATE",
        "missing_fields": [
          "industry_profile"
        ],
        "notes": [],
        "rule_id": "premise.profile_supported",
        "status": "UNKNOWN",
        "value": null
      },
      {
        "evidence_refs": [],
        "kind": "HARD_GATE",
        "missing_fields": [
          "statements_comparable",
          "latest_audit_unmodified",
          "going_concern_uncertainty"
        ],
        "notes": [],
        "rule_id": "premise.statement_integrity",
        "status": "UNKNOWN",
        "value": null
      },
      {
        "evidence_refs": [],
        "kind": "HARD_GATE",
        "missing_fields": [
          "latest_equity"
        ],
        "notes": [],
        "rule_id": "premise.positive_equity",
        "status": "UNKNOWN",
        "value": null
      },
      {
        "evidence_refs": [],
        "kind": "HARD_GATE",
        "missing_fields": [
          "six_consecutive_year_end_equities"
        ],
        "notes": [],
        "rule_id": "premise.roe_5y",
        "status": "UNKNOWN",
        "value": null
      },
      {
        "evidence_refs": [],
        "kind": "HARD_GATE",
        "missing_fields": [
          "five_consecutive_annual_fcf"
        ],
        "notes": [],
        "rule_id": "premise.fcf_consistency",
        "status": "UNKNOWN",
        "value": null
      },
      {
        "evidence_refs": [],
        "kind": "HARD_GATE",
        "missing_fields": [
          "cash",
          "liquid_assets",
          "interest_bearing_debt",
          "f_norm"
        ],
        "notes": [],
        "rule_id": "premise.leverage",
        "status": "UNKNOWN",
        "value": null
      }
    ],
    "quality_score": null,
    "reason": "历史可用时点未证实，且六个年末权益/五年 FCF/行业/审计等不完整；不借用虚拟日期或默认零调用估值。",
    "score_coverage": "0",
    "valuation_execution": "NOT_EXECUTED_UNKNOWN_DEPENDENCIES"
  },
  "reclassifications": [
    {
      "evidence_refs": [
        "pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74",
        "pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74",
        "pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74",
        "pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74",
        "pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74",
        "pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74"
      ],
      "fields": [
        "investment_property",
        "fixed_assets",
        "intangible_assets"
      ],
      "second_correction_deltas_cny": [
        "-260012912.05",
        "259336001.14",
        "676910.91"
      ],
      "sum_cny": "0.00"
    },
    {
      "evidence_refs": [
        "pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:74",
        "pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:75",
        "pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:74",
        "pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:75"
      ],
      "fields": [
        "other_noncurrent_financial_assets",
        "other_noncurrent_assets"
      ],
      "second_correction_deltas_cny": [
        "-18360000.00",
        "18360000.00"
      ],
      "sum_cny": "0.00"
    }
  ],
  "second_special_report_period": "UNKNOWN_YEAR_SCOPE_CONFLICT",
  "statement_scope": "CONSOLIDATED",
  "unit": "CNY",
  "version_arithmetic": [
    {
      "evidence_refs": [
        "pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:78",
        "pdf:sha256:00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc:physical-page:78"
      ],
      "gross_margin_pct": "43.36521107649237336560576690",
      "gross_profit_cny": "1151183585.35",
      "operating_cost_cny": "1503441070.62",
      "revenue_cny": "2654624655.97",
      "semantics": "所选版本的原文算术，不是历史可用盈利评分或未来增长判断。",
      "version": "original_annual"
    },
    {
      "evidence_refs": [
        "pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:78",
        "pdf:sha256:d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e:physical-page:78"
      ],
      "gross_margin_pct": "45.87902368750913244687486057",
      "gross_profit_cny": "1151183585.35",
      "operating_cost_cny": "1357988347.32",
      "revenue_cny": "2509171932.67",
      "semantics": "所选版本的原文算术，不是历史可用盈利评分或未来增长判断。",
      "version": "first_corrected_annual"
    },
    {
      "evidence_refs": [
        "pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:78",
        "pdf:sha256:21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410:physical-page:78"
      ],
      "gross_margin_pct": "45.87902368750913244687486057",
      "gross_profit_cny": "1151183585.35",
      "operating_cost_cny": "1357988347.32",
      "revenue_cny": "2509171932.67",
      "semantics": "所选版本的原文算术，不是历史可用盈利评分或未来增长判断。",
      "version": "second_corrected_annual"
    }
  ],
  "version_warning": "毛利差零不证明所有财报/FCF 输入不变；收入基数改变，算术毛利率也变。旧空白负债保留 null。"
}
```

## UNKNOWN 与未执行项

| 字段/规则 | 缺少的依赖 | 原因 |
|---|---|---|
| `FCF=UNKNOWN` | `OCF_pit, capex_pit, lease_cash, attributable_equity, minority_interest` | 2022 个案原文数值不等于完整归属 FCF 输入；不把租赁现金/少数股东权益缺失当零。 |
| `premise.roe_5y=UNKNOWN` | `six_consecutive_equities, five_parent_profits, available_at` | 单报告期不能代替六个连续年末权益与五年净利润。 |
| `absolute_valuation=UNKNOWN` | `five_annual_FCF, TTM_FCF, P, S, C, A, IB` | 未调用要求完整参数的估值函数，不用默认零制造可计算性。 |
| `latest_visible_version=UNKNOWN` | `historical_availability, complete_revisions_and_withdrawals` | 仅比较已固定文件，不选定声称截至 as_of 最新的有效财报。 |

整份更正后审计、完整窗口、逐日登记/流水等缺口按对应规则保留；不将它们作为查看原文和版本差额的通用前置条件。

## 证据与时点逐文件绑定

### original_annual（公告 1216702448）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2023-04-29/1216702448.PDF)；本地 bytes：`storage/pilots/financial-002570-2022-recorrection-2026-10-01/original_annual-1216702448.pdf`。
- SHA-256：`00c181533558cb7f4dac647d25a2d7d92b8aaafcb5f495e1f6a08582904558fc`；物理页码：`[70, 74, 75, 76, 78, 82]` / 全部 188 页。
- 目录 `announcementTime`：`2023-04-29T00:00:00+08:00`（北京时间；原始毫秒 `1682697600000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### first_corrected_annual（公告 1219043674）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2024-01-31/1219043674.PDF)；本地 bytes：`storage/pilots/financial-002570-2022-recorrection-2026-10-01/first_corrected_annual-1219043674.pdf`。
- SHA-256：`d84185d150bc513af25a06921ce617fd1d311d0819d47cfad02b3096458bc76e`；物理页码：`[70, 74, 75, 76, 78, 82]` / 全部 188 页。
- 目录 `announcementTime`：`2024-01-31T00:00:00+08:00`（北京时间；原始毫秒 `1706630400000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### second_corrected_annual（公告 1223388226）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-04-29/1223388226.PDF)；本地 bytes：`storage/pilots/financial-002570-2022-recorrection-2026-10-01/second_corrected_annual-1223388226.pdf`。
- SHA-256：`21fbe574b039f6004558ef89aeaa787d5d89b51e7b7998862b56c08ffee84410`；物理页码：`[70, 74, 75, 76, 78, 82]` / 全部 188 页。
- 目录 `announcementTime`：`2025-04-29T00:00:00+08:00`（北京时间；原始毫秒 `1745856000000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### first_correction_special_review（公告 1219043661）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2024-01-31/1219043661.PDF)；本地 bytes：`storage/pilots/financial-002570-2022-recorrection-2026-10-01/first_correction_special_review-1219043661.pdf`。
- SHA-256：`1972c8d10734bb8dea43a45dd92ec3cd37273eab9e10859620b0e2c2919fa6aa`；物理页码：`[3, 4]` / 全部 8 页。
- 目录 `announcementTime`：`2024-01-31T00:00:00+08:00`（北京时间；原始毫秒 `1706630400000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### second_correction_special_review（公告 1223478760）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-05-07/1223478760.PDF)；本地 bytes：`storage/pilots/financial-002570-2022-recorrection-2026-10-01/second_correction_special_review-1223478760.pdf`。
- SHA-256：`8ac7933cb5c4b1678de41562ded55bff05078cf275e9e7d97bdf0b62dc70bdb9`；物理页码：`[3, 4]` / 全部 7 页。
- 目录 `announcementTime`：`2025-05-07T00:00:00+08:00`（北京时间；原始毫秒 `1746547200000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

## 本地使用与复现

公开可获取不等于任意授权；未宣称已有全市场、商业或分享许可。未发送询证。

- 规则：`v1.3.2`；SHA-256：`db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`。
- 完整输入清单、工具/纯逻辑代码哈希见同名 JSON 的 `manifest`。
- 逻辑内容 SHA-256：`5b12d0fb5d68c22e946281a327e04ef36fd77354ea449b38fd593ffffc572365`（canonical JSON，排除自身哈希字段）。
- 同一范围、输入、规则与代码得到相同内容哈希；不声称输入已完整、历史时点已证实或事实因确定性而可靠。
