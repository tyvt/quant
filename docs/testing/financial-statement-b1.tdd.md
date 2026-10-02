# 财报样本契约 B1.1：TDD 证据

## 范围

本轮实现九个固定财报样本的纯规范化、不可变夹具、字段矩阵、逐样本范围
证据，以及不冒充供应商版本号的向前观察修订链。没有新增网络适配器，也
没有接入同步 CLI、complete snapshot 或 Parquet PIT Reader。

## RED 证据

原 B1 首次执行：

```text
python -m unittest tests.test_financial_statement_samples -v
```

初始结果为 `ModuleNotFoundError: No module named
'turtle_quant.adapters.financial_statement_samples'`。后续边界测试还捕获到
币种校验缺陷：Python 的 `str.isalpha()` 会把“人民币”视为三个字母，
实现因此改为只接受 `[A-Z]{3}`。

B1.1 先加入范围证据和失败测试；旧实现对 `statement_scope` 参数报
`TypeError`，夹具哈希也因证据变更而失败。实现明确的范围校验和动态阻塞
原因后转绿。

后续补齐浦发银行与邯郸钢铁六个样本的法定范围证据时，先加入“九个样本
范围均已核实”的测试；旧夹具对六个子测试均返回 `None`，随后以发行人/巨潮
原文逐页核对后转绿。

## GREEN 证据

初次 B1.1 定向测试：20 项通过。补齐全部范围证据后：21 项通过。

全量执行：

```text
python -m compileall -q turtle_quant tests
python -m coverage erase
python -m coverage run --branch --source=turtle_quant \
  -m unittest discover -s tests
python -m coverage report -m
```

结果：100 项测试通过；源码分支覆盖率 **82%**；
`financial_statement_samples.py` 覆盖率 **96%**。

## 测试保证

- 九个真实样本共输出 52 条科目记录；
- 夹具内容由固定 SHA-256 约束；
- 当前/退市、银行/通用、三种报表使用各自字段矩阵；
- 非 `UNKNOWN` 范围声明必须携带明确证据引用；
- 九个固定样本均有逐表范围证据：六个 `CONSOLIDATED`、三个 `PARENT`；
- 合并和母公司范围不会进入同一修订链；
- 所有数值为有限 `Decimal` 或 null，不保留 float；
- null/NaN 映射为 `UNKNOWN`，不补零；
- `SECUCODE` 与 `SECURITY_CODE` 不一致时拒绝；
- 非法日期、报告期、币种、接口和公司类型均拒绝；
- 公告日未知具体时刻时，候选可用日必须是后续交易日；
- 最新重述值的 `available_at` 固定为首次观察时点，不能回填公告日；
- 同一观察时点的冲突内容拒绝，连续相同内容折叠，内容恢复创建新片段；
- 本地观察序号不会写入 `provider_revision_sequence`；
- 所有记录仍不可用于研究，直到修订语义和生产 PIT 链完成。
