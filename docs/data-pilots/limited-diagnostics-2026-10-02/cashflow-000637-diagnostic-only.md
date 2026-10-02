# 茂化实华 2025 现金流：限定样本诊断（diagnostic_only=true）

## 本报告不宣称

- 这是单证券、单 as_of、限定输出范围的诊断，不是完整真实 PIT 策略运行。
- 这不是官方 Top-N、可发布回测或真实选股结果，不生成排名、目标权重、订单、持仓或净值。
- UNKNOWN 未作为数值参与计算，未填零、未跨证券借用、未插值或前向填充。
- 原文版本对照可以展示历史观察值；这些值不自动成为指定 as_of 的可用规则输入。
- 本报告不构成投资建议，不对外发布原始数据或报告，不用于商业用途。

## 冻结范围

- 证券：`sz.000637`；`as_of=2026-09-30`（请求历史收盘截止）。
- 复核日：`2026-10-02`；经济期间：`2025-01-01 — 2025-12-31`。
- 输出范围：`cashflow_version_comparison, ocf_minus_capex_subtotal_not_fcf, financial_input_gaps, premise_unknown_propagation`。
- `diagnostic_only=true`、`official_selection=false`；生产 Reader 与真实编排状态不变。

## 时点假设

- 处理：`UNKNOWN_UNLESS_VERIFIED`；`available_at=null`。
- 目录日期/时刻不等于最早公众可用；本次不采用当日或下一交易日可用假设。抓取晚于 as_of 不倒填。
- 目录时刻逐文件列于末节，供复核，不作为已核实的最早公开时点。
- 接纳到 PIT 规则中的真实数值观察为 **0**；原文对照数值仍完整展示。

## 原文观察与必要输入

| 字段 | 经济日期 | 版本 | 原文观察值 | 指定 as_of 输入 | 物理页证据 |
|---|---|---|---|---|---|
| 销售商品、提供劳务收到的现金 | 2025-12-31 | `original_annual` | 3501901812.73 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101` |
| 销售商品、提供劳务收到的现金 | 2025-12-31 | `amended_annual` | 3379332135.68 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101` |
| 销售商品、提供劳务收到的现金 | 2025-12-31 | `september_bundle` | 3501901812.73 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 经营活动现金流入小计 | 2025-12-31 | `original_annual` | 3527194370.04 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101` |
| 经营活动现金流入小计 | 2025-12-31 | `amended_annual` | 3404624692.99 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101` |
| 经营活动现金流入小计 | 2025-12-31 | `september_bundle` | 3527194370.04 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 经营活动现金流出小计 | 2025-12-31 | `original_annual` | 3484208109.96 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101` |
| 经营活动现金流出小计 | 2025-12-31 | `amended_annual` | 3484208109.96 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101` |
| 经营活动现金流出小计 | 2025-12-31 | `september_bundle` | 3484208109.96 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 经营活动产生的现金流量净额 | 2025-12-31 | `original_annual` | 42986260.08 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101` |
| 经营活动产生的现金流量净额 | 2025-12-31 | `amended_annual` | -79583416.97 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101` |
| 经营活动产生的现金流量净额 | 2025-12-31 | `september_bundle` | 42986260.08 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 购建固定资产、无形资产和其他长期资产支付的现金 | 2025-12-31 | `original_annual` | 62173312.84 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101` |
| 购建固定资产、无形资产和其他长期资产支付的现金 | 2025-12-31 | `amended_annual` | 62173312.84 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101` |
| 购建固定资产、无形资产和其他长期资产支付的现金 | 2025-12-31 | `september_bundle` | 62173312.84 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 投资活动产生的现金流量净额 | 2025-12-31 | `original_annual` | 99170943.48 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101` |
| 投资活动产生的现金流量净额 | 2025-12-31 | `amended_annual` | 99170943.48 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101` |
| 投资活动产生的现金流量净额 | 2025-12-31 | `september_bundle` | 99170943.48 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 筹资活动现金流入小计 | 2025-12-31 | `original_annual` | 974280000.00 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102` |
| 筹资活动现金流入小计 | 2025-12-31 | `amended_annual` | 1096849677.05 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102` |
| 筹资活动现金流入小计 | 2025-12-31 | `september_bundle` | 974280000.00 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 筹资活动现金流出小计 | 2025-12-31 | `original_annual` | 1100823838.67 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102` |
| 筹资活动现金流出小计 | 2025-12-31 | `amended_annual` | 1100823838.67 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102` |
| 筹资活动现金流出小计 | 2025-12-31 | `september_bundle` | 1100823838.67 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 筹资活动产生的现金流量净额 | 2025-12-31 | `original_annual` | -126543838.67 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102` |
| 筹资活动产生的现金流量净额 | 2025-12-31 | `amended_annual` | -3974161.62 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102` |
| 筹资活动产生的现金流量净额 | 2025-12-31 | `september_bundle` | -126543838.67 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 现金及现金等价物净增加额 | 2025-12-31 | `original_annual` | 15613364.89 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102` |
| 现金及现金等价物净增加额 | 2025-12-31 | `amended_annual` | 15613364.89 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102` |
| 现金及现金等价物净增加额 | 2025-12-31 | `september_bundle` | 15613364.89 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 期初现金及现金等价物余额 | 2025-12-31 | `original_annual` | 180316289.42 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102` |
| 期初现金及现金等价物余额 | 2025-12-31 | `amended_annual` | 180316289.42 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102` |
| 期初现金及现金等价物余额 | 2025-12-31 | `september_bundle` | 180316289.42 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |
| 期末现金及现金等价物余额 | 2025-12-31 | `original_annual` | 195929654.31 | UNKNOWN | `pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102` |
| 期末现金及现金等价物余额 | 2025-12-31 | `amended_annual` | 195929654.31 | UNKNOWN | `pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102` |
| 期末现金及现金等价物余额 | 2025-12-31 | `september_bundle` | 195929654.31 | UNKNOWN | `pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12` |

