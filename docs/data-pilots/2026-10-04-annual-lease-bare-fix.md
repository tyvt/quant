# 裸负债标签：支付表上下文限定的租赁现金部分

日期：2026-10-04；诊断 `as_of=2026-09-30`。仅对既有十一家发行人、十四份固定 PDF
做事后回归，不是新盲跑、全市场覆盖率、真实硬门、排名或投资判断。
完整 Lease_cash、PIT、标准／保守 FCF 与九个生产域状态不因本轮改善。

## 实现与实际结果

只扩展 `scripts/parsing/annual_report_parser.py` 中独立的裸标签支付表路径，
不把“租赁负债”加入五个既有通用现金别名。没有证券、发行人、页码、金额或固定行数分支。
其余五项解析支持代码与基线 bytes 一致，多级附注、币种、审计、跨页、主表金额边界
及华域完整去重认证不合并追修。

伊利 `sh.600887`，声明 2024 年报、公告 `1223421123`，270 物理页，PDF SHA-256
`a82a81e52f52da3cd1b7f38ded08625dc18e3d4522b15d3ef76bf921e54c1f43`。
程序读取同一原 PDF，物理 216 页／印刷 212 页的支付表，不用上一轮人工金额回填。
发行人本位币仍由既有 106 页政策声明核验；局部人民币列示不代替本位币政策。

| 同表原文项目 | 本期 2024（元） | 上期比较栏 2023（元） |
|---|---:|---:|
| 购买子公司少数股东权益 | 28,562,809.48 | 78,896,000.00 |
| 股票回购 | 758,635,266.98 | 696,961,104.79 |
| 债券发行费 | 1,953,008.32 | 1,443,291.43 |
| 租赁负债 | 174,129,885.66 | 258,206,679.23 |
| 限制性股票回购 | 1,890,679.60 | 9,649,770.00 |
| 列示合计／程序逐项和 | 965,171,650.04 | 1,045,156,845.45 |

两列均 `MATCH`，现金部分由 `NOT_IDENTIFIED` 变为 `OBSERVED_NUMERIC`。
逐行保留来源身份、期间、单位、页码、原生标签／金额、坐标与表头绑定。
五项只是此源表的行数，代码核验任意数量的完整行，不硬编码五项。

十四份中已识别现金部分由 9 份／6 家变为 **10 份／7 家**；CNY 已通过而部分未识别
的数量由 1 降为 0，另 4 份仍因币种阻断而未执行租赁入口。不是完整租赁已知率。
其余十三份租赁组件与旧包一致，十四份非租赁内容哈希全部一致，包含主表、币种、
审计、引用观察与原有来源绑定。

## 接受、拒绝与证据契约

1. 先经过既有文档证券／发行人／年度、本位币入口；裸标签须位于唯一合并附注起点
   和母公司附注终点之间。伊利原文边界为物理 150 页至 252 页。
2. 只接受完整原生词元“租赁负债”，同页最近现金上下文须为精确的筹资支付标题。
   不跳过较近的经营、投资、收款或说明上下文；不跨页继承。
3. 上一个闭合终点之后须有唯一支付起点；该起点至下一同格式起点前须有唯一完整
   支付说明终点。不能丢弃未闭合起点而只选最近起点；每张表独立闭合。
   多张有效表或同表多个租赁支付候选交由字段层保持 UNKNOWN，不择一、不求和。
4. 区间须有唯一表头、独立明确单位、人民币列示与本期／上期两栏。
   不借上表单位、日期、金额列或资产负债表余额列。
5. 页未旋转；`CropBox=MediaBox=(0,0,width,height)`。标签、各行、表头、起止与金额
   坐标都须在页内；不拼接标签或金额，不跨行补数，不接受截断或未知额外列。
6. 每行须有一个完整标签；全部金额和列示合计须通过既有单元格守卫。
   使用独立 Decimal 精度核验所有组成行和两栏合计。负数保留，空白／横杠不填零。
7. 任一栏缺项、歧义或对平失败，两个现金部分候选数值都保持 null；原始单元格观察与
   `UNKNOWN_INCOMPLETE_COMPONENTS`／`MISMATCH` 对账证据仍保留，不能反推缺项为零。

新增 `payment_table_evidence` 状态 `OBSERVED_BOUNDED_PAYMENT_TABLE_NOT_FULL_LEASE`，
绑定表界、所有组成行、列示合计、两栏对账和页框。
`unit_and_header_inherited=false`、`label_or_amount_joined=false`、
`note_target_resolved=false`、`complete_lease_cash_certified=false`、
`public_availability_verified=false`。这只是明确筹资现金支付表中的部分，
不拆本金／利息，不认证全部租赁或 OCF／Capex 去重范围。

## 六处同名不能混用与未解决项

同一 PDF 有六处精确同名词元：物理 88、90、216、217、236、237 页；新路径只在
216 页生成候选。88、90 页的合并／母公司负债余额不作现金；236、237 页到期合同
金额不作实际支付；217 页负债变动表的同额现金减少不作为第二笔付款。
不是仅凭“筹资”一词便把余额或多栏现金变动表当成本期／上期支付表。

物理 95 页合并现金流主表数值虽与 216 页列示合计相符，引用 `七（79）3` 仍为
`NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE`，两栏金额仍 UNKNOWN。它另列为多级附注引用
语法缺口，本轮不解析其引用目标，也不从原生外形断言它对应某个已认证层级。

