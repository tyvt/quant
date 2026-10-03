# 宇通客车：中文序号小节与同格式边界修复

日期：2026-10-03。单源原文诊断，不是真实 PIT 规则运行、官方排名或投资判断。
按本地龟龟 skill 分开记录原文观察、计算和历史可用性。

## 有界改动

仅扩展 `scripts/parsing/annual_report_parser.py` 的显式小节标题对：

- 新增 `(四)记账本位币` → `(五)重要性标准确定方法和选择依据`。
- 保留原 `(6)` → 指定 `(7)` 及既有顿号／点号路径；全局 `_title` 不变。
- 共享既有唯一政策根、主章末、唯一标题／终点、下一个编号、同页、原生同行及
  未旋转／未截断的坐标约束。不按任意中文序号推断下一节，不交叉混用两个标题对。
- 不修改币种声明语序、正文尾句、主表表头、金额／单位／附注、租赁或审计入口。
- 无发行人、证券、物理页码或金额专用解析分支；本轮沿用已固定原文，无新网络抓取。

`currency_subsection_observation.currency_verified=false` 沿用原设计，表示**小节边界观察
自身不认证币种**，不是对独立 `currency_evidence` 的否定。本例 CNY 来自后者已支持的
完整发行人声明；两层证据分别保留，历史 PIT 仍未认证。

## 实际新结果

公告 `1222974533`，158 页，PDF SHA-256：
`5edfe6e4ac095d6c28e17903cc87e284b5d8f75ba3be3f4515a0fbb92f5bc023`。
[冻结输入](2026-10-03-annual-report-bundle-600066-inputs.json)未改写。

政策根及 `(四)`／`(五)` 均绑定物理 71 页，“六、税项”绑定 98 页。
“本公司的记账本位币为人民币。”符合原有语法，程序恢复 CNY。
本轮重新目视检查 71 页政策及 63／65 页主表；属于同会话自查，不是独立人员复核。

| 2024 年目标字段 | 新程序状态 | 本期观察（元） |
|---|---|---:|
| 归母净利润 | OBSERVED_NUMERIC，合并利润表 63 页 | 4,116,194,422.50 |
| 合并净利润 | OBSERVED_NUMERIC，同表同页 | 4,153,925,766.34 |
| E／N／总权益 | NOT_IDENTIFIED，资产负债表表头未通过 | UNKNOWN |
| OCF／Capex | COLUMN_EDGE_AMBIGUOUS | UNKNOWN |

OCF 本期原始数字盒右边界 438.082、Capex 438.198，均跨现金流表头推导的分列边界
438.025；不放宽边界、不以人工可见值填充、不用比较栏替代本期。
比较栏 OCF `4,716,697,728.17`、Capex `567,039,081.24` 为独立程序观察；只有比较栏
OCF 小计对账通过，本期及权益对账仍 UNKNOWN。不宣称七项主表全部成功。
租赁部分、完整 Lease_cash、审计类型仍 UNKNOWN；未生成 alpha、FCF 或企业门控。

## 独立保存身份

[新 v2 JSON](annual-chinese-subsection-600066-2026-10-03-v2/diagnostic-only.json)和
[Markdown](annual-chinese-subsection-600066-2026-10-03-v2/diagnostic-only.md)：

- 解析器 SHA-256：`ad150ea7baa3dede81cd09394a53cfb7024d4e9345bdc157f916114dea7d9ca3`。
- logical_content_hash：`931a41559f803e967976ab373c4037c4a0edd29dd9ec93ffc5257cb490818702`。
- JSON SHA-256：`4c126803522ba8961a1bd5a11b3f628ba281f4f943ea90644dc4561487b49f6a`。
- Markdown SHA-256：`3b71b642c45658a6993a8eaa2c3d1821bafc0fd6659e5dd6224d30ecbc406e8b`。

[首次 v1](annual-holdout-600066-2026-10-03-v1/diagnostic-only.json)继续由完整提交
`d08668ab0aadf84b9925a08adbeda8148f13710a` 实际重放，不覆盖旧文件：
JSON SHA `f079521b6c017b45ae4c89e8a5c275308f1a92bd2dcde3e552f9b29d20ef57e9`，
Markdown SHA `de2f366b8be1e6249f6c5b568441a5da1468a6102b24be039051a53510ee6d93`。
旧回归从该冻结代码生成的报告断言原失败，不要求当前解析器仍失败；当前代码的冷热
缓存断言只验证新结果确定性与新身份，不改变旧证据事实。

## 验收与停止条件

新增 30 项针对性回归覆盖精确中文对、错序号／标题、交叉对、混合格式、缺失／重复／
顺序／范围错误、其他章节、截断／旋转／拆行／跨页、原语序守卫、冲突、字段绑定、
未修复表头／列边界、冻结重放、缓存及禁止 PIT／硬门导出。79 项关联测试通过。
完整回归 `python -X utf8 -m unittest discover -s tests -q`：1123 项通过，无跳过
（85.570 秒）。规则 SHA 仍 `db43fd01…`，生产快照清单摘要仍 `2f77ef0b…`。

规则及 538 个生产快照文件未改写；`UNKNOWN_UNLESS_VERIFIED`、历史 PIT 准入 0、
九域与真实策略编排 `not_ready` 不变。小节修复后的宇通是回归样本，不再作为未见样本。
通过完整回归并冻结代码后再盲跑第九发行人，不在本轮追修主表或更换容易样本。

```powershell
python -X utf8 scripts/extract_annual_report_bundle.py --scope docs/data-pilots/2026-10-03-annual-report-bundle-600066-inputs.json --output docs/data-pilots/annual-chinese-subsection-600066-2026-10-03-v2 --check
python -X utf8 -m unittest tests.test_annual_report_chinese_subsection -q
```
