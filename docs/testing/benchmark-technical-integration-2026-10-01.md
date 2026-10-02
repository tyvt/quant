# H00985 基准纯技术联调（2026-10-01）

**性质：纯技术联调；不是生产策略运行、真实选股、真实回测或可发布绩效。**
本记录不修改 `RULE_SPEC v1.3.1`，不提升其余九个生产域的状态，也不发布新快照。

## 边界与输入

- 唯一真实生产数据是已验收的 H00985 全历史基准快照
  `snapshot-9b72a2666190542a` 及其绑定的日历快照
  `snapshot-2abff764afcbfb52`。只查询覆盖范围内日期；不请求外部接口。
- 2025-01-27 是夹具信号日；首个成交日按已核实日历推导为
  2025-02-05，评估截止 2025-03-31。证券、六年财报、历史股本已知性、
  流动性、股票开收盘、交易能力、20 日成交额、税费表和无风险利率**全是合成
  fixture**，不能混称为真实市场或真实财务数据。
- 策略配置、订单引擎与 `StrategyRunManifest.rules_version` 保持冻结的
  `v1.3.0` 纯逻辑契约；`v1.3.1` 仅为所用基准 Reader 的批准版本。
  `benchmark_snapshot_id` 显式写入策略 Manifest，基础 `RunManifest` 包含同一
  benchmark/calendar 快照 ID 和 `TECHNICAL_INTEGRATION_ONLY` 标记。
- 夹具可以让指标计算器返回 `complete=True`（表示本段合成 NAV 与真实基准
  在日期上完整），但 Manifest 的 `completeness_summary.complete` 与
  `production_ready` **均为 false**。缺失的九个生产域未因此获得授权。
  测试不写订单、净值或绩效文件，不输出可发布绩效数值。

## 验收断言

`tests/test_benchmark_technical_integration.py` 以已发布快照进行只读联调：

1. 合成年度财务经 `premise/` 与 `valuation/` 产生
   `CANDIDATE`、`REJECTED`、`NOT_SUPPORTED`、`NEEDS_REVIEW`；证券池
   的 60 日流动性窗口以真实日历日期承载合成金额。任何
   `NEEDS_REVIEW` 使整月仅有无排名、权重、订单或净值的诊断记录。
2. 另一组完全合成且无待复核样本的内部选择，仅用于演练下一交易日订单、
   逐日成交、持仓和 NAV；其 API 内部 `official_selection=True` **不表示
   可对外发布的官方结果**。
3. 实际 H00985 日值与合成 NAV 使用同一交易日序列；CAGR、波动率、
   Sharpe、超额 CAGR、跟踪误差及信息比率由现有计算器计算，断言可计算
   而不发布数值。删去一个真实基准日期时，相关基准指标为 UNKNOWN，
   不以前值填补；缺合成利率时 Sharpe 为 UNKNOWN。少于两个日收益或
   分母为零时，对应指标保持 UNKNOWN。
4. 重复相同合成输入的订单/持仓/NAV `logical_content_hash` 与 canonical
   `StrategyRunManifest` 完全相同；其 `base_run_manifest_hash` 等于基础
   `RunManifest.content_hash()`，并冻结真实 `benchmark_snapshot_id`。
5. 非空的 2020 年子区间仍携带完整两日例外标记、日期和证据；无交易日
   子区间从 Reader 属性读取完整快照级状态；超快照区间硬失败。两个
   已验收快照均由各自 meta 绑定已发布日历 ID，查询时继续使用该 ID。
   Reader 对未经批准的例外证据版本硬失败，测试仅伪造校验结果以隔离
   此检查，**不修改真实快照**。白名单外额外日期、白名单日期重复和
   官方点位漂移继续由既有 `test_csindex_benchmark_exclusions.py` 覆盖。

运行：

```text
python -m unittest tests.test_benchmark_technical_integration -v
python -m unittest discover -s tests -v
```

本地执行结果：上述联调 4 项通过；全量回归 268 项通过。

## 后续

基准域只在两个获批快照各自覆盖区间内 ready。真实策略编排仍须等待其余
九域逐一通过生产验收；历史股本来源与点时总股数/公司行为桥接是下一项
独立阻塞，不得用现值或复权因子反推历史。此联调不改变这些门槛。
