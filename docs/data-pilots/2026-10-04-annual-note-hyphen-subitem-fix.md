# ASCII 横杠＋括号子项 · 多级附注整单元格语法

范围：`as_of=2026-09-30`；2026-10-04 离线工程回归。使用本地龟龟 skill
0.4.0 的证据、隐私和同会话自查约束，不是独立人员／模型复核、新样本盲跑、
企业分析或排名。复用十一家发行人／十四份固定 PDF，不是完整五年窗口或
全市场准确率验证。

## 唯一新增语法

仅在 `scripts/parsing/field_binder.py` 的既有显式附注单元格守卫增加：

```text
规范中文整数章节-正 ASCII 整数（正 ASCII 整数）
示例：七-59（1）
reference_form = CHAPTER_HYPHEN_ITEM_FULLWIDTH_PARENS_SUBITEM
syntax_state = OBSERVED_SINGLE_REFERENCE_SYNTAX
note_target_resolved = false
note_semantics_certified = false
```

章节为规范中文整数 1—99；两个项目号均为无前导零的正 ASCII 整数。连接符只
接受 ASCII `-`，不接受全角横杠、长横杠、短横杠、减号或不换行横杠。
只接纳显式非金额附注区内的单个完整原生词元，不删空白、不拼词元／行／页，
不使用 OCR。原生归属、坐标、旋转、裁切、附注／金额边界和金额单元格守卫不变。

保留原有六种语法：无符号整数、单横杠、中文章节顿号项目、中文章节括号项目、
括号项目后缀、顿号项目括号子项。不接受零、前导零、正负符号、小数、科学计数、
非规范章节、ASCII／半括号、列表、多个引用、附注前缀、空白或额外尾文。
旧路径仍可识别自身完整的旧语法，不将拆行片段认证为本轮新增语法。

六项白名单解析代码中只改变 `field_binder.py` 的一个语法条目，其他五项 bytes
保持不变。没有证券、发行人、页码、金额或子编号对应现金分类的专用分支。
不合并币种声明、主表列边界、审计、租赁、引用目标解析或华域分类桥接。

## 原 PDF 回归结果

[新范围文件](2026-10-04-annual-note-hyphen-subitem-regression-scope.json)绑定前轮顿号子项
包和固定输入清单。逐项核验十一份输入、十四份原 PDF 的证券／发行人／年度／
声明版本、公告 URL／ID、SHA 和页数。宇通 `sh.600066`，宇通客车股份有限公司，
声明 2024 年报，公告 `1222974533`，158 物理页；PDF SHA：
`5edfe6e4ac095d6c28e17903cc87e284b5d8f75ba3be3f4515a0fbb92f5bc023`。

程序在同一原 PDF 的物理 65 页合并现金流表，识别元／人民币单位、2024／2023
两栏及三行完整引用。新包保存后才查看同页本地派生图作同会话自查；这不是
独立人员复核，人工可见数值没有替换程序结果。

| 原文行 · 元 | 物理页／引用 | 本期 2024 | 比较栏 2023 |
|---|---|---|---:|
| 收到其他与经营活动有关的现金 | 65／`七-59（1）` | null，`COLUMN_EDGE_AMBIGUOUS` | 716,002,911.89 |
| 支付其他与经营活动有关的现金 | 65／`七-59（1）` | null，`COLUMN_EDGE_AMBIGUOUS` | 2,200,722,817.75 |
| 支付其他与筹资活动有关的现金 | 65／`七-59（2）` | null，`COLUMN_EDGE_AMBIGUOUS` | 9,282,499.82 |

本轮恢复三行引用语法，不是六个完整金额。三个比较栏为数值观察；三个本期
单元格仍 null：原生金额盒右边界分别为 438.082、438.082、438.078，跨过既有
表头推导的分列边界 438.025。没有放宽边界、删改原词元／坐标、以比较栏或
人工值填充本期。旧基线的两栏 `NOTE_CELL_NOT_UNAMBIGUOUS_REFERENCE`／null 保留
在新报告的 `before` 中，不能把本轮结果倒写为旧代码成功。

只宇通一份 PDF 的三行变化；其余十三份三张主表逐行完全相同，全部十四份
`parse_annual` 既有整组内容完全相同，含主表七项目标、币种、审计、租赁、
原有引用观察和来源绑定。宇通 OCF／Capex 仍 `COLUMN_EDGE_AMBIGUOUS`／null，
租赁筹资支付已识别部分仍 `14,990,744.76`，不把筹资其他支付总额当作第二笔租赁。

伊利前轮六行保留十一项数值和一项 `BLANK_NOT_ZERO`／null；恒瑞前轮六行保留
十二项数值，不计作本轮新增。限定原生词元盘点仍为三类、21 处：伊利 6、恒瑞 6、
宇通 3、格力 6。已执行附注守卫的 15 行现均有这三类受支持语法，但不表示
全部金额完整；格力 6 处仍因币种阻断未执行，不能称 21 处全部通过。四份
币种阻断、行数和样本数均不作正确率分母或全市场覆盖率。

引用目标／报表语义仍 false，完整 Lease_cash、Lease_cash_pit、标准／保守 FCF、
历史可用时点、版本链和跨年兼容仍未闭环；`UNKNOWN_UNLESS_VERIFIED`、
`diagnostic_available_at=null`、PIT 准入 0、真实企业硬门／排名权限及九域
`not_ready` 不变。

## 复用入口与冻结历史

