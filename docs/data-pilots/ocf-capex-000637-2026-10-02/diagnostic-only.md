# 茂化实华 2025 OCF/Capex：同版原文核验与普通口径算术（diagnostic_only=true）

## 本报告不宣称

- 这是单证券、单 as_of、限定输出范围的诊断，不是完整真实 PIT 策略运行。
- 这不是官方 Top-N、可发布回测或真实选股结果，不生成排名、目标权重、订单、持仓或净值。
- UNKNOWN 未作为数值参与计算，未填零、未跨证券借用、未插值或前向填充。
- 原文版本对照可以展示历史观察值；这些值不自动成为指定 as_of 的可用规则输入。
- 本报告不构成投资建议，不对外发布原始数据或报告，不用于商业用途。

## 限定补证结果

- `sz.000637`；`as_of=2026-09-30`；2025 完整年度；合并口径、人民币元。
- 父报告已有 OCF/Capex 原文观察；本次独立核验表格单元格并绑定同版 E/N，未新增已核实历史 PIT 输入。

| 固定版本 | OCF（元） | Capex（元） | OCF−Capex（元） | 普通口径原文算术（元，非 PIT） |
|---|---:|---:|---:|---:|
| original_2025_annual_report | 42986260.08 | 62173312.84 | -19187052.76 | -16158353.92113239932027895383 |
| amended_2025_annual_report | -79583416.97 | 62173312.84 | -141756729.81 | -119380263.3277545425210896909 |

- `FCF_ordinary_source_arithmetic = (OCF - Capex) * alpha_observed`；28 位 Decimal、ROUND_HALF_EVEN；负值不截断。
- 两版 alpha 均为 `0.8421488241705548591131801230`，复用已冻结同版 E/N；不跨发行人、期间、口径、单位、版本或 PDF 拼接。
- 物理第 101 页核验合并现金流量表、2025/2024 年度列、元单位、OCF 与两行 Capex 支付科目；第 102 页核验筹资续表及下方母公司表边界。
- OCF 与同列经营流入小计−流出小计对平。Capex 取购建长期资产支付行，不取投资流出合计、不扣处置资产收款。
- 2024 比较栏不是本次目标：原版 OCF `9077909.18`，更正版 `-185115131.48`；Capex 两版均 `79764639.75`。

## 时点假设与保留缺口

- `UNKNOWN_UNLESS_VERIFIED`；`diagnostic_available_at=null`；历史 PIT 准入观察数量为 0。目录日期、抓取日或保守延后均未被当作已核实可用时点。
- `OCF_pit/Capex_pit/E_pit/N_pit/alpha_pit/FCF_ordinary_pit` 全部 UNKNOWN；不选择声称最新可见的版本，也不用 9 月原版重现覆盖 8 月更正。
- 未重复扣减的现金租赁支出仍 UNKNOWN；没有填零，也没有用租赁负债余额代替。`FCF_conservative/FCF/F1..F5` 未生成。
- 普通口径只是诊断算术，不能替代 GENERAL_FCF 标准项；完整修订链、更正后整份审计状态与五年窗口未闭环。
- 不调用 premise/valuation/未就绪 Reader，不生成排名、权重、订单、持仓、净值；生产状态、父报告及 N/E 补证均不变。

## 原文证据

### original_2025_annual_report

- 公告 `1225248741`：[法定 PDF](https://static.cninfo.com.cn/finalpage/2026-04-29/1225248741.PDF)。
- 本地 bytes：`storage/pilots/financial-revision-2026-10-01/sz-000637-2025-annual-original.pdf`；SHA-256：`18231670324fb8ab60c264dbaebf4972004a4c153aa5a046dc7be4d2e40646d9`；物理页 101/102（E/N 依赖页 93/94/95）。
- 目录时间 `2026-04-29T00:00:00+08:00`，不证明最早公众可见。

### amended_2025_annual_report

- 公告 `1225460240`：[法定 PDF](https://static.cninfo.com.cn/finalpage/2026-08-06/1225460240.PDF)。
- 本地 bytes：`storage/pilots/financial-revision-2026-10-01/sz-000637-2025-annual-amended.pdf`；SHA-256：`1188d9bcac97cc67fa75424b8382acfbb387384b5e3dfeb71f545d1f90fb4791`；物理页 101/102（E/N 依赖页 93/94/95）。
- 目录时间 `2026-08-06T00:00:00+08:00`，不证明最早公众可见。

## 可复现身份

- 父诊断：`7f4762710ee73a7d86fb8ca9cef7eb71793124a70533395f366fdb44dfb4bfcf`。
- E/alpha 补证：`60662e64e86ed7bfbfc71c47ab9f7fddf7bee14ef0f6167ba8d24d5adadfa701`。
- N 补证：`744d1408ce8002f560c463db66bfd1d073d0cf600dbeae228941b4fd4bee29ef`。
- 本补证：`059ccf34098000d14265e8041a6bbaff2a5460c8595c85846dfca58c34edfd02`；输入、规则、代码、来源与 UNKNOWN 均纳入 canonical JSON 身份。
- 离线重建；源 PDF 是证据，渲染只作目视检查。仅作遵守来源条款的本地复核，不对外发布或用于商业用途。
