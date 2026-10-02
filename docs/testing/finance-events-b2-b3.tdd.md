# 分红与回购样本 B2/B3：TDD 证据

## RED 证据

分红与回购均先加入不可变夹具和契约测试。首次运行分别得到：

```text
ModuleNotFoundError: No module named 'turtle_quant.adapters.dividend_samples'
ModuleNotFoundError: No module named 'turtle_quant.adapters.buyback_samples'
```

随后加入领域 UNKNOWN 测试，旧聚合器暴露两类缺陷：未知布尔状态被过滤后
返回零；未知日期或金额直接触发 `TypeError`/`ValueError`，而不是传播
UNKNOWN。

补充后续支付完成证据时，测试先因缺少
`normalize_dividend_sample_revisions` 导入失败；实现独立 PIT 修订后转绿。

## GREEN 证据

- 分红样本定向测试：9 项通过；
- 回购样本定向测试：8 项通过；
- 穿透回报事件聚合定向组与两类样本合计：29 项通过；
- 本阶段完成时全量：124 项通过；源码分支覆盖率 **80%**。随后接口脚手架阶段
  增至 126 项，其中新增两项仅验证未就绪 Parquet PIT Reader，不改变本阶段结果。

执行命令：

```text
python -m compileall -q turtle_quant tests
python -m coverage erase
python -m coverage run --branch --source=turtle_quant \
  -m unittest discover -s tests
python -m coverage report -m
```

## 测试保证

- 分红三方身份、日期、每股金额、股本和总额必须一致；
- 实施进度、普通股股份类别和已过去的预定支付日不会自动生成 `D`；
- 后续发行人报告明确确认实施完毕时，只从该报告可用日建立
  `is_paid=TRUE` 修订，不回填预定支付日；
- 窗口内相关分红未知值传播为 UNKNOWN，明确排除项与窗口外事件不污染结果；
- 回购累计状态必须单调，同截止日冲突拒绝，同值重复证据折叠；
- 七个回购区间增量可精确回加到最终累计金额与股数；
- 东财计划日期和公告日期不会伪装成执行日期；
- 注销股数必须与最终累计股数及注销前后股本桥接同时一致；
- 回购相关未知日期、金额、执行状态或注销状态传播为 UNKNOWN；
- 两类样本都固定为非研究可用，不接入同步 CLI 或 Reader。
