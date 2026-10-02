# H00985 首个不可变快照与全区间日历对账（2026-09-30）

## 已发布的干净区间

- 显式日历快照：`snapshot-2abff764afcbfb52`（已发布 `calendar` 域）。
- 基准覆盖：2018-06-19 至 2026-09-24，预期/官方/Reader 均为 **2010 日**。
- 基准快照：`snapshot-d9fa4c6d8933fe39`，状态 `complete`，`benchmark` 行数 2010。
- [meta.json](../../storage/snapshots/snapshot-d9fa4c6d8933fe39/meta.json) 中的
  `source_provenance.csindex.fetch_time_utc` 为 `2026-09-30T11:58:19Z`；
  `source_provenance.csindex.response_hash`、域 details 的 `response_hash` 与原始
  JSON 文件 SHA-256 均为
  `10f0d259ab36d3e209ec4e981c08f64c57730d750fbf87cfb87c727545c202ef`。
- 白名单文件：`raw/response.json` 与 `benchmark/values.parquet`；Parquet 行没有
  `fetched_at_utc`，只存 `response_hash`。Reader 全区间逐行重读原始 JSON、
  对账规范行和独立日历；撤销检查由 `verify_published_domain` 执行。
- 真值抽查：2026-09-01 收盘 8105.12，2026-09-24 收盘 7907.95；Reader
  在 2026-09-01 至 2026-09-24 子区间返回 18 日并附本快照审计时点。

复核命令：

```powershell
python -m scripts.sync_csindex_benchmark --calendar-snapshot-id snapshot-2abff764afcbfb52 --start 2018-06-19 --end 2026-09-24
python -m unittest tests.test_parquet_benchmark_snapshot -v
```

上面第一条是再次在线抓取的只读探针，**不要在同一存储根重复加 `--publish`**；
已发布快照不可覆盖。验收时的发布命令是在相同参数后加 `--publish`。

## 2005-01-01 至 2026-09-24 全区间：已发布

同一已发布日历快照推导预期交易日 **5279 日**；官方 H00985 API 返回 **5281
条、5281 个唯一日期**。预期日缺口为 0，额外非交易日为 2，重复日期为 0：

| 额外日期 | 官方 close | 日历结论 | 备注 |
|---|---:|---|---|
| 2005-01-01 | 984.40 | 非交易日（周六） | 官方接口仍返回一行 |
| 2018-06-18 | 5161.74 | 非交易日（端午节休市） | 前一交易日 2018-06-15 为 5161.13，不能视为简单前值重复 |

上交所[2018 年端午节休市公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20180606_4567900.shtml)
明确 6 月 18 日休市，6 月 19 日恢复交易。官方全区间探针响应 SHA-256 为
`5def4a69d92e57d7a42a567e0a28995a1698d437d5776916f0d8d1a5bb7cd863`，
初次失败探针的原始 bytes 当时未发布；批准例外后的响应哈希未变，现已作为
完整原始 JSON 发布于下述全区间快照。

初次严格探针因两条额外日期抛出 `expected trading calendar` 错误。项目负责人
于 2026-09-30 批准仅对此二日的显式隔离例外；裁决和 SHA-256 见
[`csindex-excluded-dates`](../rule-rulings/2026-09-30-csindex-excluded-dates.md)。
适配器保留完整原始响应，逐行记录结构化排除证据；其他额外日期仍硬失败。
同日再次只读探针得到预期交易日 5279、有效官方行 5279、隔离日 2，
首末日为 2005-01-04 与 2026-09-24。复核命令：

```powershell
python -m scripts.sync_csindex_benchmark --calendar-snapshot-id snapshot-2abff764afcbfb52 --start 2005-01-01 --end 2026-09-24
```

项目负责人又批准 v1 兼容编码；顶层 `data_quality_flags` 只存字符串标记，
日期及证据存 `domains.benchmark.details`。完整条文见上述裁决文件。随后发布：

- 全区间快照：`snapshot-9b72a2666190542a`，状态 `complete`，内容哈希
  `9b72a2666190542ab7fa8913023de42f7761835b3f54732ddab3ff14c803f480`。
- [meta.json](../../storage/snapshots/snapshot-9b72a2666190542a/meta.json)：
  `source_provenance.csindex.fetch_time_utc=2026-09-30T12:59:06Z`，
  `response_hash=5def4a69d92e57d7a42a567e0a28995a1698d437d5776916f0d8d1a5bb7cd863`，
  `exclusion_policy=explicit_whitelist_v1`。
- 原始官方 JSON 为 5281 行；规范化 Parquet 与独立日历均为 5279 日。
  顶层标记为 `benchmark_excluded_dates`；details 保存两日日期和各自官方点位、
  日历结论、排除理由、原始行哈希/偏移与发布时的 `v1.3.0` 规则版本。
- `verify_published_domain` 验证顶层和域内标记、日期、证据、policy 的对应
  关系；Reader 重读原始 JSON 并与规范化行及独立日历对账。2020 全年子区间
  不含任一隔离日，但返回的每条记录仍附完整例外标记、日期及结构化证据。

v1.3.1 批准后，基准 Reader 仅在此快照及上述干净区间快照各自覆盖内
转为 `ready`；Reader 根据已验证证据版本继续读取本快照的 `v1.3.0`
排除证据，不改写任何已发布 meta。其他九个生产域和真实回测编排仍
`not_ready`，本快照不构成真实回测授权。
