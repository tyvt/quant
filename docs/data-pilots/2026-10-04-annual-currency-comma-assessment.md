# 币种声明的逗号连接说明：有界评估，未修复解析器

范围：`as_of=2026-09-30`；2026-10-04 离线工程评估，十一家发行人、十四份固定
PDF。使用本地龟龟 skill 0.4.0 的证据、隐私与同会话自查约束，不是新样本盲跑、
第三方／第二模型复核、企业分析、选股或排名。

## 结论与范围

格力的精确逗号连接句可列为下一轮有界实现候选；本轮只观察原文形式和几何，
不推断或认证人民币本位币，不改变实际币种入口。六项白名单解析代码全部与
`f74cc1716daa65c2877c59919c9ede23c5adcacb` 一致，十四份既有三表和 `parse_annual`
整组内容也全部一致。仍为十份 CNY、四份币种阻断，格力仍 `currency=null`。

[冻结范围](2026-10-04-annual-currency-comma-assessment-scope.json)先于检索保存，绑定
前轮横杠附注父包、薄索引和十一份固定输入清单，逐项核验证券／发行人／年度／
声明版本、公告 URL／ID、PDF SHA 和物理页数。仅在当前 `_currency_section` 能定位
的会计政策本位币小节中，收集含“记账本位币”、不超过 180 字的原生词元；不拼接
词元、行或页，不 OCR，不删空白，不把逗号改为句号。既有小节定位器内部的标题
匹配和规范化路径未改，不宣称其本身是新增的严格逐字定位器。

十三份可定位小节；海螺一份为 `NOT_SCANNED_SUBSECTION_NOT_IDENTIFIED`，不自动
扩大到全文或其他章节。未扫描不等于没有相关披露或逗号变体。

## 原生形式盘点

| 词元表面形式，仅为观察 | 词元数 | 对照与限制 |
|---|---:|---|
| 精确发行人逗号＋个别子公司例外说明 | 1 | 格力，未来精确形式候选，非币种证明 |
| 发行人相关句号后接子公司上下文 | 2 | 华域、隆基；形式相近不表示入口状态相同 |
| 其他子公司／拆行上下文中的逗号 | 6 | 万华、长江、隆基、贝因美三版；不能替代发行人主句 |
| 无中文逗号的相关词元 | 12 | 含完整声明及断句／其他主体片段，不能把此类全称为已支持声明 |
| 合计 | 21 | 不是唯一声明全集、正确率分母或全市场覆盖率 |

这 21 个是本位币相关词元，不是前轮同样计为 21 的多级附注引用词元，两者不能
混作同一盘点。万华首行引导语本身不含搜索词，不在此计数中；后续原生片段保留
自身文字，不拼成新的联合主体声明。其他形式的分类只描述表面结构，不认证
主体、币种、会计含义或上下文完整性。

## 格力原文与下一项候选

格力 `sz.000651`，珠海格力电器股份有限公司，声明 2024 年报，公告
`1223330631`，248 物理页。原 PDF SHA：
`c7184706caf5f57c04a795990967cfc4f4253024e02f8bdaffe2b260df2c6006`。
本次程序取得物理 124 页本位币小节的完整原生同行：

> 本公司以人民币为记账本位币，本公司的个别子公司采用人民币以外的货币作为记账本位币。

原生词元盒 `[90.984,464.314,500.768,474.274]`。政策起点、标题和下一小节均在
124 页，政策终点在 152 页。该行是小节第一正文行、单个完整原生词元，同页、
未旋转且为原点未裁切页框，标题到正文间距处于既有有界区间。

状态 `EXACT_ISSUER_COMMA_SUBSIDIARY_EXCEPTION_LITERAL_NOT_PROOF`，
`future_exact_form_candidate=true` 仅表示本轮精确形式与几何候选；
`currency_verified=false`、`public_availability_verified=false`。v2 保存后才查看
124 页本地派生图作同会话自查，不用人工值或改标点替换程序观察。

源中逗号后的主体明确为“本公司的个别子公司”，不是第二个发行人币种声明。
这支持把完整原句作为未来单独评估的精确模式，而不支持“见逗号就截去尾句”、
任意子公司尾句、混合币种、联合主体新语序或任意跨行拼接。现有币种入口要求
受支持完整句号形式，因此仍拒绝此原句，本轮没有装入新的正向识别路径。

下一轮如实现，应另冻范围与代码：只接纳此完整原生句、完整主体和小节边界，
补错误主体、非人民币、混合币种、条件／示例／引文、缺句号、空白／标点变体、
重复或冲突发行人声明、断句、跨页、旋转／裁切与错误政策范围的逆向测试。
本轮候选的形式／几何守卫尚不等于这套未来完整准入条件，尤其不能据它证明
整个小节没有重复／冲突声明。币种入口修复后也不能保证所有金额可提取。

## 未提升的权限与依赖

`currency_support_implemented=false`、`currency_verified_by_assessment=false`；不实现
币种修复，不改金额列边界、附注语法、审计、租赁或华域分类桥接。
格力仍未执行主表和附注层，不能说其六个多级引用已经通过或失败。宇通、恒瑞
原有列边界和利润缺口保持原状；已有筹资租赁部分不升级为完整 Lease_cash。

