# 量化选股

一个以规则规范、历史可见数据和可复现计算为优先的量化研究项目。

当前规则版本为 v1.3.2，包含离线领域计算、fixture 测试、不可变真实数据快照、
已通过验收的阶段 A Parquet Foundation Reader，以及通用 FCF 企业前提、行情位置、
证券池、组合和回测的纯逻辑实现。财务、行业、历史股本、证券状态、交易能力、
公司行为和历史费率等九个生产域仍未就绪。H00985 基准 Reader 仅在已验收
快照覆盖内 ready；因此仍不产生真实选股或可发布回测业绩，也不提交真实订单。

## 文档

- [架构](ARCHITECTURE.md)：模块边界、PIT、复权与可复现性。
- [规则规范](RULE_SPEC.md)：当前规则版本、公式、变量字典、fixture、变更管理和 `ready_when`。
- [架构修订计划](量化架构修订计划.md)：实施范围和验收标准。
- [数据落库契约](docs/data-ingestion-contract.md)：原始 schema、快照生命周期、PIT 边界和质量门槛。
- [财报与事件样本探针](docs/data-pilots/2026-09-24-finance-events.md)：阶段 B 字段证据与阻塞项。
- [财报字段矩阵 B1.1](docs/data-pilots/2026-09-25-financial-statements-b1.md)：九个固定样本、报表范围证据、向前观察修订链和生产阻塞项。
- [财报法定 PDF 修订链探针](docs/data-pilots/2026-10-01-financial-revision-000637.md)：茂化实华 2025 年报原版/更正版及经营现金流变更的点时边界。
- [财报单年度公告链复核](docs/data-pilots/2026-10-01-financial-year-chain-000637.md)：原版审计、重列报表与后续再次归档的修订/时点阻塞。
- [法定 PDF 探针工具边界](docs/data-pilots/README.md)：页级相似度仅用于筛查；经验阈值、目视核对与法定版本证明不可混淆。
- [财报再次更正法定公告候选](docs/data-pilots/2026-10-01-annual-recorrection-candidate-000662.md)：已固定 000662 三版年报、两份更正公告及原审计；精确披露时点和平台撤回/替换关系仍未闭环。
- [三域公开法定证据限定续查](docs/data-pilots/2026-10-01-public-evidence-gaps-followup.md)：保荐书未补足目标重审说明，年报注销总量和股本端点不能替代逐日流水/登记。
- [核心财务科目多次更正探针](docs/data-pilots/2026-10-01-core-financial-recorrection-002570.md)：固定贝因美 2022 年报三版和两轮利润表/资产负债表更正，隔离专项鉴证年份歧义；尚非完整 PIT 链。
- [贝因美公开澄清与详情续查](docs/data-pilots/2026-10-02-002570-public-clarification-followup.md)：固定当前公告详情和后续年度审计对象；空检索、比较期重列和详情时间均不升级为完整 PIT/目标年度重审证明。
- [四个限定样本诊断](docs/data-pilots/2026-10-02-limited-sample-diagnostics.md)：固定单证券/as_of/输出范围，保留原文算术与 UNKNOWN，记录时点选择及不宣称边界；不生成候选、排名或回测。
- [茂化实华单字段补证](docs/data-pilots/2026-10-02-minority-equity-000637.md)：固定两版年报的期末少数股东权益，核对列与表格范围；只关闭原文数值缺口，历史 PIT/FCF 仍 UNKNOWN。
- [分红支付事件 B2](docs/data-pilots/2026-09-25-dividends-b2.md)：三方交叉验证、后续支付完成修订、PIT 可用日和分类阻塞项。
- [固定分红普通性复核](docs/data-pilots/2026-10-01-dividend-ordinary-600000.md)：以双 PDF 法定证据验收浦发银行一笔年度基础现金分红；全窗口 `D` 仍 UNKNOWN。
- [回购累计事件化 B3](docs/data-pilots/2026-09-25-buybacks-b3.md)：法定进度证据、累计差分、注销核验和区间日期阻塞项。
- [回购首日精确执行探针](docs/data-pilots/2026-10-01-buyback-first-day-600519.md)：一笔法定逐日执行与残余区间对账；回购生产域仍未就绪。
- [回购单计划公告链探针](docs/data-pilots/2026-10-01-buyback-plan-chain-600519.md)：计划、价格调整与全部已取累计观察可对平，但无法重建所有实际执行日。
- [中上协行业分类定期 PDF 探针](docs/data-pilots/2026-10-01-industry-periodic-capco.md)：两期官方代码表及历史附件身份/可用日的点时阻塞。
- [历史股本来源预审](docs/data-pilots/2026-10-01-historical-shares-source-audit.md)：现有字段缺口、法定公告候选来源与待裁决的点时探针。
- [一沪一深历史股本 PDF 点时探针](docs/data-pilots/2026-10-01-historical-shares-pit-probe.md)：固定原始证据、核对股数桥接、隔离未知时点和多股类口径。
- [单股类股本年度公告链探针](docs/data-pilots/2026-10-01-shares-year-chain-000858.md)：五粮液 2025 年前后股份端点与回购披露核对，逐日 `S` 仍未知。
- [历史股本暂行保守解释](docs/rule-proposals/2026-10-01-historical-shares-fail-closed.md)：多股类与非零库存股的 `S/MV=UNKNOWN`；[证券池排除方向 B](docs/rule-proposals/2026-10-01-universe-exclusion-options.md)仍是未批准讨论稿。
- [股本、回购、财报来源可行性复核](docs/data-pilots/2026-10-01-priority-source-feasibility.md)：核对结构化候选接口、法定披露的能力边界、许可限制和三域最小验收包；生产状态不变。
- [三域限定证据范围](docs/data-pilots/2026-10-01-bounded-evidence-scope.md)：固定三只既有样本的日期、字段、验收缺口和停止条件；三条异证券链不能组成真实策略运行。
- [三域来源询证包（已暂停，未发送）](docs/data-pilots/2026-10-01-three-domain-evidence-requests.md)：保留点时、零事件、逐日流水、审计与许可的证据缺口；不代表已联系或获授权。
- [个人使用与生产级策略严谨性](docs/rule-proposals/2026-10-01-personal-use-production-rigor.md)：区分本地使用场景和策略证据门槛，保持 PIT、完整性与 UNKNOWN；[此前拟放宽的草稿](docs/rule-proposals/2026-10-01-personal-research-profile-draft.md)已撤回。
- [策略完备确认门槛](docs/strategy-completion-gates-2026-09-25.md)：当前可验证基线、v1.2.0 推荐语义和后续策略缺口。
- [阶段 A Parquet Reader 实施与验收规格](docs/stage-a-parquet-reader-spec-2026-09-29.md)：快照映射、强类型边界、冻结语义和验收矩阵。
- [RULE_SPEC v1.2.0 已批准修订](docs/rule-proposals/v1.2.0-exact-amendment.md)：已生效的完整条文、模块状态与迁移结论。
- [RULE_SPEC v1.3.0 已批准修订](docs/rule-proposals/v1.3.0-general-fcf-strategy.md)：已生效的企业前提、排序、组合、成交、成本与回测精确批准包。
- [RULE_SPEC v1.3.1 基准域修订](docs/rule-proposals/v1.3.1-benchmark-ready.md)：H00985 限定范围 ready、两日例外与历史快照兼容；批准文本身份见[发布记录](docs/releases/v1.3.1.md)。
- [Parquet PIT Reader 接口测试](docs/testing/parquet-pit-interface.tdd.md)：旧聚合接口和未就绪财务域的显式失败保证。
- [阶段 A Parquet Foundation Reader 测试](docs/testing/stage-a-parquet-foundation.tdd.md)：强类型、覆盖问题、PIT、过滤下推、Manifest 与真实快照验收。
- [已发布快照校验测试](docs/testing/published-snapshot-verification.tdd.md)：内容身份、文件哈希、撤销目录和真实快照冒烟。
- [v1.3.0 策略纯逻辑黄金验收](docs/testing/v13-strategy-golden.tdd.md)：日历、点时、成交、公司行为、内容哈希和未就绪生产域。
- [H00985 官方基准只读适配器验收](docs/testing/csindex-benchmark-adapter.tdd.md)：官方 JSON 身份、响应哈希、日历对账和生产阻塞项。
- [H00985 快照与全区间对账](docs/testing/csindex-benchmark-snapshot-2026-09-30.md)：已发布的 2005–2026 全区间、5279 日 Reader 复核和两日排除证据。
- [H00985 纯技术联调](docs/testing/benchmark-technical-integration-2026-10-01.md)：合成策略 × 已验收真实基准、边界断言和不可发布标记。
- [历史股本暂行解释纯逻辑验收](docs/testing/share-capital-interim-policy-2026-10-01.md)：多股类/库存股 UNKNOWN、整月诊断及生产 Reader 继续阻断。
- [H00985 两日显式排除裁决](docs/rule-rulings/2026-09-30-csindex-excluded-dates.md)：仅隔离两个已批准日期，以 v1 兼容编码保留顶层标记及逐行证据。

