# 跨页租赁支付上下文有界实现

日期：2026-10-04。诊断截止日：2026-09-30。本轮为既有样本修复回归，不是新盲跑，
不是独立人员复核，也不是完整财报、完整租赁或历史可用性认证。不生成硬门、排名、
alpha、FCF、订单或绩效；其他九域与真实策略编排仍 `not_ready`。

## 范围与实际结果

以完整基线提交 `9187e28f8ea9b754b1502686b7ce2a59b8b655a0` 和
[旧有界评估](2026-10-04-annual-lease-continuation-assessment.md)为依据，另冻
[实现范围](2026-10-04-annual-lease-continuation-regression-scope.json)。离线复用十一家、
十四份固定 PDF，核验清单、证券、发行人、年度、声明版本、URL、页数及 SHA。
基线提交只表示修复前身份；新实现由本轮六项代码 SHA 固定，不把旧提交冒充新代码。

宇通客车 sh.600066 的公告 `1222974533`、2024 年报，PDF SHA
`5edfe6e4ac095d6c28e17903cc87e284b5d8f75ba3be3f4515a0fbb92f5bc023`：
程序在原 PDF 中取得完整原生行，不用评估中的人工值回填。

| 原文层次 | 物理页 | 本轮结果 |
|---|---:|---|
| 筹资支付标题、其后适用性标记 | 125 | 有界续接至紧邻下一页，分类证据绑定这一页 |
| 独立单位、项目／本期／上期两栏 | 126 | 不继承上一页单位、表头或金额边界 |
| 偿还租赁负债本金和利息所支付的现金 | 126 | 本期 `14,990,744.76`，比较栏 `8,061,350.60` 元 |
| 下一编号附注 | 126 | 明确限定表终点，不能拼接后面的补充资料 |

现金部分从 `NOT_IDENTIFIED` 变为 `OBSERVED_NUMERIC`；这是筹资支付中的已识别部分，
不拆解本金／利息，也不认证其为全部未重复扣减租赁金额。十四份中的已识别现金部分
从 8 份／5 家变为 9 份／6 家，另 1 份 CNY 通过但未识别（伊利），4 份币种阻断。
其余十三份租赁组件与基线完全相同；十四份的非租赁内容哈希均与旧包一致，包含主表、
币种、审计、引用观察及其来源绑定。海螺同标签、同页的结构仍未支持，不强制 CNY。

## 接受条件与未扩展范围

同页五个既有 `LEASE_LABELS` 不变。新长标签只进入新增的有界路径：

- 先由既有入口验证文档身份、本位币与唯一合并／母公司附注区间。
- 只读同一 PDF 的紧邻上一物理页，不越多页，不跨源文件或版本。
- 上页底部 20% 内有唯一完整原生筹资支付标题，其后仅允许既有适用性标记及页脚。
- 两页均未旋转、宽高相符。新增页面对象的原 PDF `CropBox`／`MediaBox` 记录；二者
  必须相等且为原点页框，缺失、非原点、裁切或尺寸变化拒绝，不只凭宽高相同推断。
- 下页正文首表独立给出唯一受支持单位和本期／上期两栏，未知前置段落、现金上下文、
  错期间、额外列、重复表头或新的提前附注拒绝；不旁路无效首表。
- 标签必须为一个完整原生词元，标签和金额不跨行或跨页拼接；下一编号中文附注明确
  限定表终点。重复长标签或同表另有既有受支持支付标签不择一、不相加。
- 金额沿用原单元格守卫。负数保留，越界、多词元、不可解析数保持 UNKNOWN；空白与
  横杠不当零，比较栏不替代本期。可独立保留当前已观察数值与比较栏 UNKNOWN。

新增的 `continuation_evidence` 绑定两页、原文坐标、页框与下一附注；状态
`OBSERVED_BOUNDED_ADJACENT_CONTEXT_NOT_FULL_LEASE`。只有分类标题上下文续接，
`unit_and_header_inherited=false`、`label_or_amount_joined=false`。
未合并短标签跨页、其他长标签、裸负债标签、币种、审计、主表金额边界或华域去重桥接。
本轮没有发行人、证券、页码或金额专用分支，也不据一份回归样本估计全市场覆盖。

旧评估中本期支付表对平、比较栏第三项 `BLANK_NOT_ZERO` 与完整比较栏对账 UNKNOWN
继续保留，本轮不改写或反推旧观察。完整租赁范围、本金／利息付款桥接、OCF／Capex
去重、版本链与时点仍未闭环：完整 Lease_cash、Lease_cash_pit、FCF_conservative 均 null。
`UNKNOWN_UNLESS_VERIFIED`、`diagnostic_available_at=null`、历史 PIT 准入 0 不变。

