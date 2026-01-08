"""
Smart scraper module - inspired by GPT-Researcher's approach.

Key strategies:
1. Extract main content, remove boilerplate
2. Use LLM to summarize if content is too long
3. Return structured data for better processing
"""
import asyncio
import requests
import re
from functools import partial
from typing import Optional, Dict, List
from ..config import JINA_API_KEY, MAX_CONTENT_CHARS


# 更短的限制，因为我们会用 LLM 来摘要
MAX_RAW_CONTENT = 15000  # 原始内容最大长度
MAX_SUMMARY_CONTENT = 3000  # 摘要后的目标长度


def clean_content(text: str) -> str:
    """Clean scraped content - remove boilerplate, ads, etc."""
    if not text:
        return ""
    
    # 移除多余空白行
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # 移除常见的无用内容
    patterns_to_remove = [
        r'Cookie[s]? Policy.*?(?=\n\n|\Z)',
        r'Privacy Policy.*?(?=\n\n|\Z)',
        r'Terms of (Service|Use).*?(?=\n\n|\Z)',
        r'Subscribe to.*?(?=\n\n|\Z)',
        r'Sign up for.*?(?=\n\n|\Z)',
        r'Advertisement.*?(?=\n\n|\Z)',
        r'Share this article.*?(?=\n\n|\Z)',
        r'Related Articles.*?(?=\n\n|\Z)',
        r'©.*?\d{4}.*?(?=\n|\Z)',
        r'\[.*?Cookie.*?\]',
        r'Accept All Cookies.*?(?=\n|\Z)',
    ]
    
    for pattern in patterns_to_remove:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # 移除过短的行（通常是导航、按钮等）
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        # 保留有意义的内容（超过20字符或是标题）
        if len(stripped) > 20 or stripped.startswith('#'):
            cleaned_lines.append(line)
    
    text = '\n'.join(cleaned_lines)
    
    # 再次清理多余空白
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def extract_key_sections(text: str, max_chars: int = MAX_RAW_CONTENT) -> str:
    """Extract key sections from content, prioritizing beginning and important parts."""
    if len(text) <= max_chars:
        return text
    
    # 分段
    paragraphs = text.split('\n\n')
    
    # 优先保留：标题、开头段落、包含关键词的段落
    key_words = ['结论', 'conclusion', 'summary', '摘要', 'abstract', 
                 'result', '结果', 'finding', '发现', 'key', '关键']
    
    selected = []
    current_length = 0
    
    # 1. 先取开头 30%
    head_budget = int(max_chars * 0.4)
    for p in paragraphs[:10]:  # 最多取前10段
        if current_length + len(p) > head_budget:
            break
        selected.append(p)
        current_length += len(p) + 2
    
    # 2. 查找包含关键词的段落
    remaining_budget = max_chars - current_length - 100
    for p in paragraphs[10:]:
        if current_length >= max_chars - 100:
            break
        p_lower = p.lower()
        if any(kw in p_lower for kw in key_words):
            if len(p) < remaining_budget:
                selected.append(p)
                current_length += len(p) + 2
                remaining_budget -= len(p) + 2
    
    result = '\n\n'.join(selected)
    
    if len(result) < len(text):
        result += f"\n\n... [已提取关键内容，原文 {len(text)} 字符]"
    
    return result


async def smart_scrape(url: str, max_chars: int = None) -> Dict:
    """
    Smart scraping with content extraction and cleaning.
    
    Returns structured data:
    {
        "url": str,
        "title": str,
        "content": str,
        "success": bool,
        "error": str (if failed)
    }
    """
    max_chars = max_chars or MAX_SUMMARY_CONTENT
    
    try:
        headers = {
            "Authorization": f"Bearer {JINA_API_KEY}",
            "X-Engine": "browser",
            "X-Retain-Images": "none",
            "X-Return-Format": "markdown"
        }
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            partial(requests.get, f"https://r.jina.ai/{url}", headers=headers, timeout=30)
        )
        
        if response.status_code != 200:
            return {
                "url": url,
                "title": "",
                "content": "",
                "success": False,
                "error": f"HTTP {response.status_code}"
            }
        
        raw_content = response.text
        
        # 1. 清理内容
        cleaned = clean_content(raw_content)
        
        # 2. 提取关键部分
        extracted = extract_key_sections(cleaned, MAX_RAW_CONTENT)
        
        # 3. 如果仍然太长，截断
        if len(extracted) > max_chars:
            extracted = extracted[:max_chars - 50] + f"\n\n... [截断至 {max_chars} 字符]"
        
        # 尝试提取标题
        title = ""
        lines = extracted.split('\n')
        for line in lines[:5]:
            if line.startswith('# '):
                title = line[2:].strip()
                break
            elif line.strip() and len(line.strip()) < 200:
                title = line.strip()
                break
        
        return {
            "url": url,
            "title": title[:100] if title else url,
            "content": extracted,
            "success": True,
            "error": None
        }
        
    except Exception as e:
        return {
            "url": url,
            "title": "",
            "content": "",
            "success": False,
            "error": str(e)
        }


async def scrape_urls(urls: List[str], max_chars_per_url: int = None) -> List[Dict]:
    """Scrape multiple URLs in parallel."""
    max_chars = max_chars_per_url or MAX_SUMMARY_CONTENT
    
    tasks = [smart_scrape(url, max_chars) for url in urls[:5]]  # 最多5个URL
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    processed = []
    for r in results:
        if isinstance(r, Exception):
            processed.append({
                "url": "",
                "title": "",
                "content": "",
                "success": False,
                "error": str(r)
            })
        else:
            processed.append(r)
    
    return processed