完整租赁、Lease_cash_pit、标准／保守 FCF、历史版本与时点、跨年兼容仍未闭环。
`UNKNOWN_UNLESS_VERIFIED`、`diagnostic_available_at=null`、PIT 准入 0，真实硬门／
排名权限及九域 `not_ready` 不变。

## 开发记录与隐私

开发 v1 原 JSON SHA：`9185b52da349dc50e2d8e52381040d89884c42b0e27d9fdf9b3256412f1cec9e`。
追加隐私探针发现公开投影会复制守卫字典的未知键，文字可通过键名夹带进入
索引。没有发现本次实际源索引已含该注入文字；这是工具逆向边界缺口。
随后收紧守卫键、边界键、计数键／值与选页哈希的契约，并增加逆向测试。

v1 的原报告、索引、当时代码和范围 bytes 都保存在本地
`storage/pilots/annual-currency-comma-assessment-2026-10-04-v1/`；索引移名
`development-evidence-index.json`，不覆盖 v1，不作为已验收公开索引。
v2 使用同一固定检索范围、新工具身份和新目录，源内容与盘点结果不变。

完整 v2 只保存在
`storage/pilots/annual-currency-comma-assessment-2026-10-04-v2/diagnostic-only.json`。
[公开薄索引](annual-currency-comma-assessment-2026-10-04-v2/evidence-index.json)只含来源身份、
形式／边界状态、数字坐标与哈希：不含声明原句、完整词元文字、页文、表头或
上下文。索引是独立逻辑身份，不冒充完整报告。原 PDF、报告和派生图不进入 Git。
storage 的独立异地备份／恢复尚未验收，本地原文仍为唯一已核实副本。

| 对象 | SHA-256 |
|---|---|
| 冻结范围 | `6ea5976fa3a464c487d1f41d52a7282cd1d1949431a1ec1641af36a015a45ab9` |
| v2 评估工具 | `ab61c6738a28cca100ae8eba0b4702600796d4ae3bdfff8746ddfb3e1936b01e` |
| 完整 v2 JSON bytes | `c0c686784508179aca6897df8e8357a533d64847dffdedff4047279420f17d80` |
| 完整 v2 JSON logical | `923034a5f8c6fab0aa3457d1658a596090efbe1b6c47b2a79321734c6e7f8c16` |
| 公开 v2 索引 bytes | `448d4fb9d74031f89978adaa1d2fd8081f5326487d475bb9f5082ab5d350daa9` |
| 公开 v2 索引 logical | `d02ab1b6943d4ae38675c1a70350aa05f89ded9516d11f63dca3028e7a8b90b9` |

## 验收与重放

```powershell
python -X utf8 scripts/pilots/assess_annual_currency_comma.py `
  --scope docs/data-pilots/2026-10-04-annual-currency-comma-assessment-scope.json `
  --output storage/pilots/annual-currency-comma-assessment-2026-10-04-v2/diagnostic-only.json `
  --public-index docs/data-pilots/annual-currency-comma-assessment-2026-10-04-v2/evidence-index.json `
  --check
python -X utf8 -m unittest tests.test_annual_currency_comma_assessment tests.test_annual_report_currency_scope tests.test_annual_report_currency_intro -q
python -X utf8 -m unittest discover -s tests -q
python -X utf8 scripts/verify_workspace_integrity.py
```

首次针对性测试收集因新测试列表少一个闭括号而报 `SyntaxError`，没有执行测试。
只修测试语法，v2 工具、报告／索引 bytes 未变。修正后针对性 **116 项通过，
22.409 秒**，其中本轮新增 55 项；包含真实 PDF 回归、精确形式及范围／几何、
不拼接、投影隐私、父包／源哈希与不提升权限的断言。新 CLI `--check` 已实际
重算，完整 v2 JSON／公开索引逐字节一致。完整回归：**1837 项通过，无跳过，
410.161 秒**；从前序 1782 项增加 55 项，规则、538 份生产快照和六项解析代码
哈希均未变；旧范围继续由各自冻结提交实际重放。

既有冻结重放器只新增本评估的显式 schema 与白名单支持文件，不修改旧 schema
路径。保存本轮代码提交后，以下命令在临时目录取该完整提交代码和核验后的
输入，实际执行 CLI，要求完整 JSON／索引逐字节一致；不 checkout、不联网、
不改旧文件／Git 历史、不用保存结果替代执行：

```powershell
python -X utf8 scripts/pilots/replay_frozen_annual_indexed_pilot.py `
  --scope docs/data-pilots/2026-10-04-annual-currency-comma-assessment-scope.json `
  --private-report storage/pilots/annual-currency-comma-assessment-2026-10-04-v2/diagnostic-only.json `
  --public-index docs/data-pilots/annual-currency-comma-assessment-2026-10-04-v2/evidence-index.json `
  --code-commit <本轮完整提交ID>
```

RULE_SPEC SHA 保持 `db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`；
538 份生产快照摘要保持 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。
前序 `f74cc17` 已正常推送并核实远端 main；未推私有全文分支、`--all`／`--mirror`，
不用 force。本轮新提交仅保存本地，未推送；两份原有未跟踪文件保持原状。