复用 `build_annual_note_suffix_regression.py`，仅增加明确的横杠子项 schema／语法
配对，不接任意正则。实际读取完整基线
`541b8ca737288c4321ee4d666f1f5706e8e464b6` 的六项白名单解析 blob 和同提交 Python
支持模块，在临时目录执行旧代码。逐份旧三表和整组哈希必须与已批准顿号父包
一致，不能用保存结果替代旧代码执行。

比较只允许新增语法状态／形式及对应金额状态／数值改变；原文词元、坐标、表界、
表头、行序、单位、年份和范围必须一致。旧顿号／后缀报告改由各自完整冻结提交
实际重放，保留旧金额与产物字节断言。当前语法测试随批准新增语法更新，但
旧报告中宇通三行仍受阻的历史断言不放宽；不混用旧主解析器和当前附注守卫。
不 checkout、不联网、不改旧文件或 Git 历史。新结果有独立 schema、范围、代码
和内容身份；基线提交号不是新代码提交号。

## 产物、隐私与备份

完整新报告只保存在
`storage/pilots/annual-note-hyphen-subitem-fix-2026-10-04-v1/diagnostic-only.json`。
[公开索引](annual-note-hyphen-subitem-fix-2026-10-04-v1/evidence-index.json)只含来源身份、
受限短引用、数值／数字坐标、状态和证据哈希，不含完整页、词元集合、科目行、
表头、意见段或上下文。索引有独立逻辑身份，不冒充完整报告。

| 对象 | SHA-256 |
|---|---|
| 新范围文件 | `e163c7bf1652dd5c5d35a514a1637273515962514b41c508ebe8dc9c2a0d41b9` |
| 新附注守卫 | `7599555aa17bcdcf81170eca0bd22782d408923b930b949b1067ba722a3f96d9` |
| 新回归工具 | `534f8a7fbc798f038382b0fe7da75d493df262039adbe2a8959ed8d9e474d068` |
| 完整 JSON bytes | `c6e4af6abb87ccb06ca225945f2d5b066c8c8b63666f94de295d7c24f478fb96` |
| 完整 JSON logical | `1f920c5505bf131e759e990e782c84c6e633d0c319a86ecc8f23bcaef5495c52` |
| 公开索引 bytes | `e0d6cabd4b1d6c3468b8ff41a0460ffbd43a3213e7c438afe1a3e1bddb4a7d89` |
| 公开索引 logical | `da9fa5b8473ee0ed6e2921587f5829c068692e0ed6ff7fc20599f94894a51c71` |

原 PDF、完整新旧报告、派生图和临时基线不进 Git。storage 的独立异地备份／恢复
尚未验收，本地原文仍为唯一已核实副本，公开索引不能复原全文或替代备份。
前序 `541b8ca` 本轮已正常推送 `origin/main` 并核实远端一致，不推私有全文分支、
`--all`／`--mirror`，不用 force，不绕过忽略规则。此前额外远端查询停滞不等于
已确认推送失败；本轮以实际推送与远端查询结果确认前序状态。本轮新提交仅保存
本地，未推送；两份原有未跟踪文件保持原状，未纳入提交。

## 重算与验收

```powershell
python -X utf8 scripts/pilots/build_annual_note_suffix_regression.py `
  --scope docs/data-pilots/2026-10-04-annual-note-hyphen-subitem-regression-scope.json `
  --output storage/pilots/annual-note-hyphen-subitem-fix-2026-10-04-v1/diagnostic-only.json `
  --public-index docs/data-pilots/annual-note-hyphen-subitem-fix-2026-10-04-v1/evidence-index.json `
  --check
python -X utf8 -m unittest tests.test_annual_note_hyphen_subitem_regression tests.test_annual_note_dunhao_subitem_regression tests.test_annual_note_suffix_regression -q
python -X utf8 -m unittest discover -s tests -q
python -X utf8 scripts/verify_workspace_integrity.py
```

首次针对性运行 181 项、160.237 秒：一项新测试误用不存在的表头键 `split_x`，
按既有契约改为 `column_split`。只修改测试；解析器、范围、回归工具及已保存
v1 报告／索引 bytes 均未改变，不把首次测试写为成功。
针对性重跑：**181 项通过，159.463 秒**，其中本轮新增 62 项、旧顿号 63 项、
旧后缀 56 项。覆盖全部 99 个规范章节、精确字符语法逆向、原生归属和几何、
金额／空白边界、父包与实际旧代码一致性、局部变化限制、隐私投影及拒绝
语义／PIT 权限提升。新 CLI `--check` 实际重算新旧解析，完整 JSON／公开索引
字节一致。完整回归：**1782 项通过，无跳过，393.065 秒**；从前序 1720 项
增加 62 项。规则、九域状态和 538 份生产快照哈希检查通过且未变。

保存本轮提交后，用其完整提交 ID 实际重放新包；必须与完整 JSON、公开索引
逐字节一致，不以基线 `541b8ca` 冒充本轮新代码：

```powershell
python -X utf8 scripts/pilots/replay_frozen_annual_indexed_pilot.py `
  --scope docs/data-pilots/2026-10-04-annual-note-hyphen-subitem-regression-scope.json `
  --private-report storage/pilots/annual-note-hyphen-subitem-fix-2026-10-04-v1/diagnostic-only.json `
  --public-index docs/data-pilots/annual-note-hyphen-subitem-fix-2026-10-04-v1/evidence-index.json `
  --code-commit <本轮完整提交ID>
```

RULE_SPEC SHA 保持 `db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`；
538 份生产快照摘要保持 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。

三种已观察多级引用语法现均有有界支持，不意味着引用目标或金额列问题已解决。
后续可另冻范围评估币种声明族的逗号连接说明；不在本轮追加修复，不借三行
语法恢复认证完整租赁、审计、PIT、真实企业硬门或排名。
