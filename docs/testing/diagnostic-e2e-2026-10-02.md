# Git 恢复与限定诊断端到端验收

本轮顺序为 Git 基线 → 独立快照哈希清单 → 端到端诊断。不补下一个字段，不修改规则或任何域的 ready 状态。

## Git 基线与备份边界

- `65ec236ab72c52b7b10e5d47c5db81e853754af2`：首次保存现有 v1.3.2 代码、规则、文档、测试、fixture 与工具。不是重建 v1.3.1 发布时的未知 bytes。
- 后续 `cf22bda`：修正原 `.gitignore` 中 `storage/` 会同时忽略 `turtle_quant/storage/` 源码的问题；改为 `/storage/`，补纳入九个源码文件。不改写首次提交。
- 仓库局部 `core.autocrlf=false`；`.gitattributes` 对所有文件及获批规则/发布记录明确禁用 text、filter、ident 转换。它约束 Git，不阻止编辑器改写。
- 根目录 `/storage/`、Python 缓存、`.env` 与常见凭证文件不入 Git。提交前检查实际暂存列表，不依赖忽略规则作为凭证审核的替代。
- 本地 Git **不等于异地备份**。没有创建远程、没有上传任何代码/数据、没有发送询证。Git 外原始 PDF/Parquet 仍需项目负责人指定外部硬盘/NAS/私有备份位置；当前异地备份未完成。
- Git commit ID 用于版本定位，不替代逐文件 SHA-256。Git blob 的 SHA-1 包含对象头，commit 的 SHA-1 还包含父提交与元数据；均不是规则文件 SHA-256。

已提交的 [快照清单](../audits/storage-snapshot-manifest-2026-10-02.json) 逐项记录 538 个生产快照文件路径/哈希，摘要仍为 `2f77ef0b7fbf2588d80735f161a39c7d4694a6e5b1c57a612f592018560d1270`。同时绑定规则、三份发布记录、基准代码、四份旧诊断及既有单字段补证。清单**不包含所有 storage/raw PDF，也不是数据备份**；旧诊断 manifest 另行绑定其 PDF/目录证据。

```powershell
python -X utf8 scripts/verify_workspace_integrity.py
git status --short
git fsck --full
```

校验工具直接以 subprocess 的 bytes 读取 `git show <commit>:<path>`，逐字节及 SHA-256 对比工作区；不通过 PowerShell 文本管道，避免管道自身重新编码。

## 一条命令跑整条管线

新增工具及依赖必须先提交，才能从 Git 恢复完整代码：

```powershell
python -X utf8 scripts/pilots/run_diagnostic_e2e.py
python -X utf8 scripts/pilots/run_diagnostic_e2e.py --check
python -m unittest discover -s tests -q
```

默认输出至新的 `docs/testing/diagnostic-e2e-2026-10-02/`。拒绝覆盖已有目录；复核用 `--check`，需要新运行时用 `--output-dir <新目录>`。`--check` 固定使用已有验收报告中记录的代码提交，不因为 HEAD 增加验收文档而改变运行身份。

管线从 `git archive` 解出全新临时代码目录，核对代码、冻结文件与清单的原始字节；两次以 `python -I -X utf8` 启动独立进程，忽略宿主 PYTHONPATH。证据显式从原本地工作区读取，不复制或修改原始数据。

真实证据路径：目录/PDF 字节与身份/物理页校验 → 既有版本/区间算术 → `UNKNOWN_UNLESS_VERIFIED` PIT 准入 → ready 纯前提/股本政策逻辑 → ready 纯 `pipeline.decision.decide` → JSON/Markdown → 重读和内容哈希 → 第二进程逐字节复现。

四个真实样本仍各自独立，`as_of=2026-09-30`；历史 PIT 观察准入为 0，`available_at=null`，决策只验证 `NEEDS_REVIEW` 传播。财报使用既有六个 UNKNOWN 前提门；股本保持 UNKNOWN 政策门；回购使用证据缺口门，**不伪造完整财务前提**。估值不执行、评分未知，不拿虚拟数值凑完整路径。

正向技术路径另行运行原有 `test_benchmark_technical_integration.py` 的四项联调：合成财务/策略/交易输入 × 已验收真实 H00985，覆盖四类决策、月度诊断阻断、manifest、成交与绩效逻辑稳定性和基准缺日。合成交易/净值/数值绩效仅在内存断言，不保存到真实样本报告。失败、跳过、预期失败均不得算验收通过。

## 失败注入与验收范围

- 错误源 SHA-256、JSON 重复键、UNKNOWN 填零、诊断输出权限升级、排名字段、已有输出覆盖均须失败。
- 恢复出的代码缺少外部原始快照时，必须明确失败且不写输出，不能用跳过或空结果宣称恢复成功。
- 两个独立进程的 11 个管线产物逐字节一致；十个既有 JSON/Markdown 与冻结原件逐字节一致。
- `pipeline-result.json` 记录真实样本缺口传播与技术对照断言，不替代 StrategyRunManifest、不宣称真实策略已开放。
- `e2e-report.json` 绑定恢复提交、运行代码 SHA-256、规则/快照身份、管线产物哈希与测试/失败注入结论；自身逻辑哈希仅排除顶层 `logical_content_hash`，无运行时钟或临时路径。

这里证明的是**可恢复代码的管线行为和确定性**，不是必要输入完整、历史 PIT 可用或策略有效。九个未就绪域、真实编排、官方 Top-N 与真实回测权限均不改变。

实际运行结果另见生成的 [验收报告](diagnostic-e2e-2026-10-02/e2e-report.md)。

## 2026-10-02 实际验收

- 从提交 `121375c210ced8e210d4e23bda2fd9e57eb4f2c8` 恢复运行代码；恢复模式不依赖宿主 Python 源码导入。
- 端到端运行及 `--check` 均通过；验收报告逻辑内容哈希为 `14ede4eeb01f5afe57e0dc1bfaab922e4f50507d7a0dac959cf94f84cad9da60`。
- 新增 27 项恢复/管线回归通过；完整 `python -X utf8 -m unittest discover -s tests -q`：427 项通过，无跳过。
- `git fsck --full` 通过；规则、历史发布记录、基准代码、旧报告和 538 文件快照清单均保持原字节身份。
- 本地 Git bundle 只能作为可搬移的副本；即使通过恢复验证，仍不构成外部磁盘或异地备份。不要因本地 bundle 存在而删除唯一原始数据。
