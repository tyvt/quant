# B3 固定夹具的日期语义

`moutai-2024-plan-cumulative-observations-v1.json` 是按 SHA-256 固定的原始
审计样本，不在本说明中改写其 bytes、`fixture_version` 或历史取值。

其中 `sample.last_execution_date = "2025-08-29"` 是**遗留字段名**。
它在适配器中按**累计截止/计划完成日**使用，用于日期顺序、最后一份法定
结果公告的一致性和固定样本的注销顺序校验
（`legal_cumulative_observations[-1].cumulative_through`）；
公告没有证明最后一笔回购交易恰在 2025-08-29。真实
`actual_last_execution_day` 仍为 `UNKNOWN`，不能从该字段生成
`executed_on`、逐日金额、最近完整自然年回购额或生产 `B_buyback`。

首次回购 `2025-01-02` 有[单日法定证据](../../../docs/data-pilots/2026-10-01-buyback-first-day-600519.md)；
后续[完整公告链探针](../../../docs/data-pilots/2026-10-01-buyback-plan-chain-600519.md)
只把累计金额进一步切分为区间，不把区间截止日变成交易日。
在取得按计划 ID 的回购专户逐日/逐笔成交清单之前，保持此 UNKNOWN 语义。
如未来要更名字段或改变夹具内容，应另出新版夹具并重算身份，不能静默修改 v1。
