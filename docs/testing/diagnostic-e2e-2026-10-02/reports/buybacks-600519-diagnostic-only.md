# 茅台首个减资回购计划：限定样本诊断（diagnostic_only=true）

## 本报告不宣称

- 这是单证券、单 as_of、限定输出范围的诊断，不是完整真实 PIT 策略运行。
- 这不是官方 Top-N、可发布回测或真实选股结果，不生成排名、目标权重、订单、持仓或净值。
- UNKNOWN 未作为数值参与计算，未填零、未跨证券借用、未插值或前向填充。
- 原文版本对照可以展示历史观察值；这些值不自动成为指定 as_of 的可用规则输入。
- 本报告不构成投资建议，不对外发布原始数据或报告，不用于商业用途。

## 冻结范围

- 证券：`sh.600519`；`as_of=2026-09-30`（请求历史收盘截止）。
- 复核日：`2026-10-02`；经济期间：`2024-09-21 — 2025-08-29`。
- 输出范围：`first_execution_observation, cumulative_interval_differences, buyback_input_gaps`。
- `diagnostic_only=true`、`official_selection=false`；生产 Reader 与真实编排状态不变。

## 时点假设

- 处理：`UNKNOWN_UNLESS_VERIFIED`；`available_at=null`。
- 目录日期/时刻不等于最早公众可用；本次不采用当日或下一交易日可用假设。抓取晚于 as_of 不倒填。
- 目录时刻逐文件列于末节，供复核，不作为已核实的最早公开时点。
- 接纳到 PIT 规则中的真实数值观察为 **0**；原文对照数值仍完整展示。

## 原文观察与必要输入

| 字段 | 经济日期 | 版本 | 原文观察值 | 指定 as_of 输入 | 物理页证据 |
|---|---|---|---|---|---|
| 首日实际执行金额（非完整 B_buyback） | 2025-01-02 | `first_execution` | 299919221.00 | UNKNOWN | `pdf:sha256:9daacceadc60030620ca85863e00ac59576892202261f8d86e2ad40ae8575d0c:physical-page:2` |
| 截至该日累计金额 | 2025-01-31 | `january_progress` | 999909571.13 | UNKNOWN | `pdf:sha256:c30d4359a5330c283b1dc2e53e13ded8d8aaa6a91a9c2788a334320bf6b464d1:physical-page:2` |
| 截至该日累计金额 | 2025-02-28 | `february_progress` | 1199883179.92 | UNKNOWN | `pdf:sha256:b5af10864264aa997bb6550428a60e3b223fc46e08dddda4cf7ee8751c819217:physical-page:2` |
| 截至该日累计金额 | 2025-03-31 | `march_progress` | 1598768542.16 | UNKNOWN | `pdf:sha256:b49fa09f132112039554d555cca0952a12d0d6c3ce678e3bfb8ce008431bc526:physical-page:2` |
| 截至该日累计金额 | 2025-04-07 | `april_7_progress` | 1948495151.53 | UNKNOWN | `pdf:sha256:2e0227ad707b0b5030411ed774de28b540e6bcef289f7ef6f401d65c6dd3e1f7:physical-page:2` |
| 截至该日累计金额 | 2025-04-30 | `april_progress` | 3038850762.50 | UNKNOWN | `pdf:sha256:de9da873a530071355a42ea6ea1eae3e30bd7b9e52f6a84084c2c36941cae8d1:physical-page:2` |
| 截至该日累计金额 | 2025-05-16 | `may_16_progress` | 4050254683.12 | UNKNOWN | `pdf:sha256:8e7031203203a9c6c68d59d7a98a756b18715652abb2b2f6b2ad447cb4ef6802:physical-page:2` |
| 截至该日累计金额 | 2025-05-31 | `may_progress` | 5099947291.83 | UNKNOWN | `pdf:sha256:e8b99f4f9359b163be4e4911bc9ee270709cc690dd48adf38e96d0f05cfcc07b:physical-page:2` |
| 截至该日累计金额 | 2025-06-30 | `june_progress` | 5201527341.83 | UNKNOWN | `pdf:sha256:49f0de4a1451e41cb0f743cc45d7833fa680237275de489f11ece9eab99a8b23:physical-page:2` |
| 截至该日累计金额 | 2025-07-31 | `july_progress` | 5301459045.23 | UNKNOWN | `pdf:sha256:361ae54ff0add9530bf85e57e5d7b8c3a6cc2c5c39dc472c86f11a164fb421a2:physical-page:2` |
| 截至该日累计金额 | 2025-08-29 | `final_result` | 5999985966.95 | UNKNOWN | `pdf:sha256:9ad8dda3c43bbc19bf9926394ddf4a030543455910f7ef1b1bb736bd4385215b:physical-page:2` |

