# 通用批量硬门入口：纯技术验收

日期：2026-10-03。实施范围：离线工具、既有纯逻辑和合成 fixture。
规则基线为 v1.3.2，SHA-256 为
`db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`。

## 本次交付与不宣称

入口为 `scripts/run_batch_screening.py`，共用模块位于 `scripts/screening/`。
不新增生产 `screening/` 域或修改 `ready_when`，不接入未就绪 Reader。
仅接受 `SYNTHETIC_FIXTURE` 输入；本次没有全市场真实筛选、真实 PIT 规则运行、
正式候选、排名、订单、权重、持仓、净值或投资判断。

本地龟龟 skill v0.4.0 的“企业前提与机会资格分开”用于工作流分层。
硬门通过仅表示可以投入下一步详细分析，不表示机会资格已通过。
实际阈值和状态仍来自本仓库已批准逻辑，未复制外部 Tier 1/Tier 2 门槛。

## 执行链与三条工作队列

输入证券全集 + 同一 `as_of` → 基础筛选 → 六项企业硬门 → 工作队列。

| 工作队列 | 条件 | 后续 |
|---|---|---|
| `PASSED` | 基础 ELIGIBLE 且六门全部 PASS | 可进入详细分析，尚非正式候选 |
| `STOPPED` | 明确基础拒绝、无阻断 UNKNOWN 的企业 FAIL，或范围不支持 | 停止追加详细工作；范围不支持另有标记，绝不是财务 FAIL |
| `NEEDS_EVIDENCE` | 基础 NEEDS_REVIEW、财务输入缺失、任一阻断 UNKNOWN | 集中待补证；同时保留已有 FAIL |

同时存在企业 FAIL 和 UNKNOWN：队列仍为 `NEEDS_EVIDENCE`，
`premise_status=NEEDS_REVIEW`，保留逐门 FAIL/UNKNOWN，
`stop_additional_deep_work=true`。这是工作安排，不改变正式规则终态。
该入口不调用 `decide()`，也不伪造 Coverage/GG 来获得 CANDIDATE。

基础筛选直接复用 `evaluate_universe_security`：主板身份、上市 504 交易日、
支持的行业 Profile、证券状态、市值至少 50 亿元、最近 60 个独立给定日期的
行情/交易证据，其中至少 50 个可交易成交额、中位数至少 2000 万元。
基础筛选不需要财报，但仍需要点时股本、市值、行业、状态及流动性证据；
“没有财报依赖”不等于“已有生产输入”。多股类/库存股 UNKNOWN 和现行优先级不变。

基础状态非 ELIGIBLE 时，企业阶段明确 `NOT_RUN`，绝不伪装为六门通过。
原基础状态、原因与证据引用保留。企业阶段直接复用 `evaluate_general_fcf`，
一次计算六门，按 profile → equity → integrity → ROE → FCF → leverage 展示。
这个展示顺序不是新的短路算法；六门计算很轻，不为节省算术更改状态优先级。
ROE 仍需五年利润和六个连续年末权益；完整租赁现金仍不得用负债余额/部分现金/零代替。

每个请求 ID 都有结果。缺少输入记录不会被悄悄删除，进入待补证。
`--batch-size` 只控制工作分批，不是配额；无前 150/200 个截断。
证券列表和报告按证券代码排列，绝不是推荐顺序。

## 输入契约

JSON 顶层只允许五个字段：

| 字段 | 含义 |
|---|---|
| `schema` | 固定 `synthetic-batch-hard-gates-v1` |
| `data_kind` | 固定 `SYNTHETIC_FIXTURE`，其他类型硬失败 |
| `as_of` | ISO 日期，同一批共用 |
| `security_ids` | 唯一的规范证券 ID 全集，可以为空；不截断 |
| `inputs` | `{security_id, basic, financial}` 对象数组；basic/financial 可显式 null |

`basic` 的字段就是既有 `UniverseInput`，`financial` 就是 `GeneralFCFInputs`
（不允许配置评分权重）；年度记录使用 `AnnualFinancialObservation`。
金额必须为十进制字符串，日期为 `YYYY-MM-DD`，布尔字段只接受 true/false/null，
未知金额明确 null，绝不转成零。所有必需字段必须存在，未知配置/重复 JSON 键、
浮点/非有限数值、证券/as_of/Profile 跨层冲突、重复证券/修订排序键冲突均硬失败。
整批先验证绑定关系，即使某证券基础筛选会停止，也不能隐藏输入身份冲突。

