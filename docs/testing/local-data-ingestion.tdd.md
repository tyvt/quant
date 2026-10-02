# 本地数据落库 TDD 证据

## 来源与用户目标

来源计划：`本地数据落库执行_36875f5a.plan.md`。

用户目标：

1. 不使用 Tushare，将免费多源数据保存为不可变本地快照。
2. 断点续跑不得污染 complete 快照。
3. 真实数据在 PIT Reader 就绪前不得进入研究/回测结论。
4. 不可靠的日期、事件或缺失值必须保持 UNKNOWN，而不是零或通过。

## RED / GREEN 记录

| 行为 | RED 证据 | GREEN 证据 |
|---|---|---|
| 快照身份、锁、partial/complete、checkpoint | `python -m unittest tests.test_storage_snapshot tests.test_ingestion_contract -v`：缺少 `turtle_quant.storage/adapters`，2 个导入错误 | 同命令：17 项通过 |
| StockDB/Baostock/中债/Parquet 适配 | `python -m unittest tests.test_foundation_adapters -v`：缺少 `baostock_adapter` | 同命令：9 项通过 |
| 同步编排与内容发布 | `python -m unittest tests.test_sync_runner -v`：缺少 `storage.sync` | 同命令：通过 |
| CLI 的日期边界与零证券限制 | `python -m unittest tests.test_sync_cli -v`：缺少 `storage.cli` | 同命令：3 项通过 |
| batch 路径穿越、历史板块有效期 | 三项定向测试均按预期失败 | 修复后同三项均通过 |
| 行情证券覆盖率门槛 | 缺失一只证券行情时测试未报错 | 加入版本化覆盖率后测试通过 |
| Baostock 登录瞬时失败 | 构造参数不存在，测试报错 | 三次有界重试测试通过 |
| 父快照复用 | runner 不接受 parent 参数 | 验证内容哈希后复用测试通过 |

## 测试保证

| 保证 | 测试 |
|---|---|
| canonical JSON 键排序、NFC、禁止隐式日期 | `test_storage_snapshot.py` |
| batch ID 不含抓取时间，snapshot ID 基于内容 | `test_storage_snapshot.py` |
| 显式 batch ID 不能路径穿越 | `test_storage_snapshot.py` |
| 并发写同一批次失败，损坏分片不会被 resume 跳过 | `test_storage_snapshot.py` |
| 证券代码不猜测交易所，B 股/创业板/科创板不进主板池 | `test_ingestion_contract.py` |
| 只接收 RAW 日 K，重复主键和非有限数阻断发布 | `test_ingestion_contract.py` |
| 2004–2021 的 `002` 代码按中小板/主板有效期拆分 | `test_foundation_adapters.py`、`test_sync_runner.py` |
| StockDB 查询显式执行 `.do()`，原始价格与因子独立 | `test_foundation_adapters.py` |
| 中债 10 年值按年切片并解析为 Decimal | `test_foundation_adapters.py` |
| 必需域不完整、行情覆盖率不足时不能发布 snapshot | `test_sync_runner.py` |
| 已验证父证券主表可复用且内容哈希必须匹配 | `test_sync_runner.py` |

## 真实探针

- StockDB：5,833 个唯一证券代码；本地日 K 与 58,906 条累积复权记录可读。
- Baostock：5,559 条证券基础记录，含 337 条退市记录；交易日历可读。
- 中债：官方 `historyQuery` GET/HTML 端点可读，2024-01-01 至
  2024-01-10 返回 7 个 10 年期观测。
- 阶段 A 样本快照：`snapshot-a3066c7c6ab6dcd4`，5 只证券，五个域均
  complete；其 `chinabond_10y` 域后来发现未筛曲线名称，已在 domain
  revocation catalog 中撤销。
- 全历史行情快照：`snapshot-16de9d9c4679347d`，12,004,094 条 RAW 日 K、
  43,651 条累积复权因子，行情证券覆盖率 3,441/3,455（99.59%）。
- 全历史日历/利率快照：`snapshot-2abff764afcbfb52`，7,947 条日历记录、
  5,147 条唯一的“中债国债收益率曲线”10 年期观测；2005 年无有效值并
  显式标记 source gap，序列从 2006-03-01 开始。
- 两个生产快照的逐文件 SHA-256 与 Parquet metadata 行数复核均通过。
- 发布后修复：供应商停牌值 `"0"` 不再被当成停牌；目录改名失败可从已写好的 `meta.json` 完成发布；已退出进程留下的锁会被回收。这些修复不改变已发布快照内容。
- 阶段 B 证据见 `docs/data-pilots/2026-09-24-finance-events.md`。
- 分红 B2 与回购 B3 的 RED/GREEN 证据见
  `docs/testing/finance-events-b2-b3.tdd.md`。

## 覆盖率与已知缺口

执行：

```text
python -m coverage run --branch --source=turtle_quant -m unittest discover -s tests
python -m coverage report -m
```

本轮原始结果：72 项测试通过；`turtle_quant` 源码分支覆盖率 **80%**。

2026-09-25 加入财报 B1.1 样本契约后的全量回归为 100 项测试通过、分支
覆盖率 **82%**；新增证据见 `financial-statement-b1.tdd.md`。

同日加入分红 B2、回购 B3 样本契约及领域 UNKNOWN 传播后为 121 项测试
通过；补齐九个财报样本的法定范围证据及分红支付完成 PIT 修订后，最新全量
回归为 124 项测试通过，分支覆盖率 **80%**。新增证据见
`finance-events-b2-b3.tdd.md` 和
`financial-statement-b1.tdd.md`。

2026-09-29 加入未就绪 Parquet PIT Reader 接口失败测试后，最新全量回归为
126 项测试通过，分支覆盖率仍为 **80%**；新增证据见
`parquet-pit-interface.tdd.md`。

同日补充已发布快照内容身份、文件哈希与撤销目录的 fail-closed 校验后，最新
全量回归为 135 项测试通过，分支覆盖率 **81%**；新增证据见
`published-snapshot-verification.tdd.md`。

继续补齐配置正文哈希、稳定来源描述、深度只读 details 与质量标记后，最新
全量回归为 140 项测试通过，分支覆盖率保持 **81%**。

同日完成 v1.2.0 阶段 A Foundation Reader、强类型边界、财务独立门禁、
合成快照契约和真实快照只读验收后，最新全量回归为 **162 项测试全部通过**，
源码分支覆盖率保持 **81%**；Foundation Reader 自身分支覆盖率为 **80%**。
证据见 `stage-a-parquet-foundation.tdd.md`。

当前明确不覆盖：

- 阶段 A Foundation Reader 已实现并通过验收；旧聚合 Reader 仍为兼容 stub，证据见
  `stage-a-parquet-foundation.tdd.md`；
- 分红普通/特别分类与生产可接受的支付完成证据类型；
- 回购区间增量的精确执行日和完整自然年覆盖；
- 财报完整修订历史；
- 真实研究和回测输出。
