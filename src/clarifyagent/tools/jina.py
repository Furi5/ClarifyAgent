import asyncio
import requests
import os
from functools import partial
from ..config import JINA_API_KEY, MAX_CONTENT_CHARS


def truncate_content(text: str, max_chars: int = None) -> str:
    """Truncate content to max_chars, keeping beginning and end."""
    max_chars = max_chars or MAX_CONTENT_CHARS
    if len(text) <= max_chars:
        return text
    
    # Keep 70% from beginning, 30% from end
    head_chars = int(max_chars * 0.7)
    tail_chars = max_chars - head_chars - 50  # 50 for separator
    
    return (
        text[:head_chars] + 
        "\n\n... [内容已截断，共 " + str(len(text)) + " 字符] ...\n\n" + 
        text[-tail_chars:]
    )


async def jina_read(url: str, max_chars: int = None) -> str:
    """
    Read and extract content from a URL using Jina API.
    
    硬超时 + 零重试策略：避免长时间等待和重复失败。
    """
    from ..config import JINA_TIMEOUT
    # 注意：JINA_RETRIES 配置存在但未使用，因为 requests.get 本身不支持重试
    # 零重试策略通过不实现重试逻辑来实现
    headers = {
        "Authorization": f"Bearer {JINA_API_KEY}",
        "X-Engine": "browser",
        "X-Retain-Images": "none",
        "X-Return-Format": "markdown"
    }
    loop = asyncio.get_event_loop()
    # 使用 Jina 专用超时（默认3秒），零重试
    response = await loop.run_in_executor(
        None,
        partial(requests.get, url, headers=headers, timeout=JINA_TIMEOUT)
    )
    # 检查响应状态
    if response.status_code != 200:
        raise Exception(f"Jina API returned status {response.status_code}")
    content = response.text
    return truncate_content(content, max_chars or MAX_CONTENT_CHARS)

if __name__ == "__main__":
    url = "https://news.yaozh.com/archive/44348.html"
    response = jina_read(url)
    with open("response.md", "w", encoding="utf-8") as f:
        f.write(response)