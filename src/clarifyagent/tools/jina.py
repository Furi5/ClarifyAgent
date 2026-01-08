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
    """Read and extract content from a URL using Jina API."""
    headers = {
        "Authorization": f"Bearer {JINA_API_KEY}",
        "X-Engine": "browser",
        "X-Retain-Images": "none",
        "X-Return-Format": "markdown"
    }
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        partial(requests.get, url, headers=headers)
    )
    content = response.text
    return truncate_content(content, max_chars or MAX_CONTENT_CHARS)

if __name__ == "__main__":
    url = "https://news.yaozh.com/archive/44348.html"
    response = jina_read(url)
    with open("response.md", "w", encoding="utf-8") as f:
        f.write(response)