## 已知部分的算术 / 纯逻辑缺口传播

以下算术只针对上述原文观察，不作为已证实的历史 PIT 结论。纯逻辑门控若全部 UNKNOWN，表示输入不满足，而非对公司质量的完整判断。

```json
{
  "comparisons": [
    {
      "amended": "3379332135.68",
      "amendment_delta": "-122569677.05",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "sales_cash_receipts",
      "label": "销售商品、提供劳务收到的现金",
      "original": "3501901812.73",
      "september": "3501901812.73",
      "september_matches_original": true
    },
    {
      "amended": "3404624692.99",
      "amendment_delta": "-122569677.05",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "operating_inflow",
      "label": "经营活动现金流入小计",
      "original": "3527194370.04",
      "september": "3527194370.04",
      "september_matches_original": true
    },
    {
      "amended": "3484208109.96",
      "amendment_delta": "0.00",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "operating_outflow",
      "label": "经营活动现金流出小计",
      "original": "3484208109.96",
      "september": "3484208109.96",
      "september_matches_original": true
    },
    {
      "amended": "-79583416.97",
      "amendment_delta": "-122569677.05",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "operating_net",
      "label": "经营活动产生的现金流量净额",
      "original": "42986260.08",
      "september": "42986260.08",
      "september_matches_original": true
    },
    {
      "amended": "62173312.84",
      "amendment_delta": "0.00",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "capex_cash_paid",
      "label": "购建固定资产、无形资产和其他长期资产支付的现金",
      "original": "62173312.84",
      "september": "62173312.84",
      "september_matches_original": true
    },
    {
      "amended": "99170943.48",
      "amendment_delta": "0.00",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "investing_net",
      "label": "投资活动产生的现金流量净额",
      "original": "99170943.48",
      "september": "99170943.48",
      "september_matches_original": true
    },
    {
      "amended": "1096849677.05",
      "amendment_delta": "122569677.05",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "financing_inflow",
      "label": "筹资活动现金流入小计",
      "original": "974280000.00",
      "september": "974280000.00",
      "september_matches_original": true
    },
    {
      "amended": "1100823838.67",
      "amendment_delta": "0.00",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "financing_outflow",
      "label": "筹资活动现金流出小计",
      "original": "1100823838.67",
      "september": "1100823838.67",
      "september_matches_original": true
    },
    {
      "amended": "-3974161.62",
      "amendment_delta": "122569677.05",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "financing_net",
      "label": "筹资活动产生的现金流量净额",
      "original": "-126543838.67",
      "september": "-126543838.67",
      "september_matches_original": true
    },
    {
      "amended": "15613364.89",
      "amendment_delta": "0.00",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "cash_net_increase",
      "label": "现金及现金等价物净增加额",
      "original": "15613364.89",
      "september": "15613364.89",
      "september_matches_original": true
    },
    {
      "amended": "180316289.42",
      "amendment_delta": "0.00",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "cash_begin",
      "label": "期初现金及现金等价物余额",
      "original": "180316289.42",
      "september": "180316289.42",
      "september_matches_original": true
    },
    {
      "amended": "195929654.31",
      "amendment_delta": "0.00",
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:102",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:102",
        "pdf:sha256:a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db:physical-page:12"
      ],
      "field": "cash_end",
      "label": "期末现金及现金等价物余额",
      "original": "195929654.31",
      "september": "195929654.31",
      "september_matches_original": true
    }
  ],
  "latest_visible_version": null,
  "ocf_minus_capex_subtotals_not_fcf": [
    {
      "evidence_refs": [
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101",
        "pdf:sha256:18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9:physical-page:101"
      ],
      "fcf_status": "UNKNOWN",
      "fcf_value": null,
      "ocf_minus_capex_cny": "-19187052.76",
      "version": "original_annual"
    },
    {
      "evidence_refs": [
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101",
        "pdf:sha256:1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791:physical-page:101"
      ],
      "fcf_status": "UNKNOWN",
      "fcf_value": null,
      "ocf_minus_capex_cny": "-141756729.81",
      "version": "amended_annual"
    }
  ],
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
  "statement_scope": "CONSOLIDATED",
  "subtotal_semantics": "仅 OCF−capex 算术中间值，缺未重复扣除租赁现金、归属权益/少数股东 alpha 和 PIT；不是 FCF。",
  "unit": "CNY",
  "version_warning": "9 月选定行重现原值；不以归档晚覆盖 8 月更正，不宣称整份文件版本关系已证明。"
}
```

