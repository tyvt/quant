# 顿号＋括号子项 · 多级附注整单元格语法

范围：`as_of=2026-09-30`；2026-10-04 离线工程回归。使用本地龟龟 skill
0.4.0 的证据、隐私和同会话自查约束，不是独立人员／模型复核、盲跑、企业分析或排名。
复用十一家发行人／十四份已固定 PDF，不是十一家完整五年窗口或全市场准确率。

## 唯一新增语法

仅在 `scripts/parsing/field_binder.py` 既有显式附注单元格守卫增加一种形式：

```text
规范中文整数章节、正 ASCII 整数（正 ASCII 整数）
示例：七、78（1）
reference_form = CHAPTER_DUNHAO_ITEM_FULLWIDTH_PARENS_SUBITEM
syntax_state = OBSERVED_SINGLE_REFERENCE_SYNTAX
note_target_resolved = false
note_semantics_certified = false
```

章节沿用规范中文整数 1—99；两个项目号均为无前导零的正 ASCII 整数。必须是一个
完整原生词元，保留文字与坐标，限定显式非金额附注区。不去空白、不拼词元、行或页，
不使用 OCR，不改变原生归属、页内坐标、旋转、附注／金额边界与金额单元格守卫。
保留原有五种语法，包括前轮 `七（79）3`；拆行首片若独立满足旧语法，可能仍被旧
路径识别，但不认证新子项语法、不拼接后片，也不认证引用目标或报表语义。

拒绝零、前导零、正负符号、小数、科学计数、非规范章节、ASCII／半括号、列表、
多个引用、前缀、空白、额外尾文。`七-59（1）` 及其他横杠变体仍拒绝；不合并
多级引用目标解析、币种、主表金额边界、审计、租赁或华域分类桥接。

六项白名单解析代码只改变 `field_binder.py` 的一个语法条目；其他五项 bytes 不变。
没有发行人、证券、页码、金额或固定子编号对应现金分类的专用分支。

## 原 PDF 回归结果

[新冻结范围](2026-10-04-annual-note-dunhao-subitem-regression-scope.json)绑定前轮后缀包
及固定输入清单，核验十一份输入、十四份原 PDF 的证券／发行人／年度／声明版本、
公告 URL／ID、SHA 和物理页数。恒瑞 `sh.600276`，江苏恒瑞医药股份有限公司，声明
2024 年报，公告 `1222961962`，249 物理页。原 PDF SHA：
`7fad40fef23755f81ce5322f45483ea257ef026ebf1f7f5655c8d5998d7049fc`。
金额来自当前代码对同一原 PDF 的执行，不用前轮人工评估值填充。
首次新包保存后，同会话查看原 PDF 物理 149 页派生图，核对合并现金流表标题、
元／人民币单位、2024／2023 两栏、六项引用及十二项金额；这不是独立人员复核，
未将图像人工观察替换程序输出。派生图只保存在本地同一新包目录。

| 恒瑞原文行 · 元 | 物理页／引用 | 本期 2024 | 比较栏 2023 |
|---|---|---:|---:|
| 收到其他与经营活动有关的现金 | 149／`七、78（1）` | 1,322,070,742.88 | 1,295,530,285.40 |
| 支付其他与经营活动有关的现金 | 149／`七、78（1）` | 11,190,382,126.13 | 9,249,239,088.77 |
| 收回投资收到的现金 | 149／`七、78（2）` | 605,485,304.68 | 2,607,501,921.22 |
| 投资活动现金流出小计 | 149／`七、78（2）` | 2,591,877,899.36 | 1,500,877,315.29 |
| 支付其他与筹资活动有关的现金 | 149／`七、78（3）` | 275,801,751.83 | 861,599,151.46 |
| 六、期末现金及现金等价物余额 | 149／`七、79（4）` | 24,239,102,117.66 | 20,271,524,269.72 |

六行恢复引用语法和两栏共十二个数值观察，不解析引用目标，不将筹资支付总额当作
租赁分项，也不将现金及现金等价物余额认证为规则所需可动用现金。
恒瑞原有租赁现金部分仍为 `47,375,294.97`；归母利润仍 `NOT_IDENTIFIED`，合并利润
仍 `COLUMN_EDGE_AMBIGUOUS`，不由本轮六行恢复消除其他缺口。

与基线实际执行结果比较：只恒瑞一份 PDF 的六行变化；其余十三份的三张主表逐行
完全相同，全部十四份 `parse_annual` 既有整组内容完全相同，含七项目标、币种、
审计、租赁、已有引用观察及来源绑定。伊利前轮六行保持十一项数值加一项
`BLANK_NOT_ZERO`／null，不能重新计为本轮新增。

原生词元仍三类、21 处：伊利 6，恒瑞 6，宇通 3，格力 6。已执行主表守卫的
15 个多级引用候选中，伊利 6 个保留，恒瑞 6 个本轮恢复，宇通 3 个仍受阻。
格力的 6 处仍因币种阻断未进入附注层；四份币种阻断不算附注成功或失败。
这些计数不是唯一会计科目全集、正确率分母或全市场覆盖率。

完整 Lease_cash、Lease_cash_pit、标准／保守 FCF、历史可用时点、版本链及跨年
兼容仍未闭环；`UNKNOWN_UNLESS_VERIFIED`、`diagnostic_available_at=null`、PIT 准入 0、
真实企业硬门／排名权限不变，九域仍 `not_ready`。

## 复用回归入口与冻结历史