## 术语边界

### 研究筛选

研究筛选根据截至某个 `as_of` 的数据计算规则状态、估值结果和证据。它不是交易建议、回测业绩或订单。

### 回测策略

只有明确了证券池、信号时点、权重、调仓、成交价格、成本、税费、停牌、涨跌停、退市和公司行为规则后，结果才可称为回测策略。

### 人工下单建议

人工建议建立在已验证的研究筛选和可复现组合规则之上；当前仅能由合成 fixture
生成离线订单计划，不生成真实订单或自动执行交易。

## 本地运行

本地 Git 不等于异地备份：代码/规则/文档已纳入版本控制，根目录 `storage/` 的原始 PDF/Parquet
仍需独立备份。已提交 [538 文件快照哈希清单](docs/audits/storage-snapshot-manifest-2026-10-02.json)
用于检出变化，不能恢复原始数据；尚未创建远程或异地备份。

先保存代码提交，再运行 [Git 恢复与端到端诊断](docs/testing/diagnostic-e2e-2026-10-02.md)：

```powershell
python -X utf8 scripts/verify_workspace_integrity.py
python -X utf8 scripts/pilots/run_diagnostic_e2e.py
python -X utf8 scripts/pilots/run_diagnostic_e2e.py --check
```

这是纯技术验收，不补新字段、不授权真实选股或回测；默认输出目录必须不存在。

领域核心仅使用 Python 标准库：

```bash
python -m unittest discover -s tests -v
```

真实数据同步使用可选依赖：

```bash
python -m pip install -e ".[sync]"
python scripts/sync_local_data.py --help
```

同步产物写入仓库根 `storage/`，不纳入版本控制。只有
`storage/snapshots/<snapshot_id>/meta.json` 声明的 complete 快照可被读取。
财报 B1.1、分红 B2 和回购 B3 夹具只用于契约测试，不属于 complete
snapshot，也不得进入研究。

## 状态语义

- `PASS`：规则通过。
- `FAIL`：规则失败。
- `UNKNOWN`：数据或证据不足，绝不等于零。
- `NEEDS_REVIEW`：可以输出有限研究结果，但不能视为正常通过。
- `NOT_APPLICABLE`：该规则不适用于当前 Profile。
- `NOT_SUPPORTED`：当前版本尚未实现该行业或能力。

具体公式、单位和变更流程以 `RULE_SPEC.md` 为准。
