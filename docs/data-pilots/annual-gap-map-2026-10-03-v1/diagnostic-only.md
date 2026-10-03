# 年报缺口族：统一代码样本盘点

仅工程诊断，不是企业硬门、证券排名或全市场覆盖证明。

logical_content_hash：`42f1bd53b8af3d72b8c70963ec554c07fdf9de6f05daa8ce438026fa7f5d0cb9`。

范围：10 家发行人，13 个 PDF 版本。

## 工程优先级（建议，未执行修复）

| 缺口信号 | PDF 数 | 发行人数 | 受阻资产负债表行 | 建议顺序 |
|---|---:|---:|---:|---:|
| 复杂附注引用 | 3 | 3 | 133 | 1 |
| 审计类型原文未识别 | 8 | 8 | 不适用 | 2 |
| 租赁现金部分未识别 | 5 | 5 | 不适用 | 3 |
| 币种证据阻断 | 3 | 3 | 不适用 | 4 |
| 目标金额列边界歧义 | 2 | 2 | 不适用 | 5 |

## 逐版本结果（当前代码回归，不改写首次盲跑）

| 证券／年度／声明版本 | 目标字段观察数 | 币种 | 复杂附注受阻行 |
|---|---:|---|---:|
| sh.600066／2024／declared_2024_annual_report | 2/7 | CNY | 0 |
| sh.600276／2024／declared_2024_annual_report | 5/7 | CNY | 36 |
| sh.600309／2024／declared_2024_annual_report | 0/7 | UNKNOWN | 不可评估 |
| sh.600585／2024／declared_2024_annual_report | 0/7 | UNKNOWN | 不可评估 |
| sh.600741／2024／declared_2024_annual_report | 0/7 | UNKNOWN | 不可评估 |
| sh.600887／2024／declared_2024_annual_report | 7/7 | CNY | 49 |
| sh.600900／2024／declared_2024_annual_report | 7/7 | CNY | 0 |
| sh.601012／2024／declared_2024_annual_report | 7/7 | CNY | 48 |
| sz.000637／2025／amended_2025_annual_report | 7/7 | CNY | 0 |
| sz.000637／2025／original_2025_annual_report | 7/7 | CNY | 0 |
| sz.002570／2022／first_corrected_annual | 7/7 | CNY | 0 |
| sz.002570／2022／original_annual | 7/7 | CNY | 0 |
| sz.002570／2022／second_corrected_annual | 7/7 | CNY | 0 |

## 现有附注守卫的合成探针（不是公司数据）

| 原生词元 | 当前金额状态 | 引用目标已解析 |
|---|---|---|
| 7 | OBSERVED_NUMERIC | 否 |
| — | OBSERVED_NUMERIC | 否 |
| 七（1） | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| 七、1 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| 附注七 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| 七-1 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| 7 / 1 | OBSERVED_NUMERIC | 否 |
| -1 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| +1 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| 1.2 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| 七（1 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |
| 1,2 | NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE | 否 |

两个整数词元分别通过检查不证明附注唯一；本盘点未修改守卫、未接纳复杂引用。

- 选择样本不是随机市场抽样；不估计全市场比例或准确率。
- 统一当前代码重跑是回归盘点，不是新的独立盲跑。
- 附注仅统计已提取资产负债表行；币种阻断时不可评估，未扫描不等于无缺口。
- 审计／租赁未识别不证明未披露，不从计数推定版式原因。
- 工程工作顺序不是证券排名、规则变更或生产授权。

完整租赁、可用时点、版本链等仍未闭环，PIT 准入 0，九域／真实策略编排 not_ready 不变。
