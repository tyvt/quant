# 华域汽车：精确括号编号与小节终点修复

日期：2026-10-03。限定为原文提取诊断，不是企业硬门、真实 PIT 运行、排名或投资判断。

## 修复边界

本轮按本地龟龟 skill 的证据边界区分小节观察、币种声明和历史 PIT。
仅修改 `scripts/parsing/annual_report_parser.py` 的本位币小节定位：

- 保留原数字／顿号小节路径；不修改全局 `_title`，不普遍去掉括号。
- 新路径只接受完整原生同行 `(6)记账本位币`，以及唯一、同页的下一编号小节
  `(7)同一控制下和非同一控制下企业合并的会计处理方法`。
- 两者必须在既有唯一会计政策章节内；遇到中间编号标题、错误编号／标题、缺失／重复
  终点、混合格式、跨页、跨行、截断或旋转，不扩大扫描范围。
- 只在新路径输出 `currency_subsection_observation`：四个标题的 PDF SHA-256、原文、
  物理页码及坐标。`currency_verified=false`，不能替代 `currency_evidence`。
- 没有发行人、证券、页码或金额专用解析分支。声明语序、子公司尾句、主表表头／单位／
  金额、附注引用、租赁和审计入口不作扩展。

## 实际结果

同一源为公告 `1223375149`，224 页，PDF SHA-256：
`0e6c40acb8919acef249e2ce3520ff7c7bba00f524e8ccff34d1d58f88f996c8`。
原文 URL 见冻结输入 [600741-inputs](2026-10-03-annual-report-bundle-600741-inputs.json)。
本次重新目视检查既有物理 85 页渲染图，属于同会话源页自查，不是第三方复核。

新定位绑定：会计政策根 84 页；`(6)` 和 `(7)` 均 85 页；主章末“三、税项”103 页。
原生坐标和标题均随新 JSON 保存。定位成功不等于币种识别成功：
首句“本公司记账本位币为人民币。”及同排子公司说明仍不在支持语法内。
`currency=null`、三张主表 `CURRENCY_EVIDENCE_UNKNOWN`、七项金额及比较栏仍 null。
本轮未用后验数值回填，也未计算 alpha、FCF 或企业门控。

## 新旧身份及重放

[首次失败 v1](annual-holdout-600741-2026-10-03-v1/diagnostic-only.json)不改写，使用
`9cf2ed9e5ecdc795b381e6c2016698bfe10a9cd0` 六个白名单代码 blob 实际重放：

- JSON SHA-256：`3aa09e2f3bbea3ed3f04a4970b736747a9bc374755802235e6d543640388a6ca`。
- Markdown SHA-256：`f95244c62f56476b9a2c7cd44b63e9afad64e66379e6f8f3acf3a041cd9046ce`。

[新 v2 JSON](annual-parenthesized-currency-600741-2026-10-03-v2/diagnostic-only.json)／
[Markdown](annual-parenthesized-currency-600741-2026-10-03-v2/diagnostic-only.md)单独保存：

- 解析器 SHA-256：`2bd52ab9c2a2e4a02cfb60e208b3dd984ba1123317414476b4b0730c8ac52456`。
- logical_content_hash：`646c3b1e0f41a28abfff373fb349940f17a8d82569b5f2a0a940344f8bd0bfcb`。
- JSON SHA-256：`ba1220019e8667e37233ea3f3e4e0a14df4046bc7644b220d6c43a7eea6174a5`。
- Markdown SHA-256：`bd0eb2db81cf1dddac1728faf37a83527a7db7bb088969d7070d0fc74c269041`。

## 验证与停止条件

新增 31 项针对性回归：精确标题对、全局标题不放宽、错误编号／标题、混合边界、
缺失／重复／顺序错误／越界终点、范围、旋转／截断／跨页／拆行、同行碎片、
内外冲突边界、未支持声明保留、真实四处绑定、旧 Git 重放和冷热缓存确定性。
支持语法的正例使用合成原生几何，不能称为华域实际币种已核实。

第一次针对性运行发现两个实现问题：过宽的括号候选把隆基子公司名称段误计为标题；
拆行标题的后一行被当成旧裸标题。已将候选收紧为完整编号标题，并拒绝独立编号与
后一行裸标题拼接；未修改原文、旧结果或更改旧回归断言。90 项关联测试随后通过。
`python -X utf8 -m unittest discover -s tests -q`：1075 项通过，无跳过（79.123 秒）。
工作区完整性核验：规则哈希仍 `db43fd01…`，538 个生产快照文件清单仍 `2f77ef0b…`。

时点仍为 `UNKNOWN_UNLESS_VERIFIED`，`diagnostic_available_at=null`，历史 PIT 准入 0。
不导出真实硬门输入，九域及真实策略编排状态不变。`RULE_SPEC.md` 和生产快照未修改。
修复后华域属于回归样本；下一家在冻结本次代码后重新按元数据选样，不据少数样本估计
全市场准确率。不在本轮继续修复华域声明或尾句。

复现入口：

```powershell
python -X utf8 scripts/extract_annual_report_bundle.py --scope docs/data-pilots/2026-10-03-annual-report-bundle-600741-inputs.json --output docs/data-pilots/annual-parenthesized-currency-600741-2026-10-03-v2 --check
python -X utf8 -m unittest tests.test_annual_report_parenthesized_currency -q
```
