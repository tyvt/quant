# H00985 官方基准适配器只读验收（2026-09-30）

状态：`turtle_quant/adapters/csindex_benchmark.py` 的直接抓取、严格解析和日历对账
已通过验收；基准专用发布器和 `ParquetBenchmarkReader` 已实现，已发布
2018-06-19 至 2026-09-24 的首个快照及 2005-01-01 至 2026-09-24 的
全区间快照。两条官方非交易日行按已批准白名单隔离并审计；`RULE_SPEC`
v1.3.1 已将本 Reader 在上述快照各自覆盖内转为 `ready`，真实回测仍未获授权。

权威来源固定为中证指数有限公司
[`csindex-home/perf/index-perf`](https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=H00985&startDate=20260901&endDate=20260924)，
请求参数仅为 `indexCode=H00985`、`startDate=YYYYMMDD`、`endDate=YYYYMMDD`。
抓取不依赖第三方封装，也不自动回退到第三方。解析器保留完整响应 bytes，
计算其 SHA-256，逐行绑定来源哈希和证据引用；抓取时点只入快照审计元数据。
只接受 H00985、冻结的中英文全称、正的有限数值收盘点位，以及恰好覆盖由
独立日历给出的交易日。仅 `2005-01-01` 和 `2018-06-18` 的官方非交易日行
按已批准白名单隔离并记录结构化证据；服务端错误、响应身份漂移、JSON 重复键、
缺日、其他额外日期或任何请求区间外行全部硬失败。

2026-09-30 只读在线探针：使用阶段 A 已验证 `calendar` 快照
`snapshot-2abff764afcbfb52` 推导 2026-09-01 至 2026-09-24 预期交易日，
官方接口返回 18/18 行；首末点位分别为 8105.12 和 7907.95。
该探针当时未保存响应；后续独立发布的真实快照及全区间差异见
[`csindex-benchmark-snapshot-2026-09-30.md`](csindex-benchmark-snapshot-2026-09-30.md)。

离线回归：`python -m unittest tests.test_csindex_benchmark_adapter tests.test_csindex_benchmark_exclusions tests.test_parquet_benchmark_snapshot -v`。
首个快照已验收原始 JSON 不可变发布、规范化 Parquet schema、来源与文件哈希、
快照内容身份、撤销检查、显式 snapshot ID 只读映射及该快照覆盖区间的日历对账。
全历史区间例外及 v1 meta 兼容编码均已获裁决，并完成不可变发布和 Reader
全区间验收；v1.3.1 的 ready 不自动延伸到其他快照或日期区间。新发布证据
使用 `v1.3.1`，Reader 仍按历史全区间快照中已验证的 `v1.3.0` 证据重建。

### 已裁决的两日例外

项目负责人于 2026-09-30 批准两日显式白名单，裁决及摘要 SHA-256 见
[`csindex-excluded-dates`](../rule-rulings/2026-09-30-csindex-excluded-dates.md)。
裁决文件 SHA-256：`f579fd0a3bc0ccbfb4110cde85f3805e3b88d2d1a61b927b41cac7912caf8b59`。
原始 JSON 不删除任何行；隔离记录包含官方点位、日历结论、行证据引用和规则
版本。全区间对账为预期 5279 日、有效官方 5279 日、隔离 2 日；快照 ID 为
`snapshot-9b72a2666190542a`。`verify_published_domain` 验证顶层字符串标记
与 details 日期、证据严格对应；Reader 在 2020 年子区间仍返回全部例外信息。
这不解除其他生产门槛。

### 已裁决的身份语义

项目负责人于 2026-09-30 确认方案 A；裁定原文见
[`csindex-identity-ruling`](../rule-rulings/2026-09-30-csindex-identity.md)。裁定
文件 SHA-256：`a414ce1a477bff860f8b6fd88645a05d4fc65f49cc34f9d1a7c91034a88f7a81`。
抓取时点只入 snapshot meta 的 `source_provenance.csindex.fetch_time_utc`，
Parquet 行仅存稳定 `response_hash`。Reader 对每个显式 snapshot ID 读取该快照
自身的审计时间，不跨快照按响应哈希查找。合成回归已证明同一响应在不同时间抓取
保持相同 snapshot ID，但 Reader 分别返回各自快照的抓取时点。
