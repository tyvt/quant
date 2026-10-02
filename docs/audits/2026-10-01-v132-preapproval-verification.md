# v1.3.2 身份字段澄清：批准前核验

核验日期：2026-10-01。状态：**核验完成；提案尚待项目负责人正式生效批准。**

核验对象为 [v1.3.2-20261001-01 提案](../rule-proposals/2026-10-01-v132-benchmark-identity-clarification.md)。项目负责人的上一条审查意见为“建议批准”，并要求先复核文件哈希。本记录落实该核验及既有身份校验的测试补充，不将建议自动登记为生效裁决。

## 文件身份

| 文件 | 当前 SHA-256 | 核验结果 |
| --- | --- | --- |
| `RULE_SPEC.md` | `11f50fa67c1dfe5065ddcaf1994308b8357355d2425580556b77ba7d2dea250f` | 与已背书 v1.3.1 基线一致 |
| v1.3.2 提案 | `dd6b54bbf388b604194f9090089c7e0e8527a41ec86d78e8695564e7e0ce8a51` | 与提交复核时的提案文本一致 |
| `docs/releases/v1.3.1.md` | `1d777d700d3e558b3385ad71120c10dd08f099f7aa2276c0731ad2090e9efdeb` | 保持原样 |
| `docs/releases/v1.3.1-identity-reattest.md` | `b1ed1e686749bb4de7ac9917f332584f12707b6454868bf7f391cf608ac0d7cd` | 保持原样 |

## 已完成的实现核验与回归

现有 `csindex_benchmark.py` 在进入隔离日处理前，逐行同时校验 `indexCode`、`indexNameCnAll` 和 `indexNameEnAll`。规范值为 `H00985`、`中证全指全收益指数` 和 `CSI All Share Total Return Index`；字段缺失或任一不匹配抛出身份漂移错误。请求参数及正的有限 close 校验均已存在。

补充的测试验证已经由 v1.3.0/v1.3.1 批准并实现的行为：

- `test_approved_exclusion_rows_reject_identity_drift`：分别对 `2005-01-01` 和 `2018-06-18` 检查错误代码、错误中英文全称及英文尾部空格均硬失败，防止按白名单跳过身份核验。
- `test_approved_exclusion_rows_require_all_identity_fields`：两日分别缺少任一身份字段均硬失败。
- `test_missing_identity_fields_hard_fail`：普通交易日缺少任一身份字段均硬失败。

验收命令：`python -m unittest discover -s tests -p 'test_csindex_benchmark_*.py' -q`，17 项通过；随后 `python -m unittest discover -s tests -q`，**309 项通过**。

生产适配器实现未改；当前排除证据版本仍为 `v1.3.1`，批准版本表仍只接受 `v1.3.0` 与 `v1.3.1`。本轮没有改写规则基线、提案、历史发布记录或已发布快照，没有建立生效的 v1.3.2 发布记录。正式批准后按提案执行唯一正文替换、版本及变更记录更新，再记录生效后规则文件哈希与验收结果。