## 产物与复现

按本地龟龟 skill 的事实／计算分离与隐私边界，完整行、表头及分类原文留在
`storage/pilots/annual-lease-continuation-fix-2026-10-04-v2/diagnostic-only.json`。
[公开证据索引](annual-lease-continuation-fix-2026-10-04-v2/evidence-index.json)只含允许的
短标签、来源身份、两栏数值、数字坐标、状态与上下文哈希，不含完整词元、表头或段落。
索引具有独立逻辑身份，不冒充完整报告。

| 对象 | SHA-256 |
|---|---|
| 实现范围 | `520e39f803df1d4435effe94d323509b909f89cf5d43006c1edd4578dd4a044a` |
| 财报解析器 | `9d4cf996adccb0384e3b276ddccdf96303739d7bbd9272d4ab76ed738edb57e4` |
| 原生页面提取器 | `2a3404dbee94303ca0aefc079e65497da88f5729e450e1e69aa87029b5100bf4` |
| 本轮回归工具 | `a010ae457a1a305d64ed35a8554c3b3a769ce015a4a8d371914e8abc7b08e090` |
| 完整 JSON bytes | `046ff86ed9f5c2f79365980aaa8020f007ad096dd95caaa8c63571829990c154` |
| 完整 JSON logical | `29622b41d4b9819cdf81e9a75f680e5d6b0951eaa5def4926700d17d70a24070` |
| 公开索引 bytes | `ad661a042480e1bb03290c5590605d12fdfaab18f588c774936b3bccb4982b10` |
| 公开索引 logical | `043b040ab45d1802fecf9e7c4bcf15590339fa8fe73320c2265c3d42a4095dd7` |

```powershell
python -X utf8 scripts/pilots/build_annual_lease_continuation_regression.py --scope docs/data-pilots/2026-10-04-annual-lease-continuation-regression-scope.json --output storage/pilots/annual-lease-continuation-fix-2026-10-04-v2/diagnostic-only.json --public-index docs/data-pilots/annual-lease-continuation-fix-2026-10-04-v2/evidence-index.json --check
```

旧标签修复包用 `526fb38e65d6002c5663ad6a40ccb9a9ead4741f`，旧跨页评估用
`9187e28f8ea9b754b1502686b7ce2a59b8b655a0` 的真实旧 CLI，在临时目录实际执行；
完整 JSON 和公开索引均须逐字节一致。重放器仅增加明确 schema／代码白名单／固定
父引用，不 checkout、不联网、不修改 Git 历史，也不用保存的报告替代执行。
旧回归的历史产物断言保留；涉及当前代码的原文观察另做本轮回归。

开发 v1 的额外逆向探针发现同表另一受支持标签没有阻断；本轮已收紧该守卫。
开发 v1 完整 JSON、索引、当时代码和范围 bytes 保留在本地
`storage/pilots/annual-lease-continuation-fix-2026-10-04-v1/`，索引移名
`development-evidence-index.json`，不发布为已验收包、不覆盖为 v2。
旧有界评估 v1／v2 与旧标签包完全不改。本轮初次测试另有金额替换 fixture 的测试错误，
已限定替换目标金额词元；不修改源 PDF 或人工填写程序输出。

## 验收与保留边界

新增 47 项回归，覆盖来源、相邻页、页框／裁切／旋转、支付分类、标题尾部、前置
段落、首表、单位／期间／额外列、附注／母公司边界、重复／拆行标签、多支付标签、
金额边界、负数、空白、旧包保护、脱敏、PIT 不准入与拒绝覆盖。
`python -X utf8 -m unittest discover -s tests -q`：1551 项通过，无跳过，耗时 207.667 秒。
47 项针对性测试通过；v2 再执行与 `--check` 的完整 JSON／公开索引均逐字节一致。

RULE_SPEC 仍 v1.3.2／`db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`。
三份历史发布记录、基准适配器／Reader 与旧报告未变；538 个生产快照清单摘要仍
`2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。
storage 未由 Git 备份；独立异地备份与恢复尚未验收，本地原文仍是唯一已核实副本。
公开索引仅可辅助定位 URL／版本并校验重获 bytes，不可反演原文、页图或重放全报告。

本轮到此停止，不继续追修其余缺口。后续可单独评估伊利裸标签上下文，仍不得用
负债存量作现金代理，也不与币种、完整去重或审计缺口合并。