复用 `build_annual_note_suffix_regression.py`，只新增明确的顿号子项 schema／语法
配对，不从配置接受任意正则。新模式实际读取完整基线
`9b2be0fd137d422fddce183b9b69cba1039b3cfe` 的六项白名单解析 blob 和同提交 Python
支持模块，在临时目录运行旧代码；逐份旧三表和整组哈希还必须与已批准父包一致。
新旧比较只允许本轮语法状态／形式以及对应金额状态／数值改变，来源、原文词元、
坐标、表界、表头、行序、单位、年份和范围不得改变。

旧后缀 v1 报告／索引仍由其完整冻结提交实际执行，字节断言保留；不混用旧主解析器
和当前附注守卫，不 checkout、不联网、不改旧文件或 Git 历史、不用保存结果替代
运行。旧 schema 保留；新结果具有独立 schema、代码、范围和内容身份。

## 产物、隐私与备份边界

完整新报告只保存在
`storage/pilots/annual-note-dunhao-subitem-fix-2026-10-04-v1/diagnostic-only.json`。
[公开索引](annual-note-dunhao-subitem-fix-2026-10-04-v1/evidence-index.json)只投影公开来源
身份、受限短引用、数值／数字坐标、状态和证据哈希，不含完整页、词元集合、科目行、
表头、意见段或上下文。索引有独立逻辑身份，不冒充完整报告。

| 对象 | SHA-256 |
|---|---|
| 新范围文件 | `a64d86d7a30a17dba65926fc16f51b7af9c33582ebd978cebe57fe73d0e59f10` |
| 新附注守卫 | `b87e36c41768cadd8480eb8894a50bf24d1062f66594ae258052482ba92ba5db` |
| 新回归工具 | `e0f961b8f18e0e5ae748e7383d5f7fccc92a9dc46c2698a97e1dc03d3e71ffbb` |
| 完整 JSON bytes | `fb5ca8e47f1ecf13206bdc813bb5faf34d6437e8d3a4ae100ce415052fd27237` |
| 完整 JSON logical | `f1c403b55afafeeaec6e8695708f5f488dba340cbbe95628db1c40fbf40c76e5` |
| 公开索引 bytes | `e08c19cb2a5e329688510a78b1c72d6aa03a6a2ec80e3f97451df725dc6d9e01` |
| 公开索引 logical | `312faee2ff88dd3c6c1cf715ec5a62ef0f6c539ddc757cdd9d66cfdb3d241787` |

原 PDF、完整新旧报告和临时基线均不进 Git。尚未验收 storage 的独立异地备份／
恢复，本地原文仍为唯一已核实副本；公开索引不能恢复完整原文或替代备份。
前序 `9b2be0f` 本轮已正常推送 `origin/main`，远端核实一致；不推私有全文分支、
`--all`／`--mirror`，不用 force，不绕过忽略规则。

## 重算与验收

```powershell
python -X utf8 scripts/pilots/build_annual_note_suffix_regression.py `
  --scope docs/data-pilots/2026-10-04-annual-note-dunhao-subitem-regression-scope.json `
  --output storage/pilots/annual-note-dunhao-subitem-fix-2026-10-04-v1/diagnostic-only.json `
  --public-index docs/data-pilots/annual-note-dunhao-subitem-fix-2026-10-04-v1/evidence-index.json `
  --check
python -X utf8 -m unittest tests.test_annual_note_dunhao_subitem_regression tests.test_annual_note_suffix_regression -q
python -X utf8 -m unittest discover -s tests -q
python -X utf8 scripts/verify_workspace_integrity.py
```

首次针对性运行 117 项、87.506 秒：一项新测试误写不存在的字段名
`consolidated_net_profit`；按既有契约改为 `total_net_profit`。只改测试，不改
解析器或新 v1 报告 bytes，也不把该次运行写为成功。另增两项父包／实际基线
内容漂移逆向测试。新 CLI `--check` 实际重算新旧解析，完整 JSON／索引字节一致。
第二次针对性运行：**119 项通过，104.894 秒**，其中新增 63 项、旧后缀 56 项。
覆盖全部 99 个规范章节、语法逆向、原生归属与几何、金额／空白边界、父包与实际
旧代码一致性、局部变化限制、隐私投影和拒绝语义／PIT 权限提升。
完整回归：**1720 项通过，无跳过，339.263 秒**；从前序 1657 项增加 63 项。
旧后缀和更早限定包继续由各自完整冻结提交实际重放，历史金额／产物断言保留。
保存本轮提交后，可用以下命令以完整提交 ID 实际重放新包；它核验新完整 JSON
及公开索引逐字节一致，不用旧父包的提交号冒充本轮新代码。

```powershell
python -X utf8 scripts/pilots/replay_frozen_annual_indexed_pilot.py `
  --scope docs/data-pilots/2026-10-04-annual-note-dunhao-subitem-regression-scope.json `
  --private-report storage/pilots/annual-note-dunhao-subitem-fix-2026-10-04-v1/diagnostic-only.json `
  --public-index docs/data-pilots/annual-note-dunhao-subitem-fix-2026-10-04-v1/evidence-index.json `
  --code-commit <本轮完整提交ID>
```

RULE_SPEC SHA 保持 `db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`；
538 份生产快照摘要保持 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。

下一项如处理 `中文章节-正整数（正整数）`，另冻语法、范围、逆向测试和产物；
不借本轮六行恢复认证目标、现金可用范围、完整租赁、审计、PIT、真实硬门或排名。
