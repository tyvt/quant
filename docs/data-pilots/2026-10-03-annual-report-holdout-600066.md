# 第八发行人宇通客车：冻结代码首次盲跑

日期：2026-10-03。单发行人、单指定全文、原文提取诊断；不是真实规则运行、排名、
选股或投资建议。按本地龟龟 skill 保留证据、假设和历史 PIT 的区别。

## 先冻结再盲跑

华域括号小节修复通过 1075 项完整测试后保存提交
`d08668ab0aadf84b9925a08adbeda8148f13710a`，提交内六项代码、规则及依赖可重放。
工作区查询 `docs/data-pilots/`、`scripts/`、`tests/` 未见宇通客车／600066 既有样本。
本次只据新发行人和官方目录元数据选样，不按数值、硬门结论或 PDF 版面挑选。
“独立”仅指该样本未参与此前工具修复，不是独立人员、第二模型或第三方复核。

[冻结计划](2026-10-03-annual-holdout-600066-plan.json)在抓取及首次 CLI 前写入。
选样前一次证券身份查询和一次目录查询均 HTTP 200；官方首页浏览工具的一次超时
不作披露缺失证据。正式固定读取仅两次：官方目录 POST、指定全文 PDF GET，
不重试、不跟随重定向、不回退第三方、不读取摘要 PDF。
抓取工具只读 PDF 签名、页数，不查看正文或渲染。
首次 CLI 退出码 0，先保存 [v1 JSON](annual-holdout-600066-2026-10-03-v1/diagnostic-only.json)
及 [Markdown](annual-holdout-600066-2026-10-03-v1/diagnostic-only.md)，之后才搜索源文和
查看物理 1／71／98 页图像。本轮无解析器追修、人工值注入或换样重做。

## 固定来源与身份

[官方全文](https://static.cninfo.com.cn/finalpage/2025-04-01/1222974533.PDF)：
宇通客车股份有限公司，`sh.600066`，声明年度 2024，公告 `1222974533`，158 页。
目录同时有摘要 `1222974523`；只固定指定全文，当前目录完整不等于历史修订／撤回全集。

| 对象 | SHA-256 |
|---|---|
| 冻结计划 | `a6e8d5cf20fd7e93f86ee911ab1c81bcf23255c5123a25aa74f9cfd243347b25` |
| 官方目录原始 bytes | `5bf2589bc875aff3268d614ba0aa0fcbec4d8ddbb2d5c6856077ebc9dcb090e6` |
| PDF 原始 bytes（3,680,189 字节） | `5edfe6e4ac095d6c28e17903cc87e284b5d8f75ba3be3f4515a0fbb92f5bc023` |
| 输入范围 | `c9c929229754fc5591561f639c9452c5862ca71087e15395896a6cd4b0a8b69a` |
| 抓取索引 | `8e502287a8859c1e91881ee22b85d636e92cb1614b191aeb50b8888ac49f4f32` |
| 首次 JSON | `f079521b6c017b45ae4c89e8a5c275308f1a92bd2dcde3e552f9b29d20ef57e9` |
| 首次 Markdown | `de2f366b8be1e6249f6c5b568441a5da1468a6102b24be039051a53510ee6d93` |

首次 `logical_content_hash`：
`ec7af2ae4efc412bca88c138e360cd1a75fb29f639f2f8cce14172a6ebe093ad`。
[输入](2026-10-03-annual-report-bundle-600066-inputs.json)和
[抓取索引](2026-10-03-annual-holdout-600066-capture.json)均为生成的原始 bytes 副本。
目录和 PDF 留在忽略的 `storage/pilots/annual-holdout-600066-2026-10-03/`，Git 不备份它们。

## 首次结果与后验定位分离

首次主表自动提取未通过，但文档身份入口通过、程序正常生成诊断包：

- `currency=null`，`currency_evidence=[]`，没有已识别的本位币小节观察。
- 三张主表均 `CURRENCY_EVIDENCE_UNKNOWN`；七项金额、比较栏均 null，候选为空。
- 租赁部分、完整租赁现金、审计类型与历史 PIT 均 UNKNOWN。

首次结果保存后的原生行搜索及上述三页目视自查发现：

- 71 页“五、重要会计政策及会计估计”是明确政策根；98 页“六、税项”为主章末。
- 71 页小节标题为 **`(四)记账本位币`**，下一小节为
  **`(五)重要性标准确定方法和选择依据`**。
- 小节下一原生行完整列“本公司的记账本位币为人民币。”：该声明语序已经受支持，
  但标题不受支持。不能跳过小节边界，不能因声明字符串相同就绕过守卫。
- 这是括号小节编号这一缺口族的**中文序号变体**，不是又一个完全不同的币种语序问题。
  本轮新增路径只接受 `(6)`／指定 `(7)`，不会自动接纳 `(四)`／`(五)`。
- 128—129 页另有境外子公司本位币表，不能替代发行人政策。该表不是本次输入。

上述是后验定位，不是程序成功提取或整份 158 页人工复核；未检查主表数值并将其回填。
不能据标题支持不足推定原文未披露，也不能保证扩展中文序号后全部主表必然通过。

## 重放、时点和状态

冻结 Git 提交下实际运行旧 CLI，六项代码 SHA、规则和同提交依赖均核验，JSON/Markdown
逐字节一致；不 checkout、不网络请求、不覆盖旧报告，不用保存结果代替实际计算。
18 项新增回归包含冻结计划、原始 bytes、身份漂移、目录完整性、旧 Git 重放、自哈希、
源页边界、未知输出、冷热缓存与禁止硬门导出，全部通过。
最终完整回归 `python -X utf8 -m unittest discover -s tests -q`：1093 项通过，无跳过
（80.986 秒）。回归校验冻结 Git blob，而非要求未来解析器等于本次代码；本轮另行
再次核验当前六项 bytes 与冻结提交相同。华域新 v2 也由本冻结提交重放逐字节一致。
规则 SHA-256 仍 `db43fd01f88a4db7a43859abe45d2d8903fddd765363f4763fe4287eafc33812`；
538 个生产快照文件清单摘要仍
`2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。
历史发布记录、基准适配器／Reader 与旧报告未改写。

目录 `announcementTime=1743436800000` 不是最早公众可用证明；2026-10-03 抓取时间
不倒填历史 PIT。继续 `UNKNOWN_UNLESS_VERIFIED`，`diagnostic_available_at=null`，历史
PIT 准入数量 0，修订／撤回全集未认证。九个生产域与真实策略编排状态未变。

本轮到此停止。下一项如继续，仅评估明确中文序号小节与下一同格式边界的通用定位，
需补错序号、重复、其他章节、范围、跨页／截断等逆向测试。新结果另存，不改写本计划
或首次失败，不据八家选择样本推算全市场准确率。

```powershell
python -X utf8 scripts/pilots/replay_frozen_annual_bundle.py --scope docs/data-pilots/2026-10-03-annual-report-bundle-600066-inputs.json --frozen-directory docs/data-pilots/annual-holdout-600066-2026-10-03-v1 --code-commit d08668ab0aadf84b9925a08adbeda8148f13710a
python -X utf8 -m unittest tests.test_annual_report_eighth_holdout -q
```
