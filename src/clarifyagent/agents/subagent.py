"""
Subagent implementation for parallel task execution.

Inspired by GPT-Researcher's approach:
1. Search first, read URL only when necessary
2. Extract key facts from snippets
3. Smart content summarization
"""
import asyncio
import json
import re
import time
from typing import Any, List
from urllib.parse import urlparse
from agents import Agent, Runner, RunContextWrapper, function_tool
from agents.extensions.models.litellm_model import LitellmModel
from typing import Union
from ..anthropic_model import AnthropicModel
from ..deepseek_model import DeepseekModel

from ..schema import Subtask, SubtaskResult, Source
from ..config import MAX_CONTENT_CHARS, MAX_SEARCH_RESULTS

# 尝试导入 async_timeout，如果不可用则使用 asyncio.wait_for
try:
    import async_timeout
except ImportError:
    # 如果没有 async_timeout，使用 asyncio.wait_for 作为替代
    async_timeout = None


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
async def enhanced_research_tool(ctx: RunContextWrapper[Any], query: str, max_results: int = None) -> str:
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

    PARAMETERS:
    - query: Research query (required)
    - max_results: Number of search results to retrieve (optional, default: 10)
      **YOU MUST SPECIFY THIS PARAMETER** based on task complexity:
        - Simple fact lookup (e.g., "What is X?", "When was Y approved?"): Use max_results=6
        - Standard research (e.g., "Overview of X"): Use max_results=12
        - Comprehensive analysis (e.g., "Compare multiple X"): Use max_results=18
        - Deep investigation (e.g., "Complete pipeline analysis"): Use max_results=22
      
      **CRITICAL**: Always provide max_results parameter. Do NOT omit it. Choose the value based on how complex your research task is.

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
    - Analyze the results and decide if you need more searches based on information sufficiency
    """
    import time
    import json
    tool_start = time.time()
    
    # Use LLM-specified max_results or default
    actual_max_results = max_results if max_results is not None else MAX_SEARCH_RESULTS
    
    # #region agent log
    try:
        with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
            f.write(json.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'LLM_SEARCH', 'location': 'subagent.py:enhanced_research_tool', 'message': 'LLM called enhanced_research_tool', 'data': {'query': query[:100], 'max_results_param': max_results, 'actual_max_results': actual_max_results, 'llm_specified': max_results is not None}, 'timestamp': time.time() * 1000}) + '\n')
    except: pass
    # #endregion
    
    print(f"[DEBUG] Enhanced research tool called with query: {query[:50]}..., max_results: {actual_max_results} (LLM specified: {max_results is not None})")

    try:
        print(f"[DEBUG] enhanced_research_tool: Starting smart_research for query: {query[:50]}...")
        from ..tools.enhanced_research import EnhancedResearchTool
        tool = EnhancedResearchTool()
        
        # 必做 1：给 tool call 单独加 wall-time timeout (20秒)
        # tool 永远不允许比 LLM 更慢
        try:
            if async_timeout is not None:
                async with async_timeout.timeout(20):
                    result = await tool.smart_research(query, actual_max_results)
            else:
                # 如果没有 async_timeout，使用 asyncio.wait_for
                result = await asyncio.wait_for(
                    tool.smart_research(query, actual_max_results),
                    timeout=20.0
                )
        except (asyncio.TimeoutError, TimeoutError):
            tool_elapsed = time.time() - tool_start
            print(f"[ERROR] enhanced_research_tool TIMEOUT after {tool_elapsed:.2f}s (limit: 20s)")
            # 返回一个基本结果，而不是完全失败
            return json.dumps({
                "findings": [f"搜索超时（{tool_elapsed:.1f}s），可能因网络延迟或 API 响应慢"],
                "sources": [],
                "confidence": 0.3,
                "should_stop": True,
                "action_hint": "STOP_AND_RETURN_RESULTS",
                "error": "tool_timeout"
            }, ensure_ascii=False)
        
        tool_elapsed = time.time() - tool_start
        print(f"[DEBUG] enhanced_research_tool: smart_research completed in {tool_elapsed:.2f}s, got {len(result.get('sources', []))} sources")

        # 计算是否应该停止搜索
        confidence = result.get("confidence", 0.5)
        should_stop = confidence >= 0.7

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
            "confidence": confidence,  # 最终置信度（向后兼容）
            "rule_confidence": result.get("rule_confidence"),  # 规则计算的置信度
            "llm_confidence": result.get("llm_confidence"),  # LLM 评估的置信度（如果启用）
            "confidence_details": result.get("confidence_details", {}),  # 详细信息
            "scenario": result.get("research_plan", {}).get("strategy", "unknown"),
            "search_metadata": result.get("search_metadata", {}),
            "performance": result.get("performance", {}),
            # 明确告诉 LLM 是否应该停止
            "should_stop": should_stop,
            "action_hint": "STOP_AND_RETURN_RESULTS" if should_stop else "CONTINUE_SEARCH_IF_NEEDED"
        }

        # 返回 JSON 字符串，并在前面加上明确的指示
        json_output = json.dumps(structured_output, ensure_ascii=False, indent=2)

        # 添加明确的行动指示，让 LLM 不要忽略
        if should_stop:
            json_output = f"⚠️ CONFIDENCE >= 0.7 - STOP SEARCHING NOW AND RETURN RESULTS ⚠️\n\n{json_output}\n\n⚠️ DO NOT SEARCH AGAIN. Extract findings and return final JSON output immediately. ⚠️"

        tool_end = time.time()
        confidence = structured_output.get('confidence', 0)
        rule_conf = structured_output.get('rule_confidence')
        llm_conf = structured_output.get('llm_confidence')
        rule_conf_str = f"{rule_conf:.2f}" if rule_conf is not None else "N/A"
        llm_conf_str = f"{llm_conf:.2f}" if llm_conf is not None else "N/A"
        print(f"[DEBUG] Enhanced research completed: {tool_end - tool_start:.2f}s, {len(structured_output['sources'])} sources, confidence={confidence:.2f} (rule={rule_conf_str}, llm={llm_conf_str})")
        
        # #region agent log
        try:
            with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
                f.write(json.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'LLM_SEARCH', 'location': 'subagent.py:enhanced_research_tool', 'message': 'Enhanced research completed', 'data': {'query': query[:100], 'num_sources': len(structured_output['sources']), 'confidence': structured_output.get('confidence', 0), 'num_findings': len(structured_output.get('findings', [])), 'search_metadata': structured_output.get('search_metadata', {})}, 'timestamp': time.time() * 1000}) + '\n')
        except: pass
        # #endregion

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
You are a SINGLE-RESEARCH agent. Your job is to search for information and return results.

## ⚠️ CRITICAL STOP CONDITIONS - YOU MUST OBEY ⚠️

**MANDATORY STOP**: You MUST stop searching and return results immediately when ANY of these conditions is met:
1. Tool output contains `"should_stop": true`
2. Tool output shows `confidence >= 0.7`
3. You have made **3 search calls** (HARD LIMIT - no exceptions)

**VIOLATION WARNING**: If you continue searching after these conditions are met, you are FAILING your task.

## TASK
Research: {focus}
Suggested queries: {queries}

## SIMPLE WORKFLOW

### Step 1: Search
Call enhanced_research_tool with:
- query: Pick the best query from suggestions
- max_results: 10-15 for most tasks

### Step 2: Check Stop Condition
Look at the tool output:
- If `should_stop: true` OR `confidence >= 0.7` → **STOP and go to Step 3**
- If `confidence < 0.5` AND search count < 3 → Try ONE more search with different query
- If search count >= 3 → **STOP and go to Step 3** (even if confidence is low)

### Step 3: Return Results
Output JSON with your findings:
```json
{{
    "focus": "{focus}",
    "key_findings": ["finding 1", "finding 2", ...],
    "sources": [copy sources from tool output],
    "confidence": [use tool confidence]
}}
```

## TOOL OUTPUT FORMAT
The tool returns:
```json
{{
    "findings": [...],
    "sources": [...],
    "confidence": 0.8,
    "should_stop": true,  // ← OBEY THIS FLAG
    "action_hint": "STOP_AND_RETURN_RESULTS"  // ← OBEY THIS HINT
}}
```

## RULES
1. **NEVER search more than 3 times** - this is a hard limit
2. **ALWAYS obey `should_stop: true`** - stop immediately when you see this
3. **Copy sources directly** - do not modify URLs
4. **Return JSON only** - no explanations needed

## EXTRACTION GUIDELINES
- Extract specific facts with numbers/dates when available
- For "challenges/risks" topics: focus on problems and obstacles
- For "clinical/pipeline" topics: focus on trial results and progress
- For "mechanism" topics: focus on scientific pathways

REMEMBER: Quality over quantity. One good search is better than many redundant searches.
"""


