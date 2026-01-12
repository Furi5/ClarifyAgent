# 新的引用格式示例 - 行内可点击链接

## 输出格式（Markdown 源码）

```markdown
# STAT6 小分子抑制剂开发现状

STAT6 小分子抑制剂已成为炎症性疾病治疗的新兴热点[[nature](https://www.nature.com/articles/s41586-024-12345-6)][[science](https://www.science.org/doi/10.1126/science.abcd1234)]。全球超过 18 家公司正在开发 22 种 STAT6 相关药物[[clinicaltrials](https://clinicaltrials.gov/study/NCT12345678)]，市场规模预计从 2029 年的 32.6 亿美元增长到 2035 年的 70.1 亿美元[[marketsandmarkets](https://www.marketsandmarkets.com/Market-Reports/stat6-inhibitor...)]。

## 一、研发管线与开发阶段

Kymera Therapeutics 的 KT-621 代表了新一代 STAT6 降解剂[[nature2](https://www.nature.com/articles/s41591-024-98765-4)]，为每日一次口服药物，在 Th2 介导的炎症疾病中显示出良好前景[[pubmed](https://pubmed.ncbi.nlm.nih.gov/38765432/)]。该药物目前处于临床 1 期阶段[[clinicaltrials2](https://clinicaltrials.gov/study/NCT98765432)]。

## 二、临床进展

临床数据显示，STAT6 抑制剂在特应性皮炎患者中的客观缓解率达到 45%[[nejm](https://www.nejm.org/doi/full/10.1056/NEJMoa2024567)]，显著优于安慰剂组[[lancet](https://www.thelancet.com/journals/lancet/article/PIIS0140-6736...)]。
```

## 渲染效果

当在 Markdown 渲染器中查看时：

---

# STAT6 小分子抑制剂开发现状

STAT6 小分子抑制剂已成为炎症性疾病治疗的新兴热点[[nature](https://www.nature.com)][[science](https://www.science.org)]。全球超过 18 家公司正在开发 22 种 STAT6 相关药物[[clinicaltrials](https://clinicaltrials.gov)]，市场规模预计从 2029 年的 32.6 亿美元增长到 2035 年的 70.1 亿美元。

## 一、研发管线与开发阶段

Kymera Therapeutics 的 KT-621 代表了新一代 STAT6 降解剂[[nature2](https://www.nature.com)]，为每日一次口服药物。

---

## 关键特性

1. ✅ **可点击链接**: `[nature]` 直接变成超链接，点击跳转到原文
2. ✅ **无需参考文献**: 不再有末尾的参考文献列表
3. ✅ **简洁直观**: 网站简称作为链接文本，一眼看出来源
4. ✅ **真实 URL**: 使用 SerpAPI 提供的真实链接，100% 准确
5. ✅ **行内嵌入**: 引用直接跟在句子后面，不打断阅读

## 格式说明

- **Markdown 格式**: `[[网站简称](URL)]`
- **渲染后**: 显示为可点击的 `[nature]` 链接
- **多来源**: `[[nature](url1)][[fda](url2)]` 连续多个链接
- **同网站**: `nature`, `nature2`, `nature3` 自动编号

## 支持的网站简称

| 简称 | 网站 | 示例 |
|------|------|------|
| `nature` | Nature 系列期刊 | [[nature](https://nature.com)] |
| `science` | Science 系列期刊 | [[science](https://science.org)] |
| `pubmed` | PubMed 文献库 | [[pubmed](https://pubmed.ncbi.nlm.nih.gov)] |
| `clinicaltrials` | ClinicalTrials.gov | [[clinicaltrials](https://clinicaltrials.gov)] |
| `fda` | FDA 官网 | [[fda](https://fda.gov)] |
| `nejm` | NEJM | [[nejm](https://nejm.org)] |
| `lancet` | The Lancet | [[lancet](https://thelancet.com)] |

## 技术实现

1. **LLM 生成**: `[nature][fda]` 格式
2. **自动替换**: `[nature]` → `[[nature](真实URL)]`
3. **正则匹配**: 只替换引用标记，不影响其他 Markdown 链接
4. **URL 映射**: 从 source ID 到真实 URL 的映射表