## 已知部分的算术 / 纯逻辑缺口传播

以下算术只针对上述原文观察，不作为已证实的历史 PIT 结论。纯逻辑门控若全部 UNKNOWN，表示输入不满足，而非对公司质量的完整判断。

```json
{
  "actual_last_execution_day": null,
  "final_cumulative_amount_cny": "5999985966.95",
  "first_amount_semantics": "已观察执行日与金额；未证明 PIT 可用、合格注销/完整窗口，不直接计入 B_buyback 或 GG。",
  "first_execution_amount_cny": "299919221.00",
  "first_execution_day": "2025-01-02",
  "first_execution_shares": "200900",
  "intervals": [
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "699990350.13",
      "difference_shares": "484200",
      "end_inclusive": "2025-01-31",
      "evidence_refs": [
        "pdf:sha256:9daacceadc60030620ca85863e00ac59576892202261f8d86e2ad40ae8575d0c:physical-page:2",
        "pdf:sha256:c30d4359a5330c283b1dc2e53e13ded8d8aaa6a91a9c2788a334320bf6b464d1:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-01-02"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "199973608.79",
      "difference_shares": "137100",
      "end_inclusive": "2025-02-28",
      "evidence_refs": [
        "pdf:sha256:c30d4359a5330c283b1dc2e53e13ded8d8aaa6a91a9c2788a334320bf6b464d1:physical-page:2",
        "pdf:sha256:b5af10864264aa997bb6550428a60e3b223fc46e08dddda4cf7ee8751c819217:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-01-31"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "398885362.24",
      "difference_shares": "260500",
      "end_inclusive": "2025-03-31",
      "evidence_refs": [
        "pdf:sha256:b5af10864264aa997bb6550428a60e3b223fc46e08dddda4cf7ee8751c819217:physical-page:2",
        "pdf:sha256:b49fa09f132112039554d555cca0952a12d0d6c3ce678e3bfb8ce008431bc526:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-02-28"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "349726609.37",
      "difference_shares": "233201",
      "end_inclusive": "2025-04-07",
      "evidence_refs": [
        "pdf:sha256:b49fa09f132112039554d555cca0952a12d0d6c3ce678e3bfb8ce008431bc526:physical-page:2",
        "pdf:sha256:2e0227ad707b0b5030411ed774de28b540e6bcef289f7ef6f401d65c6dd3e1f7:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-03-31"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "1090355610.97",
      "difference_shares": "701582",
      "end_inclusive": "2025-04-30",
      "evidence_refs": [
        "pdf:sha256:2e0227ad707b0b5030411ed774de28b540e6bcef289f7ef6f401d65c6dd3e1f7:physical-page:2",
        "pdf:sha256:de9da873a530071355a42ea6ea1eae3e30bd7b9e52f6a84084c2c36941cae8d1:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-04-07"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "1011403920.62",
      "difference_shares": "624646",
      "end_inclusive": "2025-05-16",
      "evidence_refs": [
        "pdf:sha256:de9da873a530071355a42ea6ea1eae3e30bd7b9e52f6a84084c2c36941cae8d1:physical-page:2",
        "pdf:sha256:8e7031203203a9c6c68d59d7a98a756b18715652abb2b2f6b2ad447cb4ef6802:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-04-30"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "1049692608.71",
      "difference_shares": "667956",
      "end_inclusive": "2025-05-31",
      "evidence_refs": [
        "pdf:sha256:8e7031203203a9c6c68d59d7a98a756b18715652abb2b2f6b2ad447cb4ef6802:physical-page:2",
        "pdf:sha256:e8b99f4f9359b163be4e4911bc9ee270709cc690dd48adf38e96d0f05cfcc07b:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-05-16"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "101580050.00",
      "difference_shares": "72000",
      "end_inclusive": "2025-06-30",
      "evidence_refs": [
        "pdf:sha256:e8b99f4f9359b163be4e4911bc9ee270709cc690dd48adf38e96d0f05cfcc07b:physical-page:2",
        "pdf:sha256:49f0de4a1451e41cb0f743cc45d7833fa680237275de489f11ece9eab99a8b23:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-05-31"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "99931703.40",
      "difference_shares": "69600",
      "end_inclusive": "2025-07-31",
      "evidence_refs": [
        "pdf:sha256:49f0de4a1451e41cb0f743cc45d7833fa680237275de489f11ece9eab99a8b23:physical-page:2",
        "pdf:sha256:361ae54ff0add9530bf85e57e5d7b8c3a6cc2c5c39dc472c86f11a164fb421a2:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-06-30"
    },
    {
      "daily_allocation_status": "UNKNOWN",
      "daily_amounts": null,
      "difference_cny": "698526921.72",
      "difference_shares": "475900",
      "end_inclusive": "2025-08-29",
      "evidence_refs": [
        "pdf:sha256:361ae54ff0add9530bf85e57e5d7b8c3a6cc2c5c39dc472c86f11a164fb421a2:physical-page:2",
        "pdf:sha256:9ad8dda3c43bbc19bf9926394ddf4a030543455910f7ef1b1bb736bd4385215b:physical-page:2"
      ],
      "executed_on": null,
      "start_exclusive": "2025-07-31"
    }
  ],
  "plan_id": "sh.600519:2024-09-21:capital-reduction",
  "reported_completion_on": "2025-08-29",
  "unlocated_amount_after_first_day_cny": "5700066745.95",
  "verified_cancellation_effective_on": null
}
```

