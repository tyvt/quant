# 历史股本暂行保守解释：纯逻辑验收（2026-10-01）

项目负责人批准的[解释文本](../rule-proposals/2026-10-01-historical-shares-fail-closed.md)
批准前 SHA-256 为
`823b420629081066c90101dc29b41837b3f3b61bca89fb20a4ce4184563f4c9a`。
`RULE_SPEC.md` 仍为 v1.3.1；此验收不宣称历史股本域 `ready`、不产生真实研究。

实现拆分：

- `turtle_quant/core/share_capital_policy.py` 对明确输入的股类、库存股余额、
  已核实安全可用日和证据引用做纯逻辑检查。多股类、库存股非零、库存股未知、
  证据缺失/晚于查询日均返回 `UNKNOWN`，并标记缺失的 `S` 和 `MV`。
  单股类、余额确认为零且证据完整只得到“无额外政策阻断”，**不是生产 `S` 已知**。
- `ParquetSharesReader.assess_structure()` 只转发该纯逻辑检查，不读快照；
  `shares_on()` 仍抛 `NotImplementedError`。`available_on` 不是从 PDF URL 或
  公告落款猜测的日期；未来生产 Reader 必须独立核验精确 `available_at`、
  全修订链、公司行为桥接和覆盖后才能提供。
- `strategy.evaluate_universe_security()` 在收到显式股本结构证据时，
  让上述 `UNKNOWN` 覆盖调用方提供的合成 `shares_known=True` / 数值市值，
  输出 `NEEDS_REVIEW`。即使行业 Profile 同时未支持，已知股本歧义也不能被
  先行的 `NOT_SUPPORTED` 遮蔽；无歧义的未支持行业仍按原规则返回
  `NOT_SUPPORTED`。没有该额外证据的旧合成 fixture 保持原先纯逻辑行为；
  这不是生产适配器可省略结构证据的授权。
- 现有 `build_monthly_selection()` 不变：任一证券 `NEEDS_REVIEW`，整月
  `diagnostic_only=true`、无排名/权重/官方 Top-N。

合成验收包括 A/B、A/D/H、单 A 非零库存股、单 A 零库存股、缺少库存股状态、
缺证据引用、未知/未来安全可用日、错配 `as_of` 与证券身份、未支持行业优先级，
以及 Reader
仍 `not_ready`。测试：

```text
python -m unittest tests.test_share_capital_policy tests.test_strategy_selection_v13 tests.test_parquet_strategy_input_gates -v
python -m unittest discover -s tests -q
```

方向 B 的[证券池排除讨论稿](../rule-proposals/2026-10-01-universe-exclusion-options.md)
仍未批准；本验收不把 `NEEDS_REVIEW` 改成 `REJECTED` 或 `NOT_SUPPORTED`。
