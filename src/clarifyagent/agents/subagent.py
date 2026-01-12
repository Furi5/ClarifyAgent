"""
Subagent implementation for parallel task execution.

Inspired by GPT-Researcher's approach:
1. Search first, read URL only when necessary
2. Extract key facts from snippets
3. Smart content summarization
"""
import json
import re
from typing import Any, List
from urllib.parse import urlparse
from agents import Agent, Runner, RunContextWrapper, function_tool
from agents.extensions.models.litellm_model import LitellmModel
from ..anthropic_model import AnthropicModel

from ..schema import Subtask, SubtaskResult, Source
from ..config import MAX_CONTENT_CHARS, MAX_SEARCH_RESULTS


# 更严格的限制
MAX_TOOL_OUTPUT = 2000  # 每次工具调用最大输出


def truncate_tool_output(text: str, max_chars: int = None) -> str:
    """Truncate tool output to prevent context overflow."""
    max_chars = max_chars or MAX_TOOL_OUTPUT
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 50] + f"\n\n... [截断，原长度 {len(text)} 字符]"


# ============== URL 验证函数 ==============

def is_valid_source_url(url: str) -> bool:
    """
    检查是否是有效的、完整的 source URL。
    过滤掉：
    1. 空/无效格式
    2. 不完整的 URL（如 /articles/ 结尾但没有 ID）
    3. 明显是占位符或模板的 URL
    4. LLM 编造的 URL 模板（如 $1, $3 等）
    """
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    
    # 基本格式检查
    if not url.startswith(('http://', 'https://')):
        return False
    
    # ============== 检测 URL 模板/占位符（LLM 常见错误）==============
    placeholder_patterns = [
        '$1', '$2', '$3', '$4', '$5',  # 正则捕获组占位符
        '{id}', '{slug}', '{title}', '{date}', '{year}', '{month}',  # 模板占位符
        '{{', '}}',  # 模板语法
        '[id]', '[slug]', '[article]',  # 方括号占位符
        '<id>', '<slug>',  # XML风格占位符
        '%s', '%d',  # printf 风格
        ':id', ':slug',  # 路由参数风格
    ]
    for pattern in placeholder_patterns:
        if pattern in url.lower():
            return False
    
    # 检测更通用的模式：$后跟数字
    if re.search(r'\$\d+', url):
        return False
    # ============== 结束检测 ==============
    
    try:
        parsed = urlparse(url)
        
        # 必须有有效的域名
        if not parsed.netloc or '.' not in parsed.netloc:
            return False
        
        path = parsed.path.rstrip('/')
        
        # 检查不完整的 URL 模式（路径以这些结尾但没有具体 ID）
        incomplete_endings = [
            '/articles',
            '/article', 
            '/papers',
            '/paper',
            '/publications',
            '/publication',
            '/doi',
            '/abstract',
            '/pmc',
            '/pubmed',
            '/content',
            '/view',
            '/detail',
            '/item',
        ]
        
        for ending in incomplete_endings:
            if path.endswith(ending):
                return False
        
        # 检查路径是否太短（可能不完整）
        # 例如 https://pmc.ncbi.nlm.nih.gov/articles/ 的路径是 /articles/
        path_parts = [p for p in path.split('/') if p]
        
        # 特定网站的验证规则
        netloc_lower = parsed.netloc.lower()
        
        # PubMed Central: 必须有 PMC + 数字
        if 'pmc.ncbi.nlm.nih.gov' in netloc_lower:
            # 路径应该像 /articles/PMC1234567/
            if not re.search(r'/PMC\d+', path, re.IGNORECASE):
                return False
        
        # PubMed: 必须有数字 ID
        if 'pubmed.ncbi.nlm.nih.gov' in netloc_lower:
            if not re.search(r'/\d+', path):
                return False
        
        # DOI: 必须有完整的 DOI
        if 'doi.org' in netloc_lower:
            # DOI 格式: 10.xxxx/xxxxx
            if not re.search(r'10\.\d+/', url):
                return False
        
        # arXiv: 必须有论文 ID
        if 'arxiv.org' in netloc_lower:
            if not re.search(r'\d{4}\.\d+', path):
                return False
        
        # 通用检查：URL 不能以常见的目录名结尾
        if path and len(path_parts) > 0:
            last_part = path_parts[-1].lower()
            directory_names = {'search', 'results', 'list', 'index', 'home', 'articles', 'papers'}
            if last_part in directory_names:
                return False
        
        return True
        
    except Exception:
        return False


