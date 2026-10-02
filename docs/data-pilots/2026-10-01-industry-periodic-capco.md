# 中上协定期行业分类来源探针（2026-10-01）

**结论：官方按期、按证券代码排序的全表 PDF 可取得并定位证券；这仅证明来源可行性，不证明历史点时可用版本、全期覆盖或行业 Profile 映射。`ParquetIndustryReader` 仍为 `not_ready`。**

中上协官网分别列出[2024 年下半年结果（2025-04-18 发布）](https://www.capco.org.cn/xhgg/hyfl/hyfljg/202504/20250418/j_2025041815003000017449597508305299.html)
和[2025 年上半年结果（2025-09-30 发布）](https://www.capco.org.cn/xhgg/hyfl/hyfljg/202509/20250930/j_2025093014371200017592143530187679.html)。
按代码排序的官方 PDF 分别为[2024H2](https://sp.capco.org.cn:82/file/202603/hangyefenlei/2024xiaban/hangyefenleigupiaodaima.pdf)
和[2025H1](https://sp.capco.org.cn:82/file/202603/hangyefenlei/2025shangban/hangyefenleigupiaodaima.pdf)。
原始 bytes 本地保存于 `storage/pilots/industry-history-2026-10-01/`，文件身份、页码和样本值见
[结构化证据](2026-10-01-industry-periodic-capco.json)；不发布快照。

两期 PDF 中，`600000` 分别位于第 61 页，门类 `J`、大类 `66`（货币金融服务）；
`600519` 分别位于第 68/69 页，门类 `C`、次类 `CA`、大类 `15`（酒、饮料和精制茶制造业）。
这证明样本的官方统计分类可以从 PDF 提取；**不能**把 `C15` 自动等同于
`GENERAL_FCF` 全部行业敏感规则已适用，也不能把 PDF 的股票简称代替独立证券状态域。

关键 PIT 边界：两份文章显示历史发布日期，但今天下载到的附件路径都位于
`/file/202603/`。这可能是官网迁移，**不能据此证明现在的附件 bytes 与原发布日的 bytes 完全相同**。
因此本探针的 `exact_first_observed_at_utc=null`、
`historical_pdf_bytes_proven_at_original_publication=false`；
不得将当前下载文本倒填 2025 年历史 `as_of`。
正式接入前需证明原始发布版本、修订/更正链、各期证券全集（含退市者）、
分类代码体系跨版映射、具体可用时点及许可证，再以不可变快照和真实 PIT fixture 验收。
