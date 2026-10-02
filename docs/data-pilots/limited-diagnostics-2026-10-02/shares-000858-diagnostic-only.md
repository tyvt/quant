# 五粮液 2025 股本：限定样本诊断（diagnostic_only=true）

## 本报告不宣称

- 这是单证券、单 as_of、限定输出范围的诊断，不是完整真实 PIT 策略运行。
- 这不是官方 Top-N、可发布回测或真实选股结果，不生成排名、目标权重、订单、持仓或净值。
- UNKNOWN 未作为数值参与计算，未填零、未跨证券借用、未插值或前向填充。
- 原文版本对照可以展示历史观察值；这些值不自动成为指定 as_of 的可用规则输入。
- 本报告不构成投资建议，不对外发布原始数据或报告，不用于商业用途。

## 冻结范围

- 证券：`sz.000858`；`as_of=2026-09-30`（请求历史收盘截止）。
- 复核日：`2026-10-02`；经济期间：`2025-01-01 — 2025-12-31`。
- 输出范围：`reported_share_endpoints, reported_buyback_applicability, share_input_gaps, share_policy_unknown_propagation`。
- `diagnostic_only=true`、`official_selection=false`；生产 Reader 与真实编排状态不变。

## 时点假设

- 处理：`UNKNOWN_UNLESS_VERIFIED`；`available_at=null`。
- 目录日期/时刻不等于最早公众可用；本次不采用当日或下一交易日可用假设。抓取晚于 as_of 不倒填。
- 目录时刻逐文件列于末节，供复核，不作为已核实的最早公开时点。
- 接纳到 PIT 规则中的真实数值观察为 **0**；原文对照数值仍完整展示。

## 原文观察与必要输入

| 字段 | 经济日期 | 版本 | 原文观察值 | 指定 as_of 输入 | 物理页证据 |
|---|---|---|---|---|---|
| 2025 年期初发行股数 | 2025-01-01 | `2025annual` | 3881608005 | UNKNOWN | `pdf:sha256:09133e1f44b3bb4b2cebe211529ad68f5b04b6be10b43870f2a78c947d5910a4:physical-page:42` |
| 2025 年期末发行股数 | 2025-12-31 | `2025annual` | 3881608005 | UNKNOWN | `pdf:sha256:09133e1f44b3bb4b2cebe211529ad68f5b04b6be10b43870f2a78c947d5910a4:physical-page:42` |
| 年报列回购实施不适用（非库存股零证明） | 2025-12-31 | `2025annual` | NOT_APPLICABLE_REPORTED | UNKNOWN | `pdf:sha256:09133e1f44b3bb4b2cebe211529ad68f5b04b6be10b43870f2a78c947d5910a4:physical-page:46` |
| 库存股栏空白，不能读为零 | 2025-12-31 | `2025annual` | 空白（非零） | UNKNOWN | `pdf:sha256:09133e1f44b3bb4b2cebe211529ad68f5b04b6be10b43870f2a78c947d5910a4:physical-page:53` |

## 已知部分的算术 / 纯逻辑缺口传播

以下算术只针对上述原文观察，不作为已证实的历史 PIT 结论。纯逻辑门控若全部 UNKNOWN，表示输入不满足，而非对公司质量的完整判断。

```json
{
  "daily_share_series": null,
  "difference_semantics": "观察端点之差；不是期间无事件、逐日股数或当前 S 的证明。",
  "endpoint_difference_shares": "0",
  "policy_execution": {
    "evidence_refs": [],
    "kind": "EVIDENCE",
    "missing_fields": [
      "S",
      "MV"
    ],
    "notes": [
      "share_capital_evidence_missing"
    ],
    "rule_id": "shares.capital_structure_policy",
    "status": "UNKNOWN",
    "value": null
  },
  "policy_input": null,
  "policy_input_reason": "没有覆盖指定 as_of 且时点已核实的结构观察，不能由年报端点制造结构证据。",
  "treasury_shares": null
}
```

## UNKNOWN 与未执行项

| 字段/规则 | 缺少的依赖 | 原因 |
|---|---|---|
| `S=UNKNOWN` | `event_complete_registration, share_classes, treasury_shares, available_at` | 发行股数端点不是普通股经济权益对应的逐日 S；回购不适用不证明库存股零。 |
| `MV=UNKNOWN` | `P_as_of, S_as_of` | 不以 A 股价格乘未核实口径的发行股数。 |

整份更正后审计、完整窗口、逐日登记/流水等缺口按对应规则保留；不将它们作为查看原文和版本差额的通用前置条件。

## 证据与时点逐文件绑定

### 2024annual_opening_bridge（公告 1223311527）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-04-26/1223311527.PDF)；本地 bytes：`storage/pilots/shares-000858-2025-chain-2026-10-01/2024annual.pdf`。
- SHA-256：`b737191a758994a35e9442d46847de771fe48b758feb9a7f35601def922435e7`；物理页码：`[47, 51]` / 全部 147 页。
- 目录 `announcementTime`：`2025-04-26T00:00:00+08:00`（北京时间；原始毫秒 `1745596800000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### 2025h1_original（公告 1224596951）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2025-08-28/1224596951.PDF)；本地 bytes：`storage/pilots/shares-000858-2025-chain-2026-10-01/2025h1-original.pdf`。
- SHA-256：`e460cfeaac9388f493dcafc14f4f5a6f83521f24a5ad3d3dd8a447cb437d755a`；物理页码：`[26]` / 全部 126 页。
- 目录 `announcementTime`：`2025-08-28T00:00:00+08:00`（北京时间；原始毫秒 `1756310400000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

### 2025annual（公告 1225273091）

- 原始来源：[巨潮 PDF](https://static.cninfo.com.cn/finalpage/2026-04-30/1225273091.PDF)；本地 bytes：`storage/pilots/shares-000858-2025-chain-2026-10-01/2025annual.pdf`。
- SHA-256：`09133e1f44b3bb4b2cebe211529ad68f5b04b6be10b43870f2a78c947d5910a4`；物理页码：`[42, 46, 53]` / 全部 141 页。
- 目录 `announcementTime`：`2026-04-30T18:20:25+08:00`（北京时间；原始毫秒 `1777544425000`）。
- 本次 `diagnostic_available_at=null`、历史可用性 UNKNOWN；不是抓取时点、登记生效日或最早公开证明。

## 本地使用与复现

公开可获取不等于任意授权；未宣称已有全市场、商业或分享许可。未发送询证。

- 规则：`v1.3.2`；SHA-256：`db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`。
- 完整输入清单、工具/纯逻辑代码哈希见同名 JSON 的 `manifest`。
- 逻辑内容 SHA-256：`8b52d15a1d8e09e7627f53f841e93aa4c9df1755ef18d181e9ece6586b193a82`（canonical JSON，排除自身哈希字段）。
- 同一范围、输入、规则与代码得到相同内容哈希；不声称输入已完整、历史时点已证实或事实因确定性而可靠。
