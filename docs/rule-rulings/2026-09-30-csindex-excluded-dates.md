# csindex-excluded-dates

批准日期：2026-09-30。状态：已由 v1.3.1 正文吸收（2026-09-30）。
适用范围：中证指数官方 H00985 历史响应与显式中国交易日历对账。
这是一项对 `RULE_SPEC v1.3.0` §9 “恰好覆盖”的窄化解释，不放宽指数身份、
有限正收盘点位、原始响应留存、其他日期硬失败或 §11 的生产 ready 门槛。
下一次 `RULE_SPEC` 修订时将本例外写入 §9 正文，不为此单独发布规则版本。

## 批准的例外

仅 `2005-01-01` 与 `2018-06-18` 两个**逐字列明**的日期可从规范化交易日
序列隔离；不能按周末、节假日、月份或日期范围推断其他例外。原始官方 JSON
完整保留。已知官方 close 分别为 `984.40` 与 `5161.74`；若官方值改变、日历
将其中一日标为交易日、源行重复，均硬失败并重新审查。

每条隔离记录至少有：`excluded_date`、`official_close`、
`calendar_verdict=NON_TRADING_DAY`、`exclusion_reason`、`evidence_ref`
（原始响应哈希、行偏移与行内容哈希）、`rule_version=v1.3.0`。证据必须可由
不可变原始 JSON 逐行重算；任何白名单外额外日期、交易日缺口或重复日期仍硬失败。

全区间快照须有 `source_provenance.csindex.exclusion_policy =
explicit_whitelist_v1`，并将例外日期与完整结构化证据写入 snapshot meta。
Reader 必须在返回值中附带例外标记、日期及结构化证据，即使查询子区间
本身不含隔离日。

## 裁决摘要身份

以下 ASCII 规范串以 UTF-8、无尾部换行计算 SHA-256；它标识本裁决的批准
日期、指数、两日白名单、策略 ID 和规则版本，不是自引用的文档文件哈希：

```text
csindex-excluded-dates-v1|approved=2026-09-30|index=H00985|dates=2005-01-01,2018-06-18|policy=explicit_whitelist_v1|rule=v1.3.0
```

SHA-256：`deb7a72627119704a19fd582db006a511fb60ca5377e1f7552826cc4b18c2388`。

## 元数据形状：v1 兼容编码裁决

项目负责人于 2026-09-30 批准下列编码作为约束 3 的实现；不升级 v1 快照
schema，也不改写既有快照身份：

- 顶层 `data_quality_flags` 保持字符串列表，其中
  `"benchmark_excluded_dates"` 仅作例外存在的索引标记。
- `domains.benchmark.details.benchmark_excluded_dates` 保存按日期排序的完整例外
  日期列表，`domains.benchmark.details.exclusion_evidence` 保存与日期逐项对应的
  结构化证据；这里是内容的单一真相源。
- `source_provenance.csindex.exclusion_policy` 固定为
  `"explicit_whitelist_v1"`。
- `ParquetBenchmarkReader` 的任意非空子区间返回值都携带完整字符串标记、
  例外日期及结构化证据，不能按查询日期过滤；Reader 自身也暴露这三项，
  以便空子区间仍可检查快照级例外状态。

`verify_published_domain` 对 `benchmark` 域严格验证标记与 details：顶层及域内
标记存在，当且仅当 details 有非空例外日期；有日期必须有逐项对应的完整证据
和指定 `exclusion_policy`。任一侧缺失、空证据或日期不匹配都硬失败。Reader
随后用不可变原始 JSON、独立日历和规范化 Parquet 行再次核对实际日期与证据。

下一次 `RULE_SPEC` 修订时，§9 正文须明确：顶层字符串标记用于索引，
`domains.*.details` 用于结构化证据；本裁决在此之前按本文件执行。
