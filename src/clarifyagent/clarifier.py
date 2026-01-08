"""Clarifier module for assessing information sufficiency and generating clarifications."""
import json
import re
import logging
from typing import Optional
from agents import Agent, Runner
from agents.extensions.models.litellm_model import LitellmModel

from .schema import Plan
from .tools.serperapi import web_search

logger = logging.getLogger(__name__)

# 轻量搜索配置
LIGHT_SEARCH_NUM_RESULTS = 3  # 轻量搜索返回结果数
SEARCH_CONFIDENCE_MIN = 0.3   # 低于此值不搜索（太模糊）
SEARCH_CONFIDENCE_MAX = 0.75  # 高于此值不搜索（已足够清晰）

# 专业术语模式（用于判断是否需要搜索验证）
# 注意：不使用 \b 因为它在中文环境中不工作
DOMAIN_TERM_PATTERNS = [
    r'[A-Z]{2,}[\-]?[A-Z0-9]*',        # 如 KRAS, GLP-1, STAT6
    r'[A-Z][a-z]+[A-Z][a-z]+',          # 如 PembrolizumAb (驼峰式)
    r'\w+mab|\w+nib|\w+ide',            # 抗体/小分子后缀
    r'PD-?[L]?1|CTLA-?4',              # 免疫检查点
    r'STAT\d|JAK\d',                    # 信号通路
    r'GLP-?\d',                         # GLP-1 等
]


CLARIFIER_SYSTEM_PROMPT = """\
You are a clarification module for a Deep Research platform focused on drug design and biomedical research.
You MUST output ONLY valid JSON (no markdown, no extra text).

Your role:
- Assess if user input has enough information to start research
- Generate clarification questions when information is insufficient
- Provide options rather than open-ended questions
- Infer research focus when possible
- **Use pre-search context (if provided) to generate more informed options**

## Using Pre-Search Context

When `search_context` is provided in the input:
1. Use it to verify domain terms and understand the research area
2. Generate clarification options based on real-world data from search results
3. Increase confidence if search results confirm the topic is valid and well-defined
4. Use search insights to suggest relevant research focus areas

Example: If user mentions "STAT6 inhibitor" and search shows it's related to immune diseases:
- Use this to provide specific indication options (asthma, atopic dermatitis, etc.)
- Don't ask generic questions like "what do you want to research?"

## Decision Logic

1. If confidence < 0.6:
   → NEED_CLARIFICATION (must clarify - topic unclear or missing)

2. If 0.6 <= confidence < 0.7 and missing key information:
   → NEED_CLARIFICATION (clarify missing info - research focus unclear)

3. If 0.7 <= confidence < 0.85:
   → CONFIRM_PLAN (show inferred plan, let user confirm)

4. If confidence >= 0.85:
   → START_RESEARCH (sufficient information, can start directly)

5. If unknown term detected:
   → VERIFY_TOPIC (search to verify before proceeding)

## Assessment Criteria

Evaluate these dimensions (each contributes to confidence):

1. **Research topic clarity** (0.0-0.3):
   - Clear subject? (e.g., "KRAS G12C", "GLP-1 agonist") → +0.3
   - Vague subject? (e.g., "that drug", "something") → +0.0
   - Missing subject? → +0.0

2. **Research scope inferability** (0.0-0.3):
   - Can infer 3+ research focus areas? → +0.3
   - Can infer 1-2 focus areas? → +0.15
   - Cannot infer focus? → +0.0

3. **Research goal clarity** (0.0-0.2):
   - Clear goal? (e.g., "latest progress", "mechanism", "clinical data") → +0.2
   - Implied goal? → +0.1
   - No goal? → +0.0

4. **Key term understanding** (0.0-0.2):
   - All terms understood? → +0.2
   - Some terms unclear? → +0.1
   - Unknown terms? → VERIFY_TOPIC

## Clarification Principles

1. **Only ask what affects research direction**
   - ❌ Don't ask: "What do you want to research?" (too broad)
   - ✅ Ask: "Which aspect of KRAS G12C? A) Target validation B) Approved drugs C) Clinical trials"

2. **Provide 3-5 options**
   - Options should be mutually exclusive
   - Last option: "Other (please specify)"
   - Based on domain knowledge

3. **One clarification at a time**
   - Focus on the most critical missing information
   - Don't overwhelm user

## Examples

### Example 1: Sufficient Information
Input: "KRAS G12C 靶点"
Assessment:
- Topic clarity: 0.3 (clear)
- Scope inferability: 0.3 (can infer: validation, drugs, trials, resistance)
- Goal clarity: 0.1 (implied: general research)
- Term understanding: 0.2 (all understood)
- Confidence: 0.9
→ START_RESEARCH

### Example 2: Need Clarification
Input: "帮我研究一下"
Assessment:
- Topic clarity: 0.0 (missing)
- Scope inferability: 0.0 (cannot infer)
- Goal clarity: 0.0 (no goal)
- Confidence: 0.0
→ NEED_CLARIFICATION
{
    "clarification": {
        "question": "请告诉我您想研究的具体主题是什么？",
        "options": [
            "特定靶点或基因（如 KRAS G12C）",
            "特定药物或化合物（如 GLP-1 激动剂）",
            "特定疾病或适应症（如 2型糖尿病）",
            "特定技术或方法（如 PROTAC 设计）",
            "其他（请说明）"
        ],
        "missing_info": "research_topic"
    }
}

### Example 3: Confirm Plan
Input: "GLP-1 激动剂"
Assessment:
- Topic clarity: 0.3 (clear)
- Scope inferability: 0.3 (can infer focus)
- Goal clarity: 0.1 (implied)
- Confidence: 0.75
→ CONFIRM_PLAN

## Output Format

{
    "next_action": "START_RESEARCH|NEED_CLARIFICATION|CONFIRM_PLAN|VERIFY_TOPIC",
    "task": {
        "goal": "Research goal (inferred or from user)",
        "research_focus": ["focus 1", "focus 2", ...]  # At least 3 for START_RESEARCH
    },
    "confidence": 0.0-1.0,
    "why": "Brief assessment reason",
    "clarification": {
        "question": "Clear question",
        "options": ["Option 1", "Option 2", ...],
        "missing_info": "research_topic|research_focus|research_goal"
    },  # Only if NEED_CLARIFICATION
    "assumptions": ["Assumption 1", ...],  # If any assumptions made
    "confirm_prompt": "Prompt for confirmation"  # If CONFIRM_PLAN
}
"""


def build_clarifier(model: LitellmModel) -> Agent:
    """Build the clarifier agent."""
    return Agent(
        name="Clarifier",
        model=model,
        instructions=CLARIFIER_SYSTEM_PROMPT,
        tools=[]  # Clarifier doesn't use tools
    )


def extract_domain_terms(text: str) -> list[str]:
    """
    从文本中提取专业术语（用于判断是否需要搜索验证）。
    
    Args:
        text: 用户输入文本
    
    Returns:
        提取的专业术语列表
    """
    terms = set()
    for pattern in DOMAIN_TERM_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        terms.update(m.strip() for m in matches if len(m.strip()) >= 2)
    
    # 过滤常见词
    common_words = {'AI', 'OK', 'API', 'US', 'UK', 'EU', 'IT', 'ID'}
    terms = [t for t in terms if t.upper() not in common_words]
    
    return list(terms)[:5]  # 最多返回5个


def build_search_query(user_input: str, terms: list[str]) -> str:
    """
    构建轻量搜索的查询语句。
    
    Args:
        user_input: 用户原始输入
        terms: 提取的专业术语
    
    Returns:
        搜索查询语句
    """
    if terms:
        # 使用专业术语构建查询
        main_term = terms[0]
        return f"{main_term} drug research indications mechanism"
    else:
        # 提取用户输入中的核心词
        # 去掉常见请求词
        cleaned = re.sub(r'(帮我|请|搜集|研究|分析|了解|查找|找)', '', user_input)
        cleaned = cleaned.strip()[:50]  # 限制长度
        if cleaned:
            return f"{cleaned} research overview"
    return ""


async def pre_clarification_search(
    user_input: str,
    terms: list[str],
    num_results: int = LIGHT_SEARCH_NUM_RESULTS
) -> Optional[dict]:
    """
    澄清前的轻量搜索，获取背景信息。
    
    Args:
        user_input: 用户输入
        terms: 专业术语列表
        num_results: 搜索结果数量
    
    Returns:
        搜索结果字典，包含 domain_context 和 verified_terms
    """
    query = build_search_query(user_input, terms)
    if not query:
        return None
    
    try:
        logger.info(f"🔍 轻量搜索: {query}")
        search_result = await web_search(query, num_results=num_results)
        
        return {
            "query": query,
            "domain_context": search_result,
            "verified_terms": terms,
            "has_results": bool(search_result and "未找到" not in search_result)
        }
    except Exception as e:
        logger.warning(f"轻量搜索失败: {e}")
        return None


def should_do_pre_search(user_input: str, task_draft: dict) -> bool:
    """
    判断是否需要进行澄清前搜索。
    
    Args:
        user_input: 用户输入
        task_draft: 当前任务草稿
    
    Returns:
        True 如果需要搜索
    """
    # 如果任务草稿已有明确目标，不需要搜索
    if task_draft and task_draft.get("goal") and task_draft.get("research_focus"):
        return False
    
    # 检查是否包含专业术语
    terms = extract_domain_terms(user_input)
    if terms:
        return True
    
    # 检查输入长度 - 太短不搜索
    if len(user_input.strip()) < 10:
        return False
    
    # 包含研究相关关键词
    research_keywords = ['研究', '调研', '分析', '机制', '靶点', '药物', '临床', '市场', '竞争']
    if any(kw in user_input for kw in research_keywords):
        return True
    
    return False


def _extract_json(s: str) -> dict:
    """Extract JSON from agent output."""
    s = (s or "").strip()
    if s.startswith("{") and s.endswith("}"):
        return json.loads(s)
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        return json.loads(s[a:b+1])
    raise ValueError(f"Clarifier did not return JSON: {s[:200]}")


def should_clarify(plan: Plan) -> bool:
    """
    Determine if clarification is needed based on plan.
    
    Args:
        plan: Plan from clarifier
    
    Returns:
        True if clarification is needed
    """
    # Hard boundary: must clarify
    if plan.confidence < 0.6:
        return True
    
    # Soft boundary: missing key info
    if 0.6 <= plan.confidence < 0.7:
        # Check if research_focus is missing or too few
        if not plan.task.research_focus or len(plan.task.research_focus) < 2:
            return True
    
    return False


def should_start_research(plan: Plan) -> bool:
    """
    Determine if research can start directly.
    
    Args:
        plan: Plan from clarifier
    
    Returns:
        True if can start research directly
    """
    return (
        plan.confidence >= 0.85 and
        plan.task.goal and
        len(plan.task.research_focus) >= 3 and
        plan.next_action != "VERIFY_TOPIC"
    )


async def assess_input(
    model: LitellmModel,
    messages: list[dict],
    task_draft: dict,
    enable_pre_search: bool = True
) -> Plan:
    """
    Assess user input and determine if clarification is needed.
    
    Args:
        model: LLM model for clarification
        messages: Conversation history
        task_draft: Current task draft
        enable_pre_search: Whether to enable pre-clarification search
    
    Returns:
        Plan with next_action and assessment
    """
    clarifier = build_clarifier(model)
    
    # Build context from messages
    context = ""
    user_input = ""
    if messages:
        # Get last few messages for context
        recent_messages = messages[-3:] if len(messages) > 3 else messages
        context = "\n".join([
            f"{msg.get('role', 'user')}: {msg.get('content', '')}"
            for msg in recent_messages
        ])
        # Get latest user input
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                user_input = msg.get('content', '')
                break
    
    # Pre-clarification search (if enabled and appropriate)
    search_context = None
    if enable_pre_search and user_input and should_do_pre_search(user_input, task_draft):
        terms = extract_domain_terms(user_input)
        search_context = await pre_clarification_search(user_input, terms)
        if search_context:
            logger.info(f"✅ 轻量搜索完成，发现术语: {search_context.get('verified_terms', [])}")
    
    payload = {
        "messages": messages,
        "task_draft": task_draft or {},
        "context": context,
        "search_context": search_context,  # 添加搜索上下文
        "schema_hint": {
            "next_action": "START_RESEARCH|NEED_CLARIFICATION|CONFIRM_PLAN|VERIFY_TOPIC",
            "task": {
                "goal": "string",
                "research_focus": ["string"]  # At least 3 for START_RESEARCH
            },
            "confidence": "0.0-1.0",
            "why": "string",
            "clarification": {
                "question": "string",
                "options": ["string"],
                "missing_info": "research_topic|research_focus|research_goal"
            },
            "assumptions": ["string"],
            "confirm_prompt": "string"
        }
    }
    
    result = await Runner.run(clarifier, json.dumps(payload, ensure_ascii=False))
    data = _extract_json(result.final_output or "")
    plan = Plan.model_validate(data)
    
    # Post-process: enforce decision logic
    if should_clarify(plan) and plan.next_action not in ["NEED_CLARIFICATION", "VERIFY_TOPIC"]:
        plan.next_action = "NEED_CLARIFICATION"
    
    if should_start_research(plan) and plan.next_action == "CONFIRM_PLAN":
        plan.next_action = "START_RESEARCH"
    
    return plan
