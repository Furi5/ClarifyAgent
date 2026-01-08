# tools/serperapi.py
import asyncio
from functools import partial
from serpapi import GoogleSearch

import os
from dotenv import load_dotenv

load_dotenv()

SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

# 默认配置
DEFAULT_NUM_RESULTS = 3
DEFAULT_MAX_SNIPPET = 300


def _search_sync(query: str, num_results: int = None) -> dict:
    """同步搜索"""
    num_results = num_results or DEFAULT_NUM_RESULTS
    search = GoogleSearch({
        "q": query,
        "api_key": SERPAPI_API_KEY,
        "num": num_results,
    })
    return search.get_dict()


async def web_search(query: str, num_results: int = None) -> str:
    """异步包装，返回格式化的搜索结果"""
    num_results = num_results or DEFAULT_NUM_RESULTS
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, 
        partial(_search_sync, query, num_results)
    )
    return format_search_result(result, max_results=num_results)


def truncate_text(text: str, max_chars: int) -> str:
    """截断文本"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def format_search_result(result: dict, max_results: int = None, max_snippet: int = None) -> str:
    """把搜索结果格式化成 LLM 友好的文本"""
    max_results = max_results or DEFAULT_NUM_RESULTS
    max_snippet = max_snippet or DEFAULT_MAX_SNIPPET
    lines = []
    
    # Knowledge Graph (如果有)
    if kg := result.get("knowledge_graph"):
        if title := kg.get("title"):
            lines.append(f"## {title}")
        if desc := kg.get("description"):
            lines.append(truncate_text(desc, max_snippet))
        lines.append("")
    
    # Organic Results - 限制数量
    organic = result.get("organic_results", [])
    if organic:
        lines.append("### 搜索结果:")
        for i, item in enumerate(organic[:max_results], 1):
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            link = item.get("link", "")
            lines.append(f"{i}. **{title}**")
            if snippet:
                lines.append(f"   {truncate_text(snippet, max_snippet)}")
            if link:
                lines.append(f"   链接: {link}")
            lines.append("")
    
    # Answer Box (如果有) - 也要截断
    if answer := result.get("answer_box"):
        if ans := answer.get("answer") or answer.get("snippet"):
            lines.insert(0, f"**直接答案:** {truncate_text(ans, max_snippet)}\n")
    
    return "\n".join(lines) if lines else "未找到相关结果"


if __name__ == "__main__":
    import asyncio
    
    async def test():
        result = await web_search("STAT6 gene function")
        print(result)
    
    asyncio.run(test())