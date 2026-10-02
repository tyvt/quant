# Parquet PIT Reader 接口脚手架 TDD

日期：2026-09-29

## 范围

`RULE_SPEC.md` 仍将 `turtle_quant/pit/parquet.py` 标记为 `not_ready`。本轮只声明
生产 PIT Reader 的稳定边界，不读取快照、不解释财务修订、不聚合分红或回购，
也不返回空集合等容易被误认为真实结果的默认值。

## 红线

- 构造 Reader 时不得要求路径存在，也不得访问快照；
- 财务、证券主表、复权因子、行情和利率五个读取面都必须显式失败；
- 失败类型固定为 `NotImplementedError`，消息必须指向 `RULE_SPEC.md`；
- 在规则状态改为 `ready` 前，不添加任何猜测性读取或降级输出。

## 验证

`tests/test_unready_parquet_pit.py` 覆盖无快照构造和全部五个读取面。实现生产读取
前，须先批准并落盘 `docs/strategy-completion-gates-2026-09-25.md` 中的相关语义，
再将这些失败测试替换为发布快照、撤销状态、PIT 边界及修订链测试。

执行：

```text
python -m compileall -q turtle_quant tests
python -m coverage erase
python -m coverage run --branch --source=turtle_quant -m unittest discover -s tests
python -m coverage report -m
```

结果：126 项测试通过，源码分支覆盖率 **80%**；`turtle_quant/pit/parquet.py`
语句覆盖率 **100%**。

## v1.2.0 后续状态

该脚手架现在永久保留为兼容失败入口，不会静默变成 Foundation Reader。
已批准的五域阶段 A 实现、财务域独立门禁和真实快照验收见
`stage-a-parquet-foundation.tdd.md`。
