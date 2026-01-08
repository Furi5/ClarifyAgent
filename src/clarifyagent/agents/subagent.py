"""
Subagent implementation for parallel task execution.

Inspired by GPT-Researcher's approach:
1. Search first, read URL only when necessary
2. Extract key facts from snippets
3. Smart content summarization
"""
import json
from typing import Any, List
from agents import Agent, Runner, RunContextWrapper, function_tool
from agents.extensions.models.litellm_model import LitellmModel

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


# Wrap tools as function_tool for Agent
@function_tool
async def web_search_tool(ctx: RunContextWrapper[Any], query: str) -> str:
    """
    Search the web. Returns top 3 results with snippets.
    
    TIPS:
    - Snippets usually contain the key info you need
    - Only use read_url if snippet is unclear
    """
    from ..tools.serperapi import web_search
    result = await web_search(query, MAX_SEARCH_RESULTS)
    return truncate_tool_output(result)


@function_tool
async def read_url_tool(ctx: RunContextWrapper[Any], url: str) -> str:
    """
    Read a URL. Use ONLY if search snippets are insufficient.
    
    Returns cleaned, summarized content (not full page).
    """
    from ..tools.scraper import smart_scrape
    result = await smart_scrape(url, max_chars=MAX_TOOL_OUTPUT)
    if result["success"]:
        return f"**{result['title']}**\n\n{result['content']}"
    else:
        return f"Failed to read URL: {result['error']}"


# 更精简的指令
SUBAGENT_INSTRUCTIONS = """\
You are a focused research agent. Your goal: answer ONE specific question efficiently.

## STRICT RULES
1. MAX 1-2 tool calls total
2. Prefer search snippets over reading URLs
3. Only read URL if snippet lacks critical info

## YOUR TASK
Research: {focus}
Queries to try: {queries}

## OUTPUT (JSON only)
{{
    "focus": "the question you researched",
    "key_findings": ["fact 1", "fact 2", "fact 3"],
    "sources": [{{"title": "...", "url": "...", "snippet": "key quote"}}],
    "confidence": 0.8
}}

## EFFICIENCY
- Search snippets often have the answer - check them first!
- One precise query > multiple vague queries
- Stop once you have enough facts (3-5 findings is enough)
"""


class Subagent:
    """
    Subagent for executing focused research tasks.
    
    Inspired by GPT-Researcher's worker agents.
    """
    
    def __init__(self, agent_id: int, model: LitellmModel):
        self.agent_id = agent_id
        self.model = model
        # Agent will be created dynamically with task-specific instructions
        self.base_agent = None
    
    def _create_agent(self, focus: str, queries: List[str]) -> Agent:
        """Create agent with task-specific instructions."""
        # #region agent log
        import json as json_mod
        with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
            f.write(json_mod.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'H1', 'location': 'subagent.py:103', 'message': 'Before format - checking SUBAGENT_INSTRUCTIONS', 'data': {'focus': focus, 'queries': queries, 'has_unescaped_braces': '{' in SUBAGENT_INSTRUCTIONS and '{{' not in SUBAGENT_INSTRUCTIONS}, 'timestamp': __import__('time').time() * 1000}) + '\n')
        # #endregion
        try:
            instructions = SUBAGENT_INSTRUCTIONS.format(
                focus=focus,
                queries=', '.join(queries)
            )
            # #region agent log
            with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
                f.write(json_mod.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'H1', 'location': 'subagent.py:110', 'message': 'Format succeeded', 'data': {'instructions_length': len(instructions)}, 'timestamp': __import__('time').time() * 1000}) + '\n')
            # #endregion
        except KeyError as e:
            # #region agent log
            with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
                f.write(json_mod.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'H1', 'location': 'subagent.py:115', 'message': 'Format failed with KeyError', 'data': {'error': str(e), 'error_key': e.args[0] if e.args else None}, 'timestamp': __import__('time').time() * 1000}) + '\n')
            # #endregion
            raise
        return Agent(
            name=f"Subagent-{self.agent_id}",
            model=self.model,
            instructions=instructions,
            tools=[web_search_tool, read_url_tool]
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
        # Create agent with specific instructions
        agent = self._create_agent(subtask.focus, subtask.queries)
        
        # Simple input prompt
        input_prompt = f"Research: {subtask.focus}\nSuggested queries: {', '.join(subtask.queries)}"
        
        try:
            # Run the agent
            result = await Runner.run(agent, input_prompt)
            output = result.final_output or ""
            
            # Parse the result
            data = self._extract_json(output)
            
            # Convert sources to Source objects
            sources = []
            for src in data.get("sources", [])[:3]:  # 最多3个source
                snippet = src.get("snippet", "")
                if len(snippet) > 200:
                    snippet = snippet[:200] + "..."
                sources.append(Source(
                    title=src.get("title", "")[:100],
                    url=src.get("url", ""),
                    snippet=snippet,
                    source_type=src.get("source_type")
                ))
            
            # 限制 findings 数量和长度
            findings = []
            for f in data.get("key_findings", [])[:5]:
                if len(f) > 300:
                    f = f[:300] + "..."
                findings.append(f)
            
            return SubtaskResult(
                subtask_id=subtask.id,
                focus=subtask.focus,
                findings=findings,
                sources=sources,
                confidence=data.get("confidence", 0.5)
            )
        except Exception as e:
            # Fallback if anything fails
            print(f"[Subagent-{self.agent_id}] Error: {e}")
            return SubtaskResult(
                subtask_id=subtask.id,
                focus=subtask.focus,
                findings=[f"研究失败: {str(e)[:100]}"],
                sources=[],
                confidence=0.0
            )
