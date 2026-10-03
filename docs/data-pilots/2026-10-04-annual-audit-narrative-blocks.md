# 叙述式审计：有界意见原文块提取

日期：2026-10-04。`as_of=2026-09-30`。状态：限定原文回归，不是新样本盲跑、
意见类型标准化、企业硬门验收、真实 PIT 运行、排名、回测或投资建议。
本地龟龟 skill 的证据分层决定本轮只新增原文观察；版本、可用时点与硬门不升级。

## 1. 实现范围与拒绝边界

仅修改 `annual_report_parser.py` 的 `_audit`，新增 `_audit_narrative_block`。
AST 对比冻结基线证实其余函数、导入与常量未变；字段绑定器、币种、主表表头、
年度、单位、金额列、租赁和审计类型原文入口均未扩展。

唯一支持的标题对是 `一、审计意见` → `二、形成审计意见的基础`，必须由同页、
唯一、顺序正确的完整原生行构成。意见块内保留逐行原生词元及坐标，不用搜索时
的行连接字符串替换证据，不跨页、补句或重排段落。标题与正文均须在未旋转页内。
重叠词元、同排大于 40 点的分隔、嵌套编号结构拒绝；40 点是此入口保守的工程
守卫，不是排版通用标准或语义证明。

对象首句须直接以“我们审计了”或“我们审计了后附的”接完整声明发行人，
对象中第一项年末日期须匹配声明年度，包含财务报表及合并及公司／母公司表述。
意见首句须唯一、原生行以“我们认为，”起始；对象句和意见块末行须完整结束。
这些条件只用于限制原文块来源，`report_object_verified` 仍为 false。
专项审核／鉴证、审阅、示例／引用、关键审计事项／其他信息的前置上下文不接纳。
否定意见文字可作为原文保存，但不分类，更不变成正面意见或硬门通过。

不实现报告号解析：`report_number=null`、`report_number_state=NOT_EVALUATED`。
缺号或重复号不创造编号、最新版本、无效报告或完整重审结论。
不以意见段没有强调事项／持续经营词语证明全报告没有相关事项，也不把报告后面
审计责任中的条件句当作实际发现。

## 2. 同一批样本的实际结果

沿用[既有范围清单](2026-10-04-annual-audit-assessment-scope.json)的十一家、十四份 PDF。
清单原冻结代码身份属于上次评估；本次只复用其来源和 `as_of`，新解析代码身份
单独记录在新报告 `manifest.parser_code_sha256`，不声称用旧代码生成新结果。
没有新增来源、联网、换样本，也不是十一家公司五年窗口或全市场准确率样本。

| 证券／控制组 | 新原文块状态 | 物理页 |
|---|---|---:|
| 恒瑞医药 sh.600276 | OBSERVED_NARRATIVE_OPINION_BLOCK_NOT_TYPE | 139 |
| 万华化学 sh.600309 | 同上 | 75 |
| 海螺水泥 sh.600585 | 同上 | 97 |
| 伊利股份 sh.600887 | 同上 | 83 |
| 长江电力 sh.600900 | 同上 | 85 |
| 隆基绿能 sh.601012 | 同上 | 111 |
| 华域汽车 sh.600741 | NESTED_OR_OTHER_SECTION_UNSUPPORTED | 67 |
| 宇通客车 sh.600066 | NOT_IDENTIFIED（括号标题变体未支持） | — |
| 茂化两版、贝因美三版、格力一版 | 保留六份既有表格类型文字；叙述入口未执行 | — |

六份块提取成功，不等于六份意见类型识别成功、整份审计复核或审计硬门通过。
十四份的旧表格观察所有既有字段与上轮逐值相同；八份旧类型未知仍为未知。
华域和宇通仍未解决，不合并追修。万华／海螺等币种未识别不阻断独立审计原文观察，
也不因本次块观察而恢复财务字段。

三层契约不变：原文块观察 → 报告对象／版本／PIT 语义 → 审计硬门。
所有块 `opinion_type_inferred=null`、`audit_gate_result=null`，对象、完整报告复核、
公众可用与最新版本标记均为 false；更正后整份审计状态 UNKNOWN。
`diagnostic_available_at=null`，历史 PIT 准入数量 0，没有真实硬门输入导出。

## 3. 本地全文与公开索引

新完整原文块报告仅存于被忽略的
`storage/pilots/annual-audit-blocks-2026-10-04-v2/diagnostic-only.json`。
其公开[证据索引](annual-audit-blocks-2026-10-04-v2/evidence-index.json)只保留官方 URL、
证券／年度／版本、PDF SHA、物理页、词元坐标、状态、代码／规则身份以及原文块摘要。
不含完整页文字、完整词元文字、意见段或对象句；数字坐标不能夹带文字。
“删 `native_text` 但保留所有词元文字”不构成全文脱敏，因此两条文字通道都去掉。
索引具有独立身份，不冒充私有报告的逻辑哈希。

