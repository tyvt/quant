# 万华化学：说明式引导语的有界证据条件

日期：2026-10-03。仅原文提取诊断；不是企业评估、真实 PIT 规则运行或排名，
不构成投资建议。按本地龟龟 skill 分开事实观察、解析器接纳和历史公开性。

## 实现边界

只修改 `scripts/parsing/annual_report_parser.py` 的币种证据入口与观察输出。
引导语精确限定为“人民币为本公司及境内子公司经营所处的主要经济环境中的货币”，
紧接中文逗号或句号，必须完整位于本位币小节第一原生行。共用原有唯一会计政策章节、
小节终点、同页、非旋转／不越界及标题后最多 48 点的几何约束。

引导语仅产生 `currency_intro_observation`，状态 `OBSERVED_INTRO_NOT_CURRENCY_PROOF`，
`currency_verified=false`、`public_availability_verified=false`。保存整条原生行和坐标、
PDF SHA-256、物理页及章节边界，不将其中的经济环境描述推断为直接声明。

新接纳路径只允许以下两个精确组合，且本位币小节不得再含额外正文或尾句：

1. 同一原生行：完整引导语＋中文逗号＋既有完整声明
   “本公司及境内子公司记账本位币为人民币。”。
2. 完整引导语＋句号独占一行，紧邻下一原生行完整列上述同主体声明；
   两行同页、几何完整，行间距 0—12 点，不跳行、不拼接声明。

不支持新的“以／采用／的”联合主体语序，不支持跨行主体、断句、任意主体组合、
新增境外尾句或整段拼接。旧无引导语声明路径保持原语法；主表、单位倍率、金额列、
附注、利润、租赁和审计入口未修改；没有发行人、证券、页码或金额专用分支。

## 万华新 v2：识别引导语，但不认证币种

沿用已冻结 [原输入](2026-10-03-annual-report-bundle-600309-inputs.json)，没有新网络请求。
PDF 为公告 `1223097325`，223 页，SHA-256：
`0c37e70c554609f4a22990fd97f3da4ee92bb717e44d641ac7800083789d4df7`。
同会话查看原物理 95 页图像，非第三方或整份 223 页人工复核。

新 [JSON](annual-currency-intro-600309-2026-10-03-v2/diagnostic-only.json) 绑定物理 95 页
完整引导语和原生行末尾“，本公司及境内”；保留后续跨行声明为未受支持结构。
政策起点 94 页，下一小节 95 页，政策终点 116 页。

`currency=null`、`currency_evidence=[]`，三张主表仍 `CURRENCY_EVIDENCE_UNKNOWN`，
七项目标值、比较栏及候选均未恢复。引导语观察不等于 CNY 已认证，不以源页人工值
填充。完整租赁、审计及 PIT 均 UNKNOWN；没有生成 alpha、FCF 或企业硬门结果。

| 对象 | SHA-256 |
|---|---|
| 新解析器 | `484f44080881cc71eb6e64493e36139ea1b0f90ee504d50e84122b0c37f0337a` |
| 新 v2 JSON | `4f0f27254c5ff3214acfdad7c72298a4d81ad91efe1342f9eb06b6ad40c3dfc3` |
| 新 v2 Markdown | `73412af00b066a7c6ab87a32dfcb6470018bbb0c15696f793245d71d20177bb4` |

新 `logical_content_hash`：
`8be7de7368eaf413d85b1356f463d38d855dc4469e5266c147665783e24c4df9`。
原 v1 由冻结提交 `9d160ad945a6237d844f08b5da28d670e4856512` 实际执行 CLI 重放，
原 JSON／Markdown 逐字节一致；不改写首次失败，不用新结果冒充盲跑成功。

## 验收与停止条件

新增 30 项回归，包含两个接纳组合、孤立引导语不认证、其他主体／币种／条件／示例、
冲突／重复、标点、截断、跨页、越界、旋转、间距、错误章节、跨行声明和境外尾句拒绝，
以及真实原生行绑定、旧 Git 重放、缓存确定性与禁止真实硬门导出。
五个相关测试模块共 137 项通过，耗时 12.894 秒。

`python -X utf8 -m unittest discover -s tests -q`：1171 项通过，无跳过，91.775 秒。
`scripts/verify_workspace_integrity.py` 通过：规则 SHA-256 仍为
`db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`，
538 个生产快照路径／哈希清单摘要仍为
`2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`；
历史发布记录、基准适配器／Reader 与冻结父包不变。

继续 `UNKNOWN_UNLESS_VERIFIED`，`diagnostic_available_at=null`，历史 PIT 准入 0。
本轮不追修万华其余缺口；九域／真实策略编排保持 `not_ready`，规则与生产快照不改写。
修复冻结后选择第十个未参与修复的发行人盲跑，先保存首次输出再查源页；不得更换
容易样本，不由少量选择样本推算全市场准确率。Git 不备份忽略的 `storage/` 原文。

```powershell
python -X utf8 scripts/extract_annual_report_bundle.py --scope docs/data-pilots/2026-10-03-annual-report-bundle-600309-inputs.json --output docs/data-pilots/annual-currency-intro-600309-2026-10-03-v2 --check
python -X utf8 -m unittest tests.test_annual_report_currency_intro -q
```