## UNKNOWN 与未执行项

| 字段/规则 | 缺少的依赖 | 原因 |
|---|---|---|
| `B_buyback=UNKNOWN` | `all_execution_days, window_all_plans, qualifying_cancellation, available_at` | 累计差分不分配到月末/完成日，不平均分摊；单笔已知也不等于发行人完整窗口。 |
| `GG=UNKNOWN` | `B_buyback, D, MV, full_window_coverage` | 必要跨域输入未闭环。 |

整份更正后审计、完整窗口、逐日登记/流水等缺口按对应规则保留；不将它们作为查看原文和版本差额的通用前置条件。

## 证据与时点逐文件绑定

### first_execution（公告 1222206659）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-01-03/1222206659.PDF)；本地 bytes：`storage/pilots/buyback-first-day-2026-10-01/moutai-2025-first-buyback.pdf`。
- SHA-256：`9daacceadc60030620ca85863e00ac59576892202261f8d86e2ad40ae8575d0c`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-01-03T00:00:00+08:00`（北京时间；原始毫秒 `1735833600000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### january_progress（公告 1222472609）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-02-07/1222472609.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-02-progress.pdf`。
- SHA-256：`c30d4359a5330c283b1dc2e53e13ded8d8aaa6a91a9c2788a334320bf6b464d1`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-02-07T00:00:00+08:00`（北京时间；原始毫秒 `1738857600000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### february_progress（公告 1222706937）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-03-05/1222706937.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-03-progress.pdf`。
- SHA-256：`b5af10864264aa997bb6550428a60e3b223fc46e08dddda4cf7ee8751c819217`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-03-05T00:00:00+08:00`（北京时间；原始毫秒 `1741104000000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### march_progress（公告 1222993918）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-04-03/1222993918.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-04-03-progress.pdf`。
- SHA-256：`b49fa09f132112039554d555cca0952a12d0d6c3ce678e3bfb8ce008431bc526`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-04-03T00:00:00+08:00`（北京时间；原始毫秒 `1743609600000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### april_7_progress（公告 1223023904）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-04-08/1223023904.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-04-08-progress.pdf`。
- SHA-256：`2e0227ad707b0b5030411ed774de28b540e6bcef289f7ef6f401d65c6dd3e1f7`；物理页码：`[2]` / 全部 3 页。
- 目录 `announcementTime`：`2025-04-08T09:11:00+08:00`（北京时间；原始毫秒 `1744074660000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### april_progress（公告 1223490954）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-05-08/1223490954.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-05-08-progress.pdf`。
- SHA-256：`de9da873a530071355a42ea6ea1eae3e30bd7b9e52f6a84084c2c36941cae8d1`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-05-08T00:00:00+08:00`（北京时间；原始毫秒 `1746633600000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### may_16_progress（公告 1223569076）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-05-17/1223569076.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-05-17-progress.pdf`。
- SHA-256：`8e7031203203a9c6c68d59d7a98a756b18715652abb2b2f6b2ad447cb4ef6802`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-05-17T00:00:00+08:00`（北京时间；原始毫秒 `1747411200000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### may_progress（公告 1223765024）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-06-05/1223765024.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-06-progress.pdf`。
- SHA-256：`e8b99f4f9359b163be4e4911bc9ee270709cc690dd48adf38e96d0f05cfcc07b`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-06-05T00:00:00+08:00`（北京时间；原始毫秒 `1749052800000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### june_progress（公告 1224067388）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-07-03/1224067388.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-07-progress.pdf`。
- SHA-256：`49f0de4a1451e41cb0f743cc45d7833fa680237275de489f11ece9eab99a8b23`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-07-03T00:00:00+08:00`（北京时间；原始毫秒 `1751472000000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### july_progress（公告 1224387017）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-08-05/1224387017.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-08-progress.pdf`。
- SHA-256：`361ae54ff0add9530bf85e57e5d7b8c3a6cc2c5c39dc472c86f11a164fb421a2`；物理页码：`[2]` / 全部 2 页。
- 目录 `announcementTime`：`2025-08-05T00:00:00+08:00`（北京时间；原始毫秒 `1754323200000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### final_result（公告 1224625694）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-08-30/1224625694.PDF)；本地 bytes：`storage/pilots/buyback-600519-2025-chain-2026-10-01/2025-final.pdf`。
- SHA-256：`9ad8dda3c43bbc19bf9926394ddf4a030543455910f7ef1b1bb736bd4385215b`；物理页码：`[1, 2, 3]` / 全部 3 页。
- 目录 `announcementTime`：`2025-08-30T00:00:00+08:00`（北京时间；原始毫秒 `1756483200000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

## 本地使用与复现

公开可获取不等于任意授权；未宣称已有全市场、商业或分享许可。未发送询证。

- 规则：`v1.3.2`；SHA-256：`db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`。
- 完整输入清单、工具/纯逻辑代码哈希见同名 JSON 的 `manifest`。
- 逻辑内容 SHA-256：`594291d307143113a804f6c37f77e42f3eddf18951c12908e073f08d67f4f3fe`（canonical JSON，排除自身哈希字段）。
- 同一范围、输入、规则与代码得到相同内容哈希；不声称输入已完整、历史时点已证实或事实因确定性而可靠。
