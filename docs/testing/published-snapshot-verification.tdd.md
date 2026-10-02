# 已发布快照只读校验 TDD

日期：2026-09-29

## 范围

数据契约要求未来 Reader 只读取 complete 快照白名单，并核对内容身份、文件
哈希和域撤销。原有代码只在发布阶段校验 staging；本轮在已放行的 `storage/`
层补充 `verify_published_domain`，不解析领域数据，也不产出研究结果。

## 失败边界

测试固定以下 fail-closed 行为：

- 非法 snapshot ID、缺失快照、非 complete 或身份不一致的 meta 被拒绝；
- 内容哈希、文件 SHA-256 或域逻辑哈希不一致被拒绝；
- `meta.config` 正文与 `config_hash` 不一致、必需域与配置 steps 不一致、稳定
  来源描述不一致时被拒绝；
- 白名单路径越界、文件缺失或域元数据非法被拒绝；
- 撤销目录缺失、损坏、版本未知或 replacement 非法被拒绝；
- 已撤销域被拒绝，replacement 只出现在错误信息中，不自动切换；
- 有效域仅返回 meta 明列且已核验的文件，并以深度只读形式返回配置、来源、
  quality flags 和域 details。

## 结果

执行：

```text
python -m compileall -q turtle_quant tests
python -m coverage erase
python -m coverage run --branch --source=turtle_quant -m unittest discover -s tests
python -m coverage report -m
```

结果：140 项测试通过，源码分支覆盖率 **81%**；
`turtle_quant/storage/verification.py` 覆盖率 **90%**。

真实快照只读冒烟同时验证：

- `snapshot-a3066c7c6ab6dcd4/calendar`：20 行，通过；
- `snapshot-2abff764afcbfb52/chinabond_10y`：5,147 行，通过；
- `snapshot-a3066c7c6ab6dcd4/chinabond_10y`：按撤销目录拒绝，并报告显式
  replacement `snapshot-2abff764afcbfb52`。

## 2026-09-30 基准域补充

`verify_published_domain(..., "benchmark")` 额外校验 v1 顶层字符串标记
`benchmark_excluded_dates`、域内同名标记与 details 的非空日期严格对应；
逐项结构化证据和 `source_provenance.csindex.exclusion_policy` 必须存在且匹配。
合成快照测试覆盖标记缺失、日期缺失、证据缺失、证据日期不符及 policy 缺失；
真实 `snapshot-9b72a2666190542a` 通过。Reader 还会与原始响应、独立日历和
Parquet 规范行复核。原上节的 140 项及覆盖率是 2026-09-29 的历史记录，
不代表本次全套测试数。

v1.3.1 生效后，Reader 按已验证排除证据的版本表区分旧快照 `v1.3.0` 与
新发布证据 `v1.3.1`；无例外旧快照无需虚构版本。未知版本、请求区间外行
和白名单外额外日期继续硬失败，历史原始快照及 meta 不改写。
