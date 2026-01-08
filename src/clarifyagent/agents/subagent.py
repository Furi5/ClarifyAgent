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
async def enhanced_research_tool(ctx: RunContextWrapper[Any], query: str) -> str:
    """
    Enhanced research combining fast Serper search with intelligent Jina deep reading.
    
    CAPABILITIES:
    - Fast web search for broad information coverage
    - Intelligent scenario detection (synthesis routes, pipeline evaluation, clinical research)
    - Selective deep reading of high-value sources (academic papers, patents, regulatory docs)
    - Scenario-driven information extraction
    
    IMPORTANT: 
    - Returns comprehensive analysis with both broad and deep insights
    - Automatically selects best research strategy based on query type
    - Provides source reliability indicators and confidence scores
    - Return your analysis immediately after this single enhanced search
    """
    import time
    tool_start = time.time()
    print(f"[DEBUG] Enhanced research tool called with query: {query[:50]}...")
    
    try:
        from ..tools.enhanced_research import enhanced_web_search_with_jina
        result = await enhanced_web_search_with_jina(query, MAX_SEARCH_RESULTS)
        truncated = truncate_tool_output(result)
        
        tool_end = time.time()
        print(f"[DEBUG] Enhanced research completed: {tool_end - tool_start:.2f}s, output length: {len(truncated)}")
        
        return truncated
    except Exception as e:
        print(f"[ERROR] Enhanced research failed, falling back to basic search: {e}")
        # Fallback to basic search
        from ..tools.serperapi import web_search
        result = await web_search(query, MAX_SEARCH_RESULTS)
        truncated = truncate_tool_output(result)
        
        tool_end = time.time()
        print(f"[DEBUG] Fallback search completed: {tool_end - tool_start:.2f}s")
        
        return truncated

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


# read_url_tool 已移除 - 只使用搜索工具以提升性能


# 增强单次研究的指令
SUBAGENT_INSTRUCTIONS = """\
You are an ENHANCED SINGLE-RESEARCH agent with intelligent research capabilities.

## AVAILABLE TOOLS
- enhanced_research_tool: Intelligent research combining fast search + selective deep reading
- web_search_tool: Basic search (fallback only)

## CRITICAL CONSTRAINTS
- YOU CAN ONLY CALL enhanced_research_tool EXACTLY ONCE
- NO second searches, NO follow-up calls, NO exceptions
- The enhanced tool will automatically detect your research scenario and use optimal strategy

## TASK
Research: {focus}
Use ONE of these queries: {queries}

## WORKFLOW
1. Pick the BEST query from the list
2. Call enhanced_research_tool ONCE (it will auto-select Serper + selective Jina reading)
3. Extract facts from the comprehensive results
4. Return complete JSON immediately

## ENHANCED RESEARCH CAPABILITIES
The enhanced tool will:
- Detect research scenario (synthesis routes, pipeline evaluation, clinical research, etc.)
- Perform fast broad search for context
- Intelligently select 2-3 high-value sources for deep reading
- Extract scenario-specific insights
- Provide confidence scores

## OUTPUT (JSON only)
{{
    "focus": "{focus}",
    "key_findings": ["detailed fact 1", "technical detail 2", "strategic insight 3"],
    "sources": [{{"title": "title", "url": "url", "snippet": "detailed quote"}}],
    "confidence": 0.8
}}

## EXTRACTION RULES
- Prioritize detailed, technical information from deep-read sources
- Include both broad context and specific details
- Each finding = one complete, actionable insight
- Sources should include both search results and enhanced content
- Higher confidence for scenarios with deep technical content

REMEMBER: ONE enhanced research call gives you both breadth AND depth.
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
        """Create agent with task-specific instructions using fast model."""
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
            
        # Use fast model for tool calling efficiency
        from ..agent import build_model
        fast_model = build_model("fast")
        print(f"[DEBUG] Subagent-{self.agent_id} using fast model for tool calls")
        
        return Agent(
            name=f"Subagent-{self.agent_id}",
            model=fast_model,  # 使用快速模型
            instructions=instructions,
            tools=[enhanced_research_tool, web_search_tool]  # 增强研究工具 + 基础搜索作为fallback
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
            # Run the agent with detailed logging
            runner_start = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} Starting Runner.run for: {subtask.focus[:50]}...")
            print(f"[DEBUG] Subagent-{self.agent_id} Agent model: {agent.model.model}")
            print(f"[DEBUG] Subagent-{self.agent_id} Input prompt length: {len(input_prompt)}")
            
            # Monitor Runner.run with progress tracking
            result = await Runner.run(agent, input_prompt)
            
            runner_end = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} Runner.run completed: {runner_end - runner_start:.2f}s")
            
            # Check if result contains run steps for detailed analysis
            if hasattr(result, 'run_result') and hasattr(result.run_result, 'run_steps'):
                steps = result.run_result.run_steps
                print(f"[DEBUG] Subagent-{self.agent_id} Total steps: {len(steps)}")
                for i, step in enumerate(steps):
                    if hasattr(step, 'step_type'):
                        print(f"[DEBUG] Subagent-{self.agent_id} Step {i}: {step.step_type}")
            
            output_length = len(result.final_output or "")
            print(f"[DEBUG] Subagent-{self.agent_id} Output length: {output_length} chars")
            
            output = result.final_output or ""
            
            # Parse the result
            parse_start = time.time()
            data = self._extract_json(output)
            parse_end = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} JSON parsing: {parse_end - parse_start:.2f}s")
            
            # Convert sources to Source objects
            process_start = time.time()
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
            # Fallback if anything fails
            total_time = time.time() - start_time
            print(f"[ERROR] Subagent-{self.agent_id} Failed after {total_time:.2f}s: {e}")
            return SubtaskResult(
                subtask_id=subtask.id,
                focus=subtask.focus,
                findings=[f"研究失败: {str(e)[:100]}"],
                sources=[],
                confidence=0.0
            )
