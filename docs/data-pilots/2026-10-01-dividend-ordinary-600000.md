# 浦发银行固定分红样本普通性复核（2026-10-01）

**结论：仅 `sh.600000` 的 2022 年度这一笔普通股基础现金分红，依既有 `RULE_SPEC v1.2.0` 的年度股息条款，可把 `is_ordinary` 从 `UNKNOWN` 提升为 `TRUE`。**
这不证明所有分红事件覆盖、不产生 `D`，也不使 `ParquetDividendReader` 转为 `ready`。
浦发银行属银行业，本样本不授权其进入 `GENERAL_FCF` 策略候选。

## 两份法定 PDF

| 证据 | 法定原文 | SHA-256 | 用途 |
| --- | --- | --- | --- |
| 董事会年度方案（落款 2023-04-18，目录日 2023-04-19） | [2022 年度利润分配方案公告](https://static.cninfo.com.cn/finalpage/2023-04-19/1216456205.PDF)，第 1–2 页 | `3304f19cd12fc66b019017756c4da6c5e12b04de5750ce2d422cb93d048d3a9d` | 经审计年度可供普通股分配利润、单项每股现金金额及年度基础分配 |
| 已批准方案的实施公告（落款 2023-07-12） | [2022 年年度普通股权益分派实施公告](https://news.spdb.com.cn/investor_relation/company_report/202307/P020230712640521382645.pdf)，第 1–3 页 | `556db2246673babc2d6dcc996fd3d9dff308b6610b4cd61dfe78baf5c005f17b` | 年度股东大会批准、分派对象、单项金额、基数和预定发放日 |

两份 PDF 全文均未标注该项现金分红为特别、额外、一次性、清算或资本返还；
此为对**上述固定 bytes** 的人工复核判断，不是“任何标题含普通股即为普通股息”的通用分类器。
实施公告的 bytes/hash 与旧 B2 夹具完全一致；新年度方案 PDF 构成额外的独立原文证据。
原始 bytes 本地保存于 `storage/pilots/dividend-ordinary-2026-10-01/`，不发布快照。

## 点时状态与接口边界

- 旧 [B2 v1 夹具](../../tests/fixtures/dividends/spdb-2022-annual-cash-dividend-v1.json)原样保留。
  缺少该法律分类侧证时，`is_ordinary=UNKNOWN`，不能从 AKShare/Baostock 的方案进度、
  “普通股”股份类别或已过预定支付日推断。
- 新[普通性侧证夹具](../../tests/fixtures/dividends/spdb-2022-ordinary-classification-v1.json)
  SHA-256 为 `8ef02d875900c102bc246342329e38265f7c7c530198ef53a578715e73920b8a`。
  它将两份 PDF 身份、证券、年度、页码、方案可用日与人工分类判断绑定；
  任一身份或时间不一致均拒绝。
- `2023-07-13T00:00:00Z` 起，该固定事件的 `is_ordinary=TRUE`，
  但 `is_paid=UNKNOWN`。只有后续定期报告从 `2023-09-01T00:00:00Z`
  起确认实施完毕，支付状态才转为 `TRUE`；不能倒填到预定发放日。
- 即使普通性与支付状态均为 `TRUE`，**任意估值窗口的全部事件覆盖仍未证明**，
  `window_event_coverage_complete=false`、`d_eligible_amount=null`、
  `research_eligible=false`。生产 `D` 继续为 `UNKNOWN`。

固定样本的纯映射见 `turtle_quant/adapters/dividend_samples.py`，新旧夹具和逆向断言见
`tests/test_dividend_samples.py`。尚需跨证券/跨窗口完整事件清单、更正链、支付完成证据覆盖
以及真实 PIT fixture 后，才可另行评估分红生产域 `ready`。