def clean_url(url: str) -> str:
    """清理 URL，移除常见的追踪参数"""
    if not url:
        return url
    
    try:
        parsed = urlparse(url)
        # 移除常见追踪参数
        if parsed.query:
            params = parsed.query.split('&')
            tracking_prefixes = ('utm_', 'fbclid', 'gclid', 'ref=', 'source=')
            clean_params = [p for p in params if not any(p.lower().startswith(t) for t in tracking_prefixes)]
            if clean_params:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{'&'.join(clean_params)}"
            else:
                return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return url
    except:
        return url


# ============== 结束 URL 验证函数 ==============


# Wrap tools as function_tool for Agent
@function_tool
async def enhanced_research_tool(ctx: RunContextWrapper[Any], query: str) -> str:
    """
    Enhanced research combining fast Serper search with intelligent Jina deep reading.

    CRITICAL - STRUCTURED OUTPUT:
    This tool returns JSON with REAL URLs from search results.
    DO NOT modify, reconstruct, or guess URLs - use them EXACTLY as provided.

    CAPABILITIES:
    - Fast web search for broad information coverage
    - Intelligent scenario detection (synthesis routes, pipeline evaluation, clinical research)
    - Selective deep reading of high-value sources (academic papers, patents, regulatory docs)
    - Scenario-driven information extraction

    OUTPUT FORMAT:
    Returns JSON with:
    {
        "findings": ["finding 1", "finding 2", ...],
        "sources": [
            {"title": "...", "url": "REAL_URL_FROM_SEARCH", "snippet": "..."},
            ...
        ],
        "confidence": 0.8
    }

    IMPORTANT:
    - URLs in sources are REAL URLs from search results - use them DIRECTLY
    - DO NOT modify, shorten, or reconstruct these URLs
    - Copy the entire sources array to your output JSON
    - Return your analysis immediately after this single enhanced search
    """
    import time
    import json
    tool_start = time.time()
    print(f"[DEBUG] Enhanced research tool called with query: {query[:50]}...")

    try:
        from ..tools.enhanced_research import EnhancedResearchTool
        tool = EnhancedResearchTool()
        result = await tool.smart_research(query, MAX_SEARCH_RESULTS)

        # 返回结构化 JSON，包含真实的 sources
        structured_output = {
            "findings": result.get("findings", []),
            "sources": [
                {
                    "title": src.title,
                    "url": src.url,
                    "snippet": src.snippet[:300] if src.snippet else "",
                    "source_type": getattr(src, "source_type", "search_result")
                }
                for src in result.get("sources", [])
            ],
            "confidence": result.get("confidence", 0.5),
            "scenario": result.get("research_plan", {}).get("strategy", "unknown")
        }

        # 返回 JSON 字符串
        json_output = json.dumps(structured_output, ensure_ascii=False, indent=2)

        tool_end = time.time()
        print(f"[DEBUG] Enhanced research completed: {tool_end - tool_start:.2f}s, {len(structured_output['sources'])} sources")

        return json_output

    except Exception as e:
        print(f"[ERROR] Enhanced research failed, falling back to basic search: {e}")
        import traceback
        traceback.print_exc()

        # Fallback: 返回基本结构
        try:
            from ..tools.serperapi import web_search
            result = await web_search(query, MAX_SEARCH_RESULTS)

            # 尝试从文本中提取基本信息
            fallback_output = {
                "findings": ["搜索完成（降级模式）"],
                "sources": [],
                "confidence": 0.3,
                "scenario": "fallback"
            }

            tool_end = time.time()
            print(f"[DEBUG] Fallback search completed: {tool_end - tool_start:.2f}s")

            return json.dumps(fallback_output, ensure_ascii=False, indent=2)
        except:
            return json.dumps({"findings": [], "sources": [], "confidence": 0.0}, ensure_ascii=False)

@function_tool
async def web_search_tool(ctx: RunContextWrapper[Any], query: str) -> str:
    """
    Basic web search tool (kept for compatibility/fallback).
    """
    import time
    tool_start = time.time()
    print(f"[DEBUG] Basic web search tool called: {query[:50]}...")
    
    from ..tools.serperapi import web_search
    result = await web_search(query, MAX_SEARCH_RESULTS)
    truncated = truncate_tool_output(result)
    
    tool_end = time.time()
    print(f"[DEBUG] Basic search completed: {tool_end - tool_start:.2f}s")
    
    return truncated


