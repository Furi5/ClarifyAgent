"""Base tools for research agents."""
from typing import Any, List, Dict
from agents import RunContextWrapper, function_tool

from .serperapi import web_search
# from .jina import jina_read  # 已禁用以提升性能


@function_tool
async def search_academic(
    ctx: RunContextWrapper[Any],
    query: str,
    max_results: int = 10
) -> List[Dict]:
    """
    搜索学术论文和研究成果。
    
    参数：
    - query: 搜索查询，应包含关键词和领域限定（如 "KRAS G12C inhibitor clinical trial"）
    - max_results: 最大结果数，默认 10
    
    返回：
    - List[Dict]: 包含 title, authors, journal, year, abstract, url 的论文列表
    
    使用场景：
    - 查找特定主题的学术研究
    - 获取最新的研究成果
    - 查找特定药物的临床数据
    
    注意事项：
    - 查询应具体，避免过于宽泛
    - 优先返回高影响因子期刊的论文
    """
    # For now, use general web search
    # In future, can integrate with PubMed, arXiv, etc.
    result = await web_search(f"{query} site:pubmed.ncbi.nlm.nih.gov OR site:arxiv.org", max_results)
    # Parse and format as academic papers
    # This is a placeholder - actual implementation would parse the results
    return [{"title": "Academic paper", "url": "", "snippet": result}]


@function_tool
async def search_patent(
    ctx: RunContextWrapper[Any],
    query: str,
    max_results: int = 10
) -> List[Dict]:
    """
    搜索专利信息。
    
    参数：
    - query: 搜索查询，应包含关键词和领域限定
    - max_results: 最大结果数，默认 10
    
    返回：
    - List[Dict]: 包含 title, patent_number, url, abstract 的专利列表
    
    使用场景：
    - 查找特定技术的专利
    - 查找特定药物的专利信息
    - 分析专利布局
    """
    result = await web_search(f"{query} patent", max_results)
    return [{"title": "Patent", "url": "", "snippet": result}]


@function_tool
async def search_news(
    ctx: RunContextWrapper[Any],
    query: str,
    max_results: int = 10
) -> List[Dict]:
    """
    搜索新闻和最新动态。
    
    参数：
    - query: 搜索查询
    - max_results: 最大结果数，默认 10
    
    返回：
    - List[Dict]: 包含 title, url, snippet, date 的新闻列表
    
    使用场景：
    - 查找最新行业动态
    - 查找公司新闻
    - 查找临床试验最新进展
    """
    result = await web_search(f"{query} news", max_results)
    return [{"title": "News", "url": "", "snippet": result}]


@function_tool
async def search_clinical(
    ctx: RunContextWrapper[Any],
    query: str,
    max_results: int = 10
) -> List[Dict]:
    """
    搜索临床试验数据。
    
    参数：
    - query: 搜索查询，应包含药物名称或疾病名称
    - max_results: 最大结果数，默认 10
    
    返回：
    - List[Dict]: 包含 trial_id, title, status, url 的临床试验列表
    
    使用场景：
    - 查找特定药物的临床试验
    - 查找特定疾病的临床试验
    - 查找临床试验的最新进展
    """
    result = await web_search(f"{query} clinical trial site:clinicaltrials.gov", max_results)
    return [{"title": "Clinical Trial", "url": "", "snippet": result}]
