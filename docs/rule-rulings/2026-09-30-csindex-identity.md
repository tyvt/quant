# csindex-identity-ruling

批准日期：2026-09-30。状态：已由 v1.3.1 正文吸收（2026-09-30）。适用范围：`RULE_SPEC v1.3.0` §9 的
H00985 官方基准快照；不变更 v1 快照身份或其他领域规则。下一次 `RULE_SPEC`
修订时将本修正声明写入正式条文，不为此单独发布规则版本。

## §9 修正声明

“规范行保留 fetched_at_utc”解释为：抓取时点记录于快照
`source_provenance.csindex.fetch_time_utc`（审计元数据），规范化 Parquet 行存
`response_hash`，`ParquetBenchmarkReader` 返回规范行时从快照 meta 补齐对应抓取
时点。v1 快照身份与既有契约不变。

同一响应哈希多次抓取时，Reader 只附上**产生当前显式 snapshot ID 的那次抓取**
的时点；不按响应哈希跨快照寻找最早或最新抓取。生产适配器直接请求官方接口，
原始 JSON bytes 原样保存并哈希；Reader 必须校验审计时点、响应哈希、规范行和
显式快照的对应关系。基准生产域在不可变发布、撤销、全区间日历和真实 fixture
验收前仍为 `not_ready`。

本裁定是对 §9 措辞的解释，不是授权真实选股或可发布回测。裁定文本 SHA-256
在基准适配器验收记录中登记，以便下一次规则修订引用。
