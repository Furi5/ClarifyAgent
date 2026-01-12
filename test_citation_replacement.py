"""测试引用标记替换为可点击链接"""
import re

# 模拟的 ID 到 URL 映射
id_to_source = {
    'nature': type('Source', (), {'url': 'https://www.nature.com/articles/s41586-024-12345-6'}),
    'fda': type('Source', (), {'url': 'https://www.fda.gov/drugs/drug-approvals'}),
    'clinicaltrials': type('Source', (), {'url': 'https://clinicaltrials.gov/study/NCT12345678'}),
    'pubmed': type('Source', (), {'url': 'https://pubmed.ncbi.nlm.nih.gov/38765432/'}),
    'nature2': type('Source', (), {'url': 'https://www.nature.com/articles/s41591-024-98765-4'}),
}

# 测试文本
test_text = """# STAT6 小分子抑制剂开发现状

STAT6 小分子抑制剂已成为炎症性疾病治疗的新兴热点[nature][fda]。全球超过 18 家公司正在开发 22 种 STAT6 相关药物[clinicaltrials]。

## 研发管线

Kymera Therapeutics 的 KT-621 代表了新一代 STAT6 降解剂[nature2]，在 Th2 介导的炎症疾病中显示出良好前景[pubmed]。

这是一个普通的 [文本链接](https://example.com)，不应该被替换。
"""

print("原始文本:")
print(test_text)
print("\n" + "="*80 + "\n")

# 替换函数
def replace_citation_with_link(match):
    """将 [source_id] 替换为 [[source_id](url)]"""
    source_id = match.group(1)

    # 查找对应的 URL
    if source_id in id_to_source:
        source = id_to_source[source_id]
        url = source.url
        # 返回 Markdown 链接格式
        return f"[[{source_id}]({url})]"
    else:
        # 如果找不到，保持原样
        return f"[{source_id}]"

# 使用正则表达式替换所有引用
# 匹配 [word] 或 [word2] 格式（不匹配 Markdown 链接）
result_text = re.sub(
    r'\[([a-z]+\d*)\](?!\()',  # 匹配 [nature] 但不匹配 [text](url)
    replace_citation_with_link,
    test_text
)

print("替换后文本:")
print(result_text)
print("\n" + "="*80 + "\n")

# 验证替换结果
print("验证:")
print("✓ [nature] 是否被替换:", "[[nature](" in result_text)
print("✓ [fda] 是否被替换:", "[[fda](" in result_text)
print("✓ [clinicaltrials] 是否被替换:", "[[clinicaltrials](" in result_text)
print("✓ [nature2] 是否被替换:", "[[nature2](" in result_text)
print("✓ [pubmed] 是否被替换:", "[[pubmed](" in result_text)
print("✓ [文本链接](url) 是否保持不变:", "[文本链接](https://example.com)" in result_text)