完整租赁范围、本金／利息现金桥接、去重、版本链、可用时点及审计仍未闭环。
`UNKNOWN_UNLESS_VERIFIED`、`diagnostic_available_at=null`、PIT 准入 **0** 不变；
完整 Lease_cash、Lease_cash_pit、FCF_conservative 均 null，不导出真实硬门输入。

## 冻结身份、隐私与开发记录

范围记录的 `implementation_base_commit=27ada9544e1a82cde3a1f8c1e8429c6f5ca44805`
只是修复前基线，不冒充新实现提交。新实现由代码 SHA 独立固定。
父跨页实现包及其索引 bytes 不改写；旧断言通过完整 Git 提交的代码实际执行重放。

| 对象 | SHA-256 |
|---|---|
| [新范围](2026-10-04-annual-lease-bare-regression-scope.json) | `78d39404c62df53e0ccb076c83a4d4c1d76157163dbdb3785b4acf9e60c64b12` |
| 财报解析器 | `525299589b33f4f62fb51115a0e626f9dc6d841cc88eca398eb726be1868e571` |
| 新回归工具 | `63b366d3e5bf7f76e77314337f3a052c33c54e95e03dd05ff500d1d424416d0d` |
| 本地完整 JSON bytes | `7682680d185682224d376b2a83c0966af649e2e35195c76b920e51efbc896e29` |
| 本地完整 JSON logical | `aa447f649735b67b1161632cd56c001045a7bc4fb0ec72fdf9ad180371c3fec7` |
| [最小索引](annual-lease-bare-fix-2026-10-04-v3/evidence-index.json) bytes | `cf11909f764339fd5e09e5c93b679570ebcfad951b05c21477f9451211ebae8f` |
| 最小索引 logical | `d5ba449acde9e73b5f5d84489a9ae8e4b3e24d04060407c68345fcc81ebc8658` |

完整报告在 `storage/pilots/annual-lease-bare-fix-2026-10-04-v3/diagnostic-only.json`。
索引仅含来源身份、允许的短租赁标签、数字／坐标、状态和哈希；支付表其他项目标签
只投影摘要，不带完整词元、表头、段落或原文文字通道。索引具有独立身份，不能重建原文。
本轮龟龟 skill 的证据／隐私约束影响了此分层及本地／最小索引的交付边界。

开发 v1 的逆向测试发现：两个完整支付表时不能丢弃首表而选第二表；现已收紧。
另一失败来自测试误以为底层范围拒绝返回必有完整租赁标志，只修改该测试假定。
v1 完整 JSON SHA `d289ffd7971f63a2ad831efd3df765785c7b8a2ce83a07059adda59e77a85833`，
其原代码／范围／索引均保留本地 `storage/pilots/annual-lease-bare-fix-2026-10-04-v1/`，
索引移名 `development-evidence-index.json`，可恢复；不覆盖、不作为正式验收包发布。
开发 v2 的 47 项新增回归及完整 1598 项测试虽通过，追加逆向探针仍发现连续两个未闭合
起点可被择近放行，现进一步收紧起点守卫并增补测试。v2 完整 JSON SHA
`6580be3c25a25f0f7e62ff0a214f43a58a183479095849b73f848eb5e2c224ef`，
原代码／范围／索引同样保留本地 v2，索引移为 `development-evidence-index.json`。
正式结果另存 v3，v1／v2 均不发布为验收包。这不是把失败或追加发现重新包装为首次成功。

完整原文与开发材料不进入 Git；storage 独立异地备份与恢复仍未验收，本地原文是唯一
已核实副本，不声称绝无其他副本。不推送私有分支、`--all`／`--mirror`，不 force。

## 复现与验收

```powershell
python -X utf8 scripts/pilots/build_annual_lease_bare_regression.py `
  --scope docs/data-pilots/2026-10-04-annual-lease-bare-regression-scope.json `
  --output storage/pilots/annual-lease-bare-fix-2026-10-04-v3/diagnostic-only.json `
  --public-index docs/data-pilots/annual-lease-bare-fix-2026-10-04-v3/evidence-index.json `
  --check
python -X utf8 -m unittest tests.test_annual_lease_bare_regression -q
python -X utf8 -m unittest discover -s tests -q
python -X utf8 scripts/verify_workspace_integrity.py
```

新增 50 项针对性回归。覆盖表界、重复起点与重复候选、负债余额／
变动／合同表、经营／投资／收款、独立单位／期间、截断／页框／分列歧义、缺项／显式零、
正负号／低精度环境及两栏对账、十四份来源身份／非租赁不变和索引文字泄漏拒绝。
新增 50 项通过；完整 `python -X utf8 -m unittest discover -s tests -q`：
**1601 项通过，无跳过**，218.780 秒。父跨页实现包在针对性与完整验收中用完整提交
`27ada9544e1a82cde3a1f8c1e8429c6f5ca44805` 的旧 CLI 实际重放，完整 JSON／索引
逐字节一致，不用当前代码或保存结果冒充旧代码执行。新 CLI 拒绝覆盖既有结果，
`--check` 校验重新计算的完整 JSON／索引 bytes；公开索引身份与完整报告身份分别固定。

RULE_SPEC SHA 仍为 `db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`；
538 份生产快照摘要仍为 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。
历史发布记录、基准适配器／Reader、旧报告和生产状态不变。

下一项可单独评估多级附注引用的整单元格语法与目标层级，不借本轮现金部分观察认证
95 页引用目标、完整租赁、审计、PIT、真实硬门或排名。
