# 阶段 A Parquet Foundation Reader TDD

日期：2026-09-29  
规则：`RULE_SPEC v1.2.0` / `v1.2.0-20260929-02`

## 范围

本轮只实现获准的五个阶段 A 域：历史证券池、交易日历、RAW 日行情、StockDB
累积复权因子和中债国债 10 年收益率。财报、分红和回购分别保留独立
`NotImplementedError` 门禁；旧 `pit/parquet.py` 仍是兼容失败入口。Reader 只能
用于点时读取和数据验收，不产出研究筛选或回测结果。

## RED

先新增 `tests/test_stage_a_market_data.py`、`tests/test_parquet_foundation.py` 和
`tests/test_parquet_finance_gates.py`。首次执行因以下目标模块不存在而产生三个
导入错误：

- `turtle_quant.core.market_data`；
- `turtle_quant.pit.parquet_foundation`；
- 三个财务专用门禁与 `parquet_finance` 聚合门面。

没有删除旧失败测试，也没有以空集合或 fallback 让测试通过。

## GREEN 契约

合成快照测试冻结：

1. 五个域均使用调用方显式 snapshot ID，主三域必须同 snapshot；
2. 构造时校验发布身份、撤销、文件哈希、域行数、必需列及 schema/
   normalization 白名单；
3. 零行、零列行情分片仅作为已验证的空分片接受，非零行缺列仍失败；
4. 历史证券上市、退市和板块区间端点包含；
5. 行情只读取证券前五位数字对应分片，并向 Parquet 传证券/日期过滤谓词；
6. `PriceBarSeries` 分别返回 `SECURITY_NOT_COVERED`、`MISSING_BAR`、
   `PAUSE_STATUS_UNKNOWN`、`EVIDENCE_MISSING`，问题只污染依赖字段；
7. 因子统一按 `available_at <= as_of` 可见，保留查询起点之前的最近基线；同一
   PIT 排序键的冲突因子硬失败；
8. 中债 series 只接受 `CN_GOVT_10Y_YIELD_PCT`；周五至周一计零交易日、周四
   至周一计一个交易日，连续长假不增加陈旧度；
9. 日历缓冲只允许 `next_trading_day(end_date)` 使用，缓冲日期不能再次查询；
10. `RunManifest` 固定 `rules_version=v1.2.0`、全部 snapshot ID、主 cohort
    `universe_hash`、稳定来源和已选域质量标记；
11. 三个财务专用 Reader 可独立演进，但聚合门面在三者全部 ready 前不得部分
    开放。

## 真实快照只读验收

固定组合：

| 用途 | snapshot ID |
|---|---|
| security / market / factors | `snapshot-16de9d9c4679347d` |
| calendar / ChinaBond 10Y | `snapshot-2abff764afcbfb52` |

验收结果：

- 构造约 1.34 秒；逐文件 SHA-256 和版本检查通过，未扫描目录选择 latest；
- 主板历史证券池在 2026-09-24 返回 3,196 个证券；
- 浦发银行 2026-09-01 至 09-24 通过单分片过滤读取 17 条 bar；09-24 是日历
  交易日但快照无 bar，准确返回一个 `MISSING_BAR`；17 条来源均无明确 paused，
  分别返回 `PAUSE_STATUS_UNKNOWN`，没有把 null 当作 FALSE；
- `sh.600788` 位于 `missing_security_ids`，返回
  `SECURITY_NOT_COVERED`，不返回“完整空序列”；
- 浦发银行 2022–2026 五次除权均复现既有连续性证据：

| 除权日 | 调整后前收盘 | 除权日收盘 | 差额 |
|---|---:|---:|---:|
| 2022-07-21 | 7.3768 | 7.33 | 0.0468 |
| 2023-07-21 | 7.1005 | 7.12 | -0.0195 |
| 2024-07-18 | 8.7172 | 8.77 | -0.0528 |
| 2025-07-16 | 13.5247 | 13.48 | 0.0447 |
| 2026-07-16 | 8.8923 | 8.85 | 0.0423 |

- 2026-09-24 的利率读取选择 2026-09-23 观测、09-24 可用的 `1.6807%`；
- `next_trading_day(2026-09-24)` 只从缓冲返回 2026-09-28；
- Manifest 记录两组 snapshot、`v1.2.0` 和 15 个已选域质量标记；
- 被撤销的旧中债域仍由发布校验硬拒绝，不自动跟随 replacement。

真实验收只报告数据状态，不把浦发样本解释为选股或回测结论。

## 执行

```text
python -m compileall -q turtle_quant tests
python -m coverage run --branch --source=turtle_quant -m unittest discover -s tests
python -m coverage report -m
```

2026-09-29 最终全量回归结果：**162 项测试全部通过**；`turtle_quant` 源码
分支覆盖率为 **81%**，其中 `turtle_quant/pit/parquet_foundation.py` 为 **80%**。
`python -m compileall -q turtle_quant tests` 同步通过。