## UNKNOWN 与未执行项

| 字段/规则 | 缺少的依赖 | 原因 |
|---|---|---|
| `FCF=UNKNOWN` | `OCF_pit, capex_pit, lease_cash, attributable_equity, minority_interest` | 2025 个案原文数值不等于完整归属 FCF 输入；不把租赁现金/少数股东权益缺失当零。 |
| `premise.roe_5y=UNKNOWN` | `six_consecutive_equities, five_parent_profits, available_at` | 单报告期不能代替六个连续年末权益与五年净利润。 |
| `absolute_valuation=UNKNOWN` | `five_annual_FCF, TTM_FCF, P, S, C, A, IB` | 未调用要求完整参数的估值函数，不用默认零制造可计算性。 |
| `latest_visible_version=UNKNOWN` | `historical_availability, complete_revisions_and_withdrawals` | 仅比较已固定文件，不选定声称截至 as_of 最新的有效财报。 |

整份更正后审计、完整窗口、逐日登记/流水等缺口按对应规则保留；不将它们作为查看原文和版本差额的通用前置条件。

## 证据与时点逐文件绑定

### original_annual（公告 1225248741）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2026-04-29/1225248741.PDF)；本地 bytes：`storage/pilots/financial-revision-2026-10-01/sz-000637-2025-annual-original.pdf`。
- SHA-256：`18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9`；物理页码：`[101, 102]` / 全部 209 页。
- 目录 `announcementTime`：`2026-04-29T00:00:00+08:00`（北京时间；原始毫秒 `1777392000000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### original_audit（公告 1225248743）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2026-04-29/1225248743.PDF)；本地 bytes：`storage/pilots/financial-000637-2025-chain-2026-10-01/2025-original-audit.pdf`。
- SHA-256：`448049c623801d7b2389f799637eeb8332b8d4cce420fa9ec467790f71ef47c9`；物理页码：`[12]` / 全部 120 页。
- 目录 `announcementTime`：`2026-04-29T00:00:00+08:00`（北京时间；原始毫秒 `1777392000000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### amended_annual（公告 1225460240）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2026-08-06/1225460240.PDF)；本地 bytes：`storage/pilots/financial-revision-2026-10-01/sz-000637-2025-annual-amended.pdf`。
- SHA-256：`1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791`；物理页码：`[101, 102]` / 全部 209 页。
- 目录 `announcementTime`：`2026-08-06T00:00:00+08:00`（北京时间；原始毫秒 `1785945600000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### corrected_statements（公告 1225460244）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2026-08-06/1225460244.PDF)；本地 bytes：`storage/pilots/financial-revision-2026-10-01/sz-000637-corrected-statements.pdf`。
- SHA-256：`d568c02d881faecb0e937d189147b4673ceb2680543268ef5bb7136ef13a86b3`；物理页码：`[24, 25, 26]` / 全部 29 页。
- 目录 `announcementTime`：`2026-08-06T00:00:00+08:00`（北京时间；原始毫秒 `1785945600000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### september_bundle（公告 1225584994）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2026-09-29/1225584994.PDF)；本地 bytes：`storage/pilots/financial-000637-2025-chain-2026-10-01/2026-09-29-financial-bundle.pdf`。
- SHA-256：`a42401180f78bf4d345f2a3a84c15769659c79b14c3b60e7140bb810eb8908db`；物理页码：`[12]` / 全部 136 页。
- 目录 `announcementTime`：`2026-09-29T00:00:00+08:00`（北京时间；原始毫秒 `1790611200000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

## 本地使用与复现

公开可获取不等于任意授权；未宣称已有全市场、商业或分享许可。未发送询证。

- 规则：`v1.3.2`；SHA-256：`db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`。
- 完整输入清单、工具/纯逻辑代码哈希见同名 JSON 的 `manifest`。
- 逻辑内容 SHA-256：`7f4762710ee73a7d86fb8ca9cef7eb71793124a70533395f366fdb44dfb4bfcf`（canonical JSON，排除自身哈希字段）。
- 同一范围、输入、规则与代码得到相同内容哈希；不声称输入已完整、历史时点已证实或事实因确定性而可靠。
