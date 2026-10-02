# 初始核心实现：TDD 证据报告

## 范围

来源计划：[量化架构修订计划](../../量化架构修订计划.md)。

本轮只实现 `RULE_SPEC.md` 中状态为 `ready` 的核心契约、绝对估值、穿透回报、决策聚合和 fixture PIT Reader。真实数据源、行情定位、企业前提、行业专用模型、组合与回测仍不在本轮范围内。

## 用户旅程与保证

- 作为研究者，我可以用完整 fixture 计算六年回本、Coverage、Payback、GG 和三个价格档位。
- 作为回测使用者，我只能读取在 `as_of` 时已可见的财务版本，历史退市证券不会从历史股票池消失。
- 作为规则维护者，缺字段得到 `UNKNOWN` 或 `NEEDS_REVIEW`，不会被填成 0 或正常通过。
- 作为实施者，未就绪的行情模块只抛出 `NotImplementedError`，不会生成猜测性结论。

## RED 证据

以下测试均在相应实现存在前执行并失败：

- `python -m unittest discover -s tests -v`
  - 初始失败：`ModuleNotFoundError: No module named 'turtle_quant'`。
  - 行情 stub 测试失败：`ModuleNotFoundError: No module named 'turtle_quant.market'`。
  - 审查修复测试失败：验证了可变 Mapping、缺失 `delta_base_reason` 和 PIT 同修订键歧义。

这些失败分别证明测试确实引用了缺失的领域实现、未就绪接口和审查指出的边界行为。

## GREEN 证据

已实际执行：

```text
python -m unittest discover -s tests -v
```

最终结果：`Ran 30 tests ... OK`。

已实际执行：

```text
python -m compileall -q turtle_quant tests
```

最终结果：退出码 `0`。

已读取 IDE 诊断：`turtle_quant/` 与 `tests/` 均无 linter error。

## 测试保证

- `test_calculates_reference_coverage_and_payback`：固定 D 组基线算例的 `Coverage6=1.03`、`Payback=5.8125` 和参考价格。
- `test_calculates_shared_capacity_and_price_ladder`：股息优先、回购使用剩余容量、GG 及 Observe/Heavy/Standard 价格。
- `test_rolls_dividends_left_open_and_buybacks_closed_at_start_boundary`：D 的左开右闭 365 日窗口与回购的含端点窗口不同。
- `test_qualifies_sustained_buybacks_with_year_coverage_cap`：合格回购取 365 日执行额和最近完整自然年金额的较小值。
- `test_sustained_buyback_window_is_exactly_three_times_365_days`：跨闰年时仍按冻结规则使用精确 `3×365` 日窗口，而不是三个自然年。
- `test_missing_calendar_year_coverage_keeps_buybacks_unknown`：缺少年度覆盖不被填为零。
- PIT 测试：未来记录不可见、最新可见修订被选中、相同可见修订键被拒绝、历史退市证券被保留。
- 决策测试：硬门失败、未知证据优先、估值不达标、评分不完整和不支持 Profile 的输出。
- 不可变性测试：财务记录、运行清单、估值覆盖结果不能通过可变容器被改写。
- `test_manifest_round_trip_and_hash_are_deterministic`：运行清单可 JSON 往返；数据源字典、快照 ID、质量标记的顺序以及等价 Unicode 规范化形式均不影响内容哈希、对象相等性或 Python 哈希；含时间的 `datetime` 不能伪装成 `as_of` 日期。
- 规范边界测试：固定 Decimal 上下文、FCF 零值例外、未知输入、未就绪行情模块。

## 覆盖率与已知限制

已尝试：

```text
python -m coverage --version
```

结果：环境未安装 `coverage` 模块，因此本轮无法生成百分比覆盖率报告，不能声称已验证 80% 覆盖率。单元测试、编译检查和 IDE lint 已完成。引入正式 CI 前，应安装并配置覆盖率工具及阈值。

未覆盖的后续范围包括真实数据适配器、公司行为因子、行情位置、企业前提、行业专用 Profile、证券池和回测交易状态机。