class Subagent:
    """
    Subagent for executing focused research tasks.

    Inspired by GPT-Researcher's worker agents.
    """

    def __init__(self, agent_id: int, model: Union[AnthropicModel, DeepseekModel]):
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
        from ..config import get_litellm_model_config
        fast_model = build_model("fast")
        print(f"[DEBUG] Subagent-{self.agent_id} using fast model for tool calls")
        
        model_str, api_key = get_litellm_model_config(fast_model.model)
        # 注意：LitellmModel 可能不支持 timeout 参数，超时由 asyncio.wait_for 控制
        # 如果 LiteLLM 内部有阻塞操作，可能需要额外的超时机制
        litellm_model = LitellmModel(
            model=model_str,
            api_key=api_key
            # timeout 参数可能不被支持，使用 asyncio.wait_for 作为外层超时保护
        )
        print(f"[DEBUG] Subagent-{self.agent_id} Created LitellmModel: {model_str}")
        
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
        import json
        import asyncio
        
        # 建议 4：给每个 task 打 wall-clock
        t0 = time.monotonic()
        start_time = time.time()
        print(f"[DEBUG] Subagent-{self.agent_id} Task started: {subtask.focus[:50]}... (wall-clock: {t0:.3f})")
        
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
            
            # #region agent log
            try:
                with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'AGENT_EXEC', 'location': 'subagent.py:search', 'message': 'Starting agent execution', 'data': {'subtask_focus': subtask.focus, 'subtask_queries': subtask.queries, 'input_prompt': input_prompt[:200]}, 'timestamp': time.time() * 1000}) + '\n')
            except: pass
            # #endregion
            
            # 添加超时检查日志
            import asyncio
            check_task = None
            async def log_progress():
                check_count = 0
                while True:
                    await asyncio.sleep(30.0)  # 每30秒检查一次
                    check_count += 1
                    elapsed = time.time() - runner_start
                    print(f"[DEBUG] Subagent-{self.agent_id} Runner.run still running after {elapsed:.1f}s (check #{check_count})...")
            
            check_task = asyncio.create_task(log_progress())
            
            try:
                # 添加超时保护 + 限制工具调用次数
                from ..config import AGENT_EXECUTION_TIMEOUT, MAX_AGENT_TURNS
                from agents.exceptions import MaxTurnsExceeded

                # max_turns: 限制 LLM 循环次数（可通过环境变量 MAX_AGENT_TURNS 配置）
                # 默认2：Turn1=搜索 → Turn2=生成输出（快速模式）
                # 设为3-4：允许多次搜索（更全面但更慢）

                print(f"[DEBUG] Subagent-{self.agent_id} Starting Runner.run with timeout={AGENT_EXECUTION_TIMEOUT}s, max_turns={MAX_AGENT_TURNS}")
                
                # 必做 2：Runner.run 改为"软退出" - 如果超过设定时间就强制提前停止
                # 不要等 timeout=180s
                # 从环境变量读取，默认 90 秒（比硬超时 180s 短，但给足够时间完成正常任务）
                from ..config import SOFT_EXIT_TIMEOUT
                
                async def run_with_soft_exit():
                    """Runner.run with soft exit after SOFT_EXIT_TIMEOUT"""
                    runner_task = asyncio.create_task(
                        Runner.run(agent, input_prompt, max_turns=MAX_AGENT_TURNS)
                    )
                    
                    # 等待软退出时间或完成
                    try:
                        done, pending = await asyncio.wait(
                            [runner_task],
                            timeout=SOFT_EXIT_TIMEOUT,
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        
                        if pending:
                            # 超过设定时间，强制提前停止
                            elapsed = time.time() - runner_start
                            print(f"[WARN] Subagent-{self.agent_id} Force early stop after {elapsed:.1f}s (soft exit limit: {SOFT_EXIT_TIMEOUT}s)")
                            runner_task.cancel()
                            try:
                                await runner_task
                            except asyncio.CancelledError:
                                pass
                            # 返回 None 表示提前退出
                            return None
                        else:
                            # 在设定时间内完成，返回结果
                            return runner_task.result()
                    except Exception as e:
                        elapsed = time.time() - runner_start
                        print(f"[ERROR] Subagent-{self.agent_id} run_with_soft_exit error after {elapsed:.1f}s: {e}")
                        runner_task.cancel()
                        raise
                
                # 使用 asyncio.wait_for 包装，确保硬超时也生效
                try:
                    result = await asyncio.wait_for(
                        run_with_soft_exit(),
                        timeout=AGENT_EXECUTION_TIMEOUT
                    )
                    
                    if result is None:
                        # 软退出，返回基本结果
                        check_task.cancel()
                        elapsed = time.time() - runner_start
                        total_time = time.time() - start_time
                        wall_elapsed = time.monotonic() - t0
                        print(f"[INFO] Subagent-{self.agent_id} Soft exit after {elapsed:.1f}s (total: {total_time:.2f}s, wall-clock: {wall_elapsed:.2f}s) - returning with available data")
                        return SubtaskResult(
                            subtask_id=subtask.id,
                            focus=subtask.focus,
                            findings=["研究因时间限制提前结束，已收集可用信息"],
                            sources=[],
                            confidence=0.5
                        )
                    
                    check_task.cancel()
                    elapsed = time.time() - runner_start
                    total_time = time.time() - start_time
                    wall_elapsed = time.monotonic() - t0
                    print(f"[DEBUG] Subagent-{self.agent_id} Runner.run completed successfully in {elapsed:.2f}s (total: {total_time:.2f}s, wall-clock: {wall_elapsed:.2f}s)")
                except asyncio.TimeoutError:
                    # 硬超时（180秒）
                    check_task.cancel()
                    elapsed = time.time() - runner_start
                    print(f"[ERROR] Subagent-{self.agent_id} Runner.run HARD TIMEOUT after {elapsed:.1f}s (limit: {AGENT_EXECUTION_TIMEOUT}s)")
                    raise
            except MaxTurnsExceeded as e:
                # 达到最大循环次数，这是正常的退出情况（不是错误）
                check_task.cancel()
                elapsed = time.time() - runner_start
                print(f"[INFO] Subagent-{self.agent_id} reached max_turns after {elapsed:.1f}s - returning with available data")

                # 当 max_turns 被超过时，返回一个基本结果
                total_time = time.time() - start_time
                wall_elapsed = time.monotonic() - t0
                print(f"[INFO] Subagent-{self.agent_id} Task finished in {total_time:.2f}s (wall-clock: {wall_elapsed:.2f}s) - max_turns reached")
                return SubtaskResult(
                    subtask_id=subtask.id,
                    focus=subtask.focus,
                    findings=["研究达到最大搜索次数限制，已收集可用信息"],
                    sources=[],
                    confidence=0.5
                )
            except asyncio.TimeoutError:
                check_task.cancel()
                elapsed = time.time() - runner_start
                total_time = time.time() - start_time
                wall_elapsed = time.monotonic() - t0
                print(f"[ERROR] Subagent-{self.agent_id} Runner.run TIMEOUT after {elapsed:.1f}s (total: {total_time:.2f}s, wall-clock: {wall_elapsed:.2f}s, limit: {AGENT_EXECUTION_TIMEOUT}s)")
                print(f"[ERROR] This indicates Runner.run did not complete within {AGENT_EXECUTION_TIMEOUT}s")
                print(f"[ERROR] Possible causes:")
                print(f"[ERROR]   1. LLM API call stuck (DeepSeek API not responding)")
                print(f"[ERROR]   2. Blocking operation in Runner.run")
                print(f"[ERROR]   3. Network issue or connection hang")
                print(f"[ERROR]   4. asyncio.wait_for may not be able to cancel Runner.run if it's in a blocking call")
                
                # 返回超时结果，而不是抛出异常（让系统继续运行）
                total_time = time.time() - start_time
                wall_elapsed = time.monotonic() - t0
                print(f"[ERROR] Subagent-{self.agent_id} Task timeout in {total_time:.2f}s (wall-clock: {wall_elapsed:.2f}s)")
                return SubtaskResult(
                    subtask_id=subtask.id,
                    focus=subtask.focus,
                    findings=[f"执行超时（{elapsed:.1f}s/{AGENT_EXECUTION_TIMEOUT}s），LLM API 调用可能卡住"],
                    sources=[],
                    confidence=0.3
                )
            except Exception as e:
                check_task.cancel()
                raise
            
            runner_end = time.time()
            print(f"[DEBUG] Subagent-{self.agent_id} Runner.run completed: {runner_end - runner_start:.2f}s")
            
            # #region agent log
            try:
                with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
                    f.write(json.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'AGENT_EXEC', 'location': 'subagent.py:search', 'message': 'Agent execution completed', 'data': {'subtask_focus': subtask.focus, 'has_final_output': bool(result.final_output), 'final_output_length': len(result.final_output) if result.final_output else 0, 'final_output_preview': (result.final_output or '')[:500]}, 'timestamp': time.time() * 1000}) + '\n')
            except: pass
            # #endregion
            
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
                    snippet = snippet[:500] + "..."

                sources.append(Source(
                    title=src.get("title", "")[:100] or "Unknown",
                    url=clean_url_str,
                    snippet=snippet,
                    source_type=src.get("source_type")
                ))

                # 最多保留 5 个有效 source（增加以保留更多高质量来源）
                if len(sources) >= 8:
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
            wall_elapsed = time.monotonic() - t0
            print(f"[DEBUG] Subagent-{self.agent_id} TOTAL TIME: {total_time:.2f}s (wall-clock: {wall_elapsed:.2f}s)")
            
            return SubtaskResult(
                subtask_id=subtask.id,
                focus=subtask.focus,
                findings=findings,
                sources=sources,
                confidence=data.get("confidence", 0.5)
            )
            
        except Exception as e:
            total_time = time.time() - start_time
            wall_elapsed = time.monotonic() - t0
            print(f"[ERROR] Subagent-{self.agent_id} Failed after {total_time:.2f}s (wall-clock: {wall_elapsed:.2f}s): {e}")
            return SubtaskResult(
                subtask_id=subtask.id,
                focus=subtask.focus,
                findings=[f"研究失败: {str(e)[:100]}"],
                sources=[],
                confidence=0.0
            )