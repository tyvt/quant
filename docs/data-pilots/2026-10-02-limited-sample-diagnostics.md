# 四个限定样本诊断（2026-10-02）

本轮依项目负责人接受的诊断边界执行，不是规则修订或生产域状态变更。**“法定澄清”不再作为查看原文、比较版本或限定诊断的通用前置**；未证明的年份、审计范围、公众可用时点和事件覆盖仍显式 UNKNOWN，不通过措辞变化制造规则输入。

## 本报告不宣称

- 不是官方 Top-N、真实选股结果、可发布回测或完整真实 PIT 策略运行。
- 不给出投资判断、排名、推荐顺序、权重、订单、持仓、净值或投资建议。
- 不把四只不同发行人的证据拼接成一只公司的完整输入，不接入未就绪 Reader。
- 不修改 `RULE_SPEC v1.3.2`、历史发布记录、已发布快照、基准适配器或 Reader；其他九域及真实编排状态不变。

## 冻结范围与报告入口

固定 `as_of=2026-09-30`，指请求的历史收盘截止；复核日期另记 `2026-10-02`。这两个日期是本批诊断范围的明确选择，不是声称输入在 9 月 30 日已满足 PIT。经济期间和原文公告日期逐样本另列。

| 单证券样本 | 本次输出 | 没有生成的结论 |
|---|---|---|
| [五粮液 2025 股本](limited-diagnostics-2026-10-02/shares-000858-diagnostic-only.md) | 发行股数端点、回购实施“不适用”原文、股本结构纯逻辑缺口传播 | 端点不是指定日 `S`，不证明中间逐日零事件/零库存股；`S/MV=UNKNOWN` |
| [茅台首个减资回购计划](limited-diagnostics-2026-10-02/buybacks-600519-diagnostic-only.md) | 首日执行金额、十个后续累计区间差额及证据绑定 | 不按月末/完成日分摊；不证明最后成交日；完整 `B_buyback/GG=UNKNOWN` |
| [茂化实华 2025 现金流](limited-diagnostics-2026-10-02/cashflow-000637-diagnostic-only.md) | 十二项原版/更正版/9 月归档行对照、`OCF−capex` 中间值、前提门控 UNKNOWN 传播 | 中间值不是归属 FCF；不以 9 月旧值覆盖 8 月更正；不选择声称最新可见的版本 |
| [贝因美 2022 核心科目](limited-diagnostics-2026-10-02/financial-002570-diagnostic-only.md) | 三版字段对照、毛利/算术毛利率、两组重分类差额、前提门控 UNKNOWN 传播 | 毛利不变不代表所有输入不变；空白负债非零；专项鉴证年份与整份更正后审计状态仍 UNKNOWN |

每份 Markdown 均有同名 JSON，包含单证券身份、`as_of`、输出范围、必要依赖及缺口、逐字段原始 PDF SHA-256/物理页码、逐文件目录时间、代码/规则/输入身份与逻辑内容哈希。

## 本次时点选择

使用 `UNKNOWN_UNLESS_VERIFIED`：目录 `announcementTime` 即使含非零时分秒，也不自动证明最早公众可用；本次既不假设目录日可用，也不使用“延后一个交易日即已核实”的解释。`diagnostic_available_at=null`，真实观察接纳到历史 PIT 门控的数量为 **0**。10 月抓取只证明本地复核所持原文，不能倒填 9 月历史可用时点。

原文数值仍可做版本/区间算术，不能混为完整 PIT 输入。因此本批不是“四家企业完整规则已运行”：财报样本对现有 `premise.general_fcf` 的调用只验证缺失输入传播，行业、审计、权益、六年/五年窗口等仍未知，六门均 UNKNOWN，评分不产生有效数值。股本样本对现有保守结构门控也只检查未接纳结构证据的 UNKNOWN。要求必填数值的估值函数不调用，不创建虚拟可用日期或零参数以求函数可运行。

如果以后选择日级保守延后或取得更明确的时点证据，应冻结**新的诊断范围与假设**，不能改写本批报告或把假设标成已核实 PIT。特定规则所缺的审计或事件证据仍保留，但不是证据对照的通用障碍。

单证券、部分规则的诊断不天然要求完整全市场证券池和交易能力；那些依赖属于原月度 Top-N / 成交回测的输出范围。任何拟声称真实 PIT 的数值结论，都须闭合它自身的完整必要依赖链，而不是因“个人、本地”就放宽。

## 使用与复现

公开可获取不等于无限授权。仅做已有本地证据的内部复核，不新增批量抓取，不对外分享原文/报告，不用于商业目的，不宣称已取得全市场或衍生结果授权。询证包仍暂停、未发送。

范围身份见[冻结 JSON](2026-10-02-limited-diagnostic-scope.json)。离线工具 `scripts/pilots/build_limited_diagnostics.py` 校验输入清单、目录原始 bytes、证券/公告身份、PDF bytes/物理页码和规则基线，再生成报告；没有网络请求。

```powershell
# 校验现有冻结报告，不写文件
python scripts/pilots/build_limited_diagnostics.py --check

# 如需重生成，指定尚不存在的新目录；工具拒绝覆盖
python scripts/pilots/build_limited_diagnostics.py --output-dir storage/pilots/limited-diagnostics-recheck

# 针对性回归
python -m unittest discover -s tests -p test_limited_sample_diagnostics.py -q
```

`logical_content_hash` 为排序键、UTF-8、无运行时钟的 canonical JSON SHA-256，唯一排除自身顶层哈希字段。所有代码、规则、证据、时点选择、UNKNOWN 与输出内容均在哈希范围内；同样环境、输入及代码的两次生成应得到同样 JSON 和 Markdown。确定性不证明历史输入已完整。

后续最小推进是选择某一份报告中的具体 UNKNOWN 依赖补证，而不是继续要求无边界全历史 ready，或宣称累计值/端点已覆盖每日。任何域 ready、真实策略输出授权或规则文字修订仍另走批准流程。

## 本轮验收

- 四份 Markdown 与四份 canonical JSON，绑定 24 份本地 PDF 和 81 条原文观察；全部引用文件哈希、公告身份、目录 bytes 与物理页码已验证。
- 新增 29 项针对性回归通过；`python -m unittest discover -s tests -q`：**380 项通过，无跳过**。
- 同一输入两次生成的 JSON/Markdown 内容逐字节一致；重新读取 canonical JSON 后 Markdown 顺序同样稳定，`--check` 通过。
- `RULE_SPEC.md` SHA-256 仍为 `db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`；三份历史发布记录及基准适配器/Reader 哈希均与本轮前一致。
- 538 个生产快照文件的路径/哈希清单摘要仍为 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。
- 本轮没有发布快照、修改生产 Reader、改变域状态或产生候选/排名/订单/回测；没有新增网络抓取或发送询证。