财务类型本身没有证券 ID，因此通过外层 `security_id` 绑定；这只解决合成输入的
接口绑定，不认证 PDF 发行人或原文版本。`data_kind` 是调用契约，不是证据认证；
不得把真实数据改标签伪装成合成验收。未来真实接入仍需来源、版本、PIT 与范围验收。
未知历史可用时点不得补造 `available_at` 来凑年度记录；真实证据诊断仍使用既有工具。

## 确定性、缓存与集中补证

- `input_content_hash` 包含规范化证券全集、as_of 和所有输入（含证据与未知）。
- `logical_content_hash` 为 UTF-8 canonical JSON SHA-256，排除且仅排除自己的
  顶层哈希字段；规则/代码哈希、队列、逐门状态和缺口都在范围内。
- 输入记录/年度观察排列、执行分批大小、冷/热缓存不影响逻辑内容。
  金额字符串精度不强行归一化；没有运行时钟。
- 进程内缓存键绑定证券、as_of、全部输入、规则与实现身份。新增一个证券字段，
  只使该证券的计算缓存失效。返回结果采用防御性复制，不能反向污染缓存。
- 会话中实现文件变动硬失败，要求重启，不给已加载旧代码贴新代码哈希。
  规则文件不匹配冻结基线直接硬失败。
- `evidence_backlog` 按阶段/规则/缺口汇总证券，是待补证索引，不自动搜索来源。
- 缓存仅限当前进程的筛选计算，**不是**持久化 PDF 解析缓存。通用 PDF 整组提取、
  内容哈希解析缓存和真实公告增量依赖图仍属下一阶段，不在本次宣称完成。

## 使用与验收

全部数据、证券经济属性、证据及日历均为合成；演示日期串不是真实交易日历。
默认不使用任何真实公司 PDF 或快照。输出目录必须不存在，旧报告不覆盖。

```powershell
python -X utf8 scripts/run_batch_screening.py --demo --batch-size 2 --output storage/diagnostics/batch-hard-gates-2026-10-03-v1
python -X utf8 scripts/run_batch_screening.py --demo --batch-size 1 --output storage/diagnostics/batch-hard-gates-2026-10-03-v1 --check
python -X utf8 scripts/run_batch_screening.py --input <合成输入.json> --output <新的报告目录>
python -X utf8 -m unittest discover -s tests -p test_batch_hard_gate_screening.py -q
python -X utf8 -m unittest discover -s tests -q
```

无 `--output` 时输出 canonical JSON；带输出时生成 `diagnostic-only.json/.md`。
每次 CLI 都比较冷运行/热缓存的不同分批结果；`--check` 还逐字节核对已生成报告。
Python 调用可使用 `BatchRunner().run(request)`，同一 runner 可跨批复用计算缓存。
合成输入格式可从 `demo_request().normalized()` 获取。

验收包括：三队列、范围不支持不变 FAIL、缺输入不丢证券、205 只不截断、
UNKNOWN 与 FAIL 并存、现行股本解释、60/50 流动性边界、六年权益、未来/无证据财务
拒用、既有引擎逐门一致、集中缺口、单证券缓存失效、防污染、代码/规则身份漂移、
严格 JSON、覆盖拒绝、CLI 重跑，以及旧诊断和保护文件的完整性检查。

本批报告永远诊断用，`whole_month_eligibility=NOT_EVALUATED`；
即使合成样本全通过，也不证明完整证券池、整月完整性或真实排名权限。
其他九个生产域、真实策略编排与现行整月诊断门槛均未改变。

## 本轮实测记录

- 新增 52 项回归通过；完整 `unittest discover -s tests -q`：744 项通过，无跳过。
- 五只合成证券：通过 1、停止 2（已知 FAIL 1、NOT_SUPPORTED 1）、待补证 2。
  另有 205 只全通过样本证明不按 150/200 截断。
- 冷/热缓存、不同分批大小、输入顺序、canonical JSON 重新读取后的 Markdown
  均保持内容一致，演示 `--check` 通过。
- 本轮演示报告 `logical_content_hash`：
  `5e4d70aea4806bbdecbb4522efb331838b733b01e6ad0cfe8e72f0f7976fe590`。
  生成文件位于本地忽略目录 `storage/diagnostics/batch-hard-gates-2026-10-03-v1/`，
  不冒充 Git 已备份这些文件；提交的代码与规则可重建全部合成报告。
- 五年依赖清单及旧端到端诊断 `--check` 通过；538 个生产快照路径/哈希摘要
  仍为 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`，
  规则、历史发布记录、基准适配器/Reader 及保护诊断未改写。
- 之前未完成的 2021 公告时点探针文件不纳入本次提交，不改写、不重启搜索。