# 增强单次研究的指令
SUBAGENT_INSTRUCTIONS = """\
You are an ENHANCED SINGLE-RESEARCH agent with intelligent research capabilities.

## AVAILABLE TOOLS
- enhanced_research_tool: Returns STRUCTURED JSON with real URLs from search results
- web_search_tool: Basic search (fallback only)

## CRITICAL CONSTRAINTS
- YOU CAN ONLY CALL enhanced_research_tool EXACTLY ONCE
- NO second searches, NO follow-up calls, NO exceptions
- The tool returns JSON with REAL URLs - use them DIRECTLY

## TASK
Research: {focus}
Use ONE of these queries: {queries}

## WORKFLOW
1. Pick the BEST query from the list
2. Call enhanced_research_tool ONCE
3. Parse the returned JSON (it contains findings, sources with REAL URLs, confidence)
4. Use the sources DIRECTLY from the tool output
5. Return complete JSON immediately

## TOOL OUTPUT FORMAT
The enhanced_research_tool returns JSON:
{{
    "findings": ["finding 1", "finding 2", ...],
    "sources": [
        {{"title": "...", "url": "REAL_URL", "snippet": "...", "source_type": "..."}},
        ...
    ],
    "confidence": 0.8,
    "scenario": "..."
}}

## CRITICAL: SOURCE HANDLING
- The tool already provides REAL URLs from SerpAPI - DO NOT modify them
- COPY the sources array DIRECTLY from the tool output to your output
- DO NOT reconstruct, modify, or guess URLs
- DO NOT create new URLs not in the tool output
- The sources in tool output are already validated and cleaned

## OUTPUT (JSON only)
{{
    "focus": "{focus}",
    "key_findings": ["Combine tool findings with your analysis", "Extract key insights", "Add context"],
    "sources": [COPY_DIRECTLY_FROM_TOOL_OUTPUT],
    "confidence": USE_TOOL_CONFIDENCE_OR_ADJUST
}}

## EXTRACTION RULES

**CRITICAL: Adapt extraction based on research focus**

If focus contains keywords like "挑战/challenge", "难点/difficulty", "瓶颈/bottleneck", "限制/limitation", "风险/risk":
→ This is a TECHNICAL CHALLENGES analysis. You MUST extract:
  - Specific technical obstacles and barriers
  - Unsolved problems and open questions
  - Failed approaches and why they didn't work
  - Limitations of current methods
  - Risks and potential issues
  - Expert opinions on difficulties
  - DO NOT only list positive facts - focus on NEGATIVE/CHALLENGING aspects

If focus contains keywords like "mechanism", "pathway", "target", "作用机制":
→ This is a SCIENTIFIC MECHANISM analysis. Extract:
  - Molecular mechanisms and pathways
  - Structure-activity relationships
  - Biological targets and interactions
  - Scientific evidence and data

If focus contains keywords like "pipeline", "clinical", "企业/company", "竞争/competitive":
→ This is a COMMERCIAL/CLINICAL analysis. Extract:
  - Development stages and timelines
  - Company strategies and positioning
  - Clinical trial results and progress
  - Market opportunities and threats

**General rules** (apply to all):
- Each finding = one complete, specific, actionable insight
- Include quantitative data when available (numbers, percentages, dates)
- Cite specific sources for key claims
- Use tool's confidence as baseline, adjust based on finding quality

EXAMPLE:
Tool returns:
{{
    "findings": ["Found synthesis route"],
    "sources": [{{"title": "Paper A", "url": "https://real-url.com/123", "snippet": "..."}}],
    "confidence": 0.8
}}

Your output:
{{
    "focus": "Synthesis routes",
    "key_findings": ["Found synthesis route with 85% yield", "Uses Pd catalyst", "Requires 3 steps"],
    "sources": [{{"title": "Paper A", "url": "https://real-url.com/123", "snippet": "..."}}],
    "confidence": 0.8
}}

REMEMBER: The tool provides REAL URLs - use them EXACTLY as given. No modifications needed!
"""