上轮完整评估 JSON 保持原 bytes，SHA 仍为
`ae06d17238f5cb4c5935112aad60cfdce283f3bab40548cdcdcb996c76b4dd31`，仅留本地。
公开[评估索引 v2](annual-audit-assessment-2026-10-04-v1/evidence-index-v2.json)
补足来源 URL 和解析代码身份；初次公开索引仍保留，不改写其身份。

未推送的全文提交 `c7cbcc458f49a2eda337756201d0b902dc11f62d` 由本地
`private/audit-assessment-20261004` 保存。`main` 从已发布的 `5bf686c` 非破坏性重建，
公开基线 `88fcd1763339cc792a5c63f2be93f3b50cb9bf1a` 不包含该全文 JSON，
且全文提交不是 `main` 的祖先。不是仅在后续提交删除全文而仍上传其历史。
不得推送该私有分支、`--all`、`--mirror` 或用 `add -f` 绕过忽略规则。
正常推送 `main`，不用 force；本地 Git 与 GitHub 代码副本均不备份 `storage/`。

## 4. 冻结重放、验收与使用

新增 `replay_frozen_annual_audit_assessment.py` 从完整 Git 提交下取旧六项解析代码、
评估 CLI、规则及支持模块，逐项核验代码／输入／PDF／父包 SHA 和 PDF 后端。
在临时目录实际执行旧 CLI，不 checkout、不联网、不覆写原报告、不用结果文件代替
旧代码执行。公开基线 `88fcd1763339cc792a5c63f2be93f3b50cb9bf1a` 提供相同的旧代码，
不要求上传私有 `c7cbcc4`。旧 JSON 与 Markdown 逐字节一致：

| 对象 | SHA-256 |
|---|---|
| 旧评估 JSON（本地） | ae06d17238f5cb4c5935112aad60cfdce283f3bab40548cdcdcb996c76b4dd31 |
| 旧评估 Markdown | 2ec6042924dc9ada5371260af87d085efb897685fca0e7c935374bf4dd6ca2c3 |
| 旧评估公开索引 v2 | 06650f04c63c25ca137a01690b318f0ebcd325a77b1fc42ac521a70e4df0017f |
| 新完整原文块 JSON（本地） | 61e5344ec4a7eaaab559210785a396de3aaff9afc128871d45d23c5d1821e658 |
| 新公开索引 | 6993920713e9ced0d944ead3229fc5c0c2f8cb2adb525dc0ecf7c8434517f445 |

新完整报告 `logical_content_hash=f9ca4c6f6fb18042fc77248447fecaa0e6fa817f40c547770b1e71b64f355533`。
解析器 SHA `82d67859ed8767f13a62f0a4fb985eab74ef0f431a12ddc868c6a7bb063bd842`。
离线重新生成及 `--check` 通过。新输出与原首次盲跑／回归／评估的身份分离。

新增回归覆盖标题唯一性／顺序／范围、原生行与坐标、错主体／年度、嵌套与括号标题、
专项／示例／引用、否定句不推广、KAM／其他信息／条件责任文字、跨页／旋转／截断／
越界／多栏、缺号／重复号、更正版重用原报告、六块与两份未知、六份表格控制、
本地冻结重放、公开文字双通道隔离及 Git 可发布历史检查。

新增 **52 项**回归，完整 **1365 项通过，无跳过**，140.809 秒。
首轮全套测试有一项旧复杂附注回归仍用当前代码比对旧报告而失败；改为实际执行
冻结 CLI，并额外比较除新增审计观察外的全部旧 bundle 字段。针对性首次重跑还
发现测试漏导入 `deepcopy`，补齐后通过；未修改解析器或旧报告以迎合这些断言。
旧复杂附注三份 JSON/Markdown 均由冻结代码重现，其他财务字段逐值相同。
完整性检查通过：规则 SHA 仍 `db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`，
538 个生产快照摘要仍 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。

```powershell
python -X utf8 scripts/pilots/build_annual_audit_blocks.py --scope docs/data-pilots/2026-10-04-annual-audit-assessment-scope.json --output storage/pilots/annual-audit-blocks-2026-10-04-v2/diagnostic-only.json --public-index docs/data-pilots/annual-audit-blocks-2026-10-04-v2/evidence-index.json --check
python -X utf8 scripts/pilots/replay_frozen_annual_audit_assessment.py --scope docs/data-pilots/2026-10-04-annual-audit-assessment-scope.json --frozen-directory docs/data-pilots/annual-audit-assessment-2026-10-04-v1 --code-commit 88fcd1763339cc792a5c63f2be93f3b50cb9bf1a
python -X utf8 -m unittest discover -s tests -q
python -X utf8 scripts/verify_workspace_integrity.py
```

本地完整报告／PDF 未由 Git 备份，仍需独立备份；仅有公开索引不能复原文字。
当前通用年报 CLI 也会返回新增原文块，不能将它的新完整 JSON 当作可直接上传的
字段报告；本批使用上面的本地 `storage/` 输出和显式公开索引投影。
下一项可按既定优先级有界评估租赁标签变体；不因本次观察接入真实硬门。
规则 v1.3.2、历史发布记录、基准适配器／Reader、538 个生产快照不变，
九域与真实策略编排仍为 `not_ready`。
