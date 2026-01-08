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
# 通用模式，适用于各领域
DOMAIN_TERM_PATTERNS = [
    r'[A-Z]{2,}[\-]?[A-Z0-9]*',        # 缩写词：如 AI, API, GDP, ESG
    r'[A-Z][a-z]+[A-Z][a-z]+',          # 驼峰式专有名词
    r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)+',   # 多词专有名词：如 Tesla Model
]


CLARIFIER_SYSTEM_PROMPT = """\
You are a clarification module for a Deep Research platform.
You MUST output ONLY valid JSON (no markdown, no extra text).

## Core Principle: Minimize User Friction

**Ask as few questions as possible. One well-crafted question is better than five.**

## CRITICAL: Understanding Conversation Context

When processing user input, ALWAYS check:
1. **conversation_summary** - Shows the original request and any follow-up answers
2. **task_draft.pipeline_info** - Contains user-provided project/product details
3. **task_draft.clarification_responses** - Previous Q&A pairs

**Example flow:**
- User first says: "评估我们的产品"
- System asks: "请简单描述您的产品：名称、类型、目标市场是什么？"
- User answers: "智能音箱，面向家庭用户"
- NOW: conversation_summary will show this is a FOLLOW-UP answer
- DO NOT ask more questions - user has provided the info, proceed to research!

**If user has already provided project details, confidence should be HIGH (0.85+)**

## Detecting Private vs Public Information

**CRITICAL**: Distinguish between:
1. **Public information**: Named entities that can be searched (companies, products, people, events)
   → Can directly research with web search
2. **Private information**: User's own project/product/data (e.g., "我们的产品", "我的项目", "公司的方案")
   → Must ask user to provide details

**Signals of private information:**
- "我们的", "我的", "公司的", "团队的"
- "我有一个", "我们开发的", "自研的"
- "our", "my", "we have"

## Clarification Strategy

### For Private Information → Use ONE Open-Ended Question

When user mentions their own project/product, ask ONE comprehensive question to gather key details:

```json
{
    "clarification": {
        "question": "请简单描述您的项目/产品：具体是什么？目前处于什么阶段？主要目标是什么？",
        "options": [],
        "missing_info": "project_details",
        "open_ended": true
    }
}
```

**DO NOT** ask multiple rounds. **DO** ask once with all key questions.

### For Public Information → Smart Defaults

If topic is clear and searchable, **don't ask** unnecessary questions.
Assume comprehensive research and directly start.

Only clarify if truly ambiguous (e.g., "帮我研究一下" with no context).

### For Ambiguous Requests → Maximum 3 Options

If must provide options, limit to 3:
```json
{
    "options": [
        "选项1（最可能的意图）",
        "选项2（次可能的意图）", 
        "其他（请说明）"
    ]
}
```

## Decision Logic

1. **Private info detected + missing details** → NEED_CLARIFICATION (open-ended)
2. **Public info + clear topic** (confidence >= 0.7) → START_RESEARCH or CONFIRM_PLAN
3. **Completely vague** (confidence < 0.5) → NEED_CLARIFICATION (max 3 options)
4. **Unknown term** → VERIFY_TOPIC

## Assessment Criteria

1. **Topic clarity** (0.0-0.4):
   - Specific named entity → +0.4
   - General category → +0.2
   - Vague/missing → +0.0

2. **Scope inferability** (0.0-0.3):
   - Can infer comprehensive research areas → +0.3
   - Partial inference → +0.15

3. **Goal clarity** (0.0-0.3):
   - Clear goal stated → +0.3
   - Implied goal → +0.2
   - No goal (assume comprehensive) → +0.1

## Examples

### Example 1: Private Information (Open-Ended)
Input: "评估我们的新产品市场前景"
Assessment: Private info (我们的), need product details
→ NEED_CLARIFICATION
```json
{
    "next_action": "NEED_CLARIFICATION",
    "confidence": 0.3,
    "why": "用户提到'我们的'产品，需要了解具体信息",
    "clarification": {
        "question": "请简单描述您的产品：是什么类型的产品？目标用户群体是谁？主要功能或特点是什么？",
        "options": [],
        "missing_info": "project_details",
        "open_ended": true
    }
}
```

### Example 2: Public Information (Direct Start)
Input: "特斯拉 2024 年销量分析"
Assessment: Clear public topic, can infer research scope
→ START_RESEARCH (confidence 0.85+)

### Example 3: Ambiguous (Minimal Options)
Input: "帮我研究一下市场"
Assessment: Too broad, need to narrow down
→ NEED_CLARIFICATION
```json
{
    "clarification": {
        "question": "您想研究哪个市场？",
        "options": [
            "特定行业市场（如新能源、AI、医疗等）",
            "特定地区市场（如中国、美国、东南亚等）",
            "其他（请说明具体市场）"
        ],
        "missing_info": "research_scope"
    }
}
```

### Example 4: User Provides Details After Open Question
Previous: Asked for project details
Input: "智能家居产品，面向年轻家庭，主打语音控制"
Assessment: All key info provided
→ START_RESEARCH (confidence 0.9)

## Output Format

{
    "next_action": "START_RESEARCH|NEED_CLARIFICATION|CONFIRM_PLAN|VERIFY_TOPIC",
    "task": {
        "goal": "Research goal",
        "research_focus": ["focus 1", "focus 2", ...]
    },
    "confidence": 0.0-1.0,
    "why": "Brief reason",
    "clarification": {
        "question": "Question text",
        "options": ["opt1", "opt2", "opt3"],  // Max 3, or empty for open-ended
        "missing_info": "project_details|research_scope|research_topic",
        "open_ended": true|false  // True = no options, user types freely
    },
    "assumptions": ["assumption 1", ...],
    "confirm_prompt": "Confirmation prompt"
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
    conversation_summary = ""
    if messages:
        # Get last few messages for context
        recent_messages = messages[-5:] if len(messages) > 5 else messages
        context = "\n".join([
            f"{msg.get('role', 'user')}: {msg.get('content', '')}"
            for msg in recent_messages
        ])
        # Get latest user input
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                user_input = msg.get('content', '')
                break
        
        # 构建对话摘要，帮助 LLM 理解上下文
        user_msgs = [m for m in messages if m.get('role') == 'user']
        if len(user_msgs) >= 2:
            first_msg = user_msgs[0].get('content', '')
            conversation_summary = f"用户最初请求: {first_msg}"
            if task_draft.get('project_info'):
                conversation_summary += f"\n用户补充的项目信息: {task_draft['project_info']}"
            elif task_draft.get('pipeline_info'):  # 兼容旧字段
                conversation_summary += f"\n用户补充的项目信息: {task_draft['pipeline_info']}"
            if task_draft.get('clarification_responses'):
                for resp in task_draft['clarification_responses']:
                    conversation_summary += f"\n问: {resp.get('question', '')}\n答: {resp.get('answer', '')}"
    
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
        "conversation_summary": conversation_summary,  # 对话脉络摘要
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