class Subagent:
    """
    Subagent for executing focused research tasks.

    Inspired by GPT-Researcher's worker agents.
    """

    def __init__(self, agent_id: int, model: AnthropicModel):
        self.agent_id = agent_id
        self.model = model
        self.base_agent = None
    
    def _create_agent(self, focus: str, queries: List[str]) -> Agent:
        """Create agent with task-specific instructions using fast model."""
        # #region agent log
        import json as json_mod
        try:
            with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
                f.write(json_mod.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'H1', 'location': 'subagent.py:_create_agent', 'message': 'Before format', 'data': {'focus': focus, 'queries': queries}, 'timestamp': __import__('time').time() * 1000}) + '\n')
        except: pass
        # #endregion
        
        try:
            instructions = SUBAGENT_INSTRUCTIONS.format(
                focus=focus,
                queries=', '.join(queries)
            )
        except KeyError as e:
            print(f"[ERROR] SUBAGENT_INSTRUCTIONS format failed: {e}")
            raise
            
        # Use fast model for tool calling efficiency
        from ..agent import build_model
        fast_model = build_model("fast")
        print(f"[DEBUG] Subagent-{self.agent_id} using fast model for tool calls")
        
        from ..config import ANTHROPIC_API_KEY
        litellm_model = LitellmModel(
            model=f"anthropic/{fast_model.model}",
            api_key=ANTHROPIC_API_KEY
        )
        
        return Agent(
            name=f"Subagent-{self.agent_id}",
            model=litellm_model,
            instructions=instructions,
            tools=[enhanced_research_tool, web_search_tool]
        )
    
    def _extract_json(self, s: str) -> dict:
        """Extract JSON from agent output."""
        s = (s or "").strip()
        if s.startswith("{") and s.endswith("}"):
            return json.loads(s)
        a, b = s.find("{"), s.rfind("}")
        if a != -1 and b != -1 and b > a:
            return json.loads(s[a:b+1])
        raise ValueError(f"Subagent did not return JSON: {s[:200]}")
    
    async def search(self, subtask: Subtask) -> SubtaskResult:
        """Execute search for a subtask."""
        import time
        start_time = time.time()
        
        # Create agent with specific instructions
        agent_start = time.time()
        agent = self._create_agent(subtask.focus, subtask.queries)
        agent_end = time.time()
        print(f"[DEBUG] Subagent-{self.agent_id} Agent creation: {agent_end - agent_start:.2f}s")
        
        # Simple input prompt
        input_prompt = f"Research: {subtask.focus}\nSuggested queries: {', '.join(subtask.queries)}"
        
        try:
            # Run the agent
            runner_start = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} Starting Runner.run for: {subtask.focus[:50]}...")
            
            result = await Runner.run(agent, input_prompt)
            
            runner_end = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} Runner.run completed: {runner_end - runner_start:.2f}s")
            
            output = result.final_output or ""
            
            # Parse the result
            parse_start = time.time()
            data = self._extract_json(output)
            parse_end = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} JSON parsing: {parse_end - parse_start:.2f}s")
            
            # ============== 关键修改：验证并过滤 sources ==============
            process_start = time.time()
            sources = []
            invalid_url_count = 0
            
            for src in data.get("sources", [])[:8]:  # 检查更多，因为有些会被过滤
                url = src.get("url", "")

                # 验证 URL
                if not is_valid_source_url(url):
                    invalid_url_count += 1
                    print(f"[WARN] Subagent-{self.agent_id} filtering invalid URL: {url[:100] if url else 'empty'}")
                    continue

                # 清理 URL
                clean_url_str = clean_url(url)

                snippet = src.get("snippet", "")
                if len(snippet) > 200:
                    snippet = snippet[:200] + "..."

                sources.append(Source(
                    title=src.get("title", "")[:100] or "Unknown",
                    url=clean_url_str,
                    snippet=snippet,
                    source_type=src.get("source_type")
                ))

                # 最多保留 5 个有效 source（增加以保留更多高质量来源）
                if len(sources) >= 5:
                    break
            
            if invalid_url_count > 0:
                print(f"[INFO] Subagent-{self.agent_id} filtered {invalid_url_count} invalid URLs, kept {len(sources)} valid")
            # ============== 结束关键修改 ==============
            
            # 限制 findings 数量和长度
            findings = []
            for f in data.get("key_findings", [])[:5]:
                if len(f) > 300:
                    f = f[:300] + "..."
                findings.append(f)
            
            process_end = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} Data processing: {process_end - process_start:.2f}s")
            
            total_time = time.time() - start_time
            print(f"[DEBUG] Subagent-{self.agent_id} TOTAL TIME: {total_time:.2f}s")
            
            return SubtaskResult(
                subtask_id=subtask.id,
                focus=subtask.focus,
                findings=findings,
                sources=sources,
                confidence=data.get("confidence", 0.5)
            )
            
        except Exception as e:
            total_time = time.time() - start_time
            print(f"[ERROR] Subagent-{self.agent_id} Failed after {total_time:.2f}s: {e}")
            return SubtaskResult(
                subtask_id=subtask.id,
                focus=subtask.focus,
                findings=[f"研究失败: {str(e)[:100]}"],
                sources=[],
                confidence=0.0
            )