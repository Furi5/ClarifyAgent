"""Clarifier module for assessing information sufficiency and generating clarifications."""
import json
import re
import logging
from datetime import datetime
from typing import Optional, List, Dict
from .anthropic_model import AnthropicModel

from .schema import Plan, Task
from .universal_clarifier import (
    UniversalClarifier,
    ClarifyAction,
    ClarifyResult,
    DEEP_RESEARCH_ADDITIONS,
)
from .tools.serperapi import web_search

logger = logging.getLogger(__name__)

# 轻量搜索配置
LIGHT_SEARCH_NUM_RESULTS = 3
SEARCH_CONFIDENCE_MIN = 0.3
SEARCH_CONFIDENCE_MAX = 0.75

# 专业术语模式（用于判断是否需要搜索验证）
DOMAIN_TERM_PATTERNS = [
    r'[A-Z]{2,}[\-]?[A-Z0-9]*',
    r'[A-Z][a-z]+[A-Z][a-z]+',
    r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)+',
]


def extract_domain_terms(text: str) -> list[str]:
    """从文本中提取专业术语"""
    terms = set()
    for pattern in DOMAIN_TERM_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        terms.update(m.strip() for m in matches if len(m.strip()) >= 2)
    
    common_words = {'AI', 'OK', 'API', 'US', 'UK', 'EU', 'IT', 'ID'}
    terms = [t for t in terms if t.upper() not in common_words]
    
    return list(terms)[:5]


async def pre_clarification_search(
    user_input: str,
    terms: list[str],
    num_results: int = LIGHT_SEARCH_NUM_RESULTS
) -> Optional[Dict]:
    """执行澄清前的轻量搜索"""
    if not terms:
        return None
    
    try:
        main_term = terms[0]
        query = f"{main_term} research overview"
        
        # 使用原始搜索函数获取结构化数据
        from .tools.serperapi import _search_sync
        import asyncio
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, _search_sync, query, num_results)
        
        if results and results.get("organic_results"):
            organic = results["organic_results"]
            verified_terms = [
                t for t in terms 
                if any(t.lower() in r.get("title", "").lower() or t.lower() in r.get("snippet", "").lower() 
                       for r in organic)
            ]
            return {
                "query": query,
                "results": organic[:num_results],
                "verified_terms": verified_terms,
            }
    except Exception as e:
        logger.warning(f"Pre-search failed: {e}")
    
    return None


def should_do_pre_search(user_input: str, task_draft: Dict) -> bool:
    """判断是否需要预搜索"""
    if not user_input or len(user_input) < 10:
        return False
    
    # 如果任务草稿已经很完善，不需要搜索
    if task_draft.get("goal") and task_draft.get("research_focus"):
        return False
    
    terms = extract_domain_terms(user_input)
    return len(terms) > 0


def _convert_to_plan(result: ClarifyResult, task_draft: Dict) -> Plan:
    """将 UniversalClarifier 的结果转换为 Plan 格式"""
    
    # 映射 action
    action_map = {
        ClarifyAction.PROCEED: "START_RESEARCH",
        ClarifyAction.NEED_CLARIFICATION: "NEED_CLARIFICATION",
        ClarifyAction.CONFIRM: "CONFIRM_PLAN",
        ClarifyAction.REJECT: "CANNOT_DO",
    }
    next_action = action_map.get(result.action, "NEED_CLARIFICATION")
    
    # 构建 task - 正确组合用户意图
    parsed_intent = result.parsed_intent
    subject = parsed_intent.get("subject", "")
    action = parsed_intent.get("action", "")
    output_format = parsed_intent.get("output_format", "")
    
    # 构建完整的研究目标：主体 + 动作 + 输出格式
    goal_parts = []
    if subject:
        goal_parts.append(subject)
    if action:
        goal_parts.append(action)
    if output_format and output_format not in action:
        goal_parts.append(f"({output_format})")
    
    goal = " - ".join(goal_parts) if goal_parts else task_draft.get("goal", "研究任务")
    
    # 从 parsed_intent 提取 research_focus
    # 优先使用 output_format 和 action 作为研究重点，而不是 constraints
    research_focus = task_draft.get("research_focus", [])
    if not research_focus:
        # 提取用户关心的核心问题作为研究重点
        focus_candidates = []
        if output_format:
            focus_candidates.append(output_format)
        if action and action not in str(focus_candidates):
            focus_candidates.append(action)
        if parsed_intent.get("constraints"):
            # constraints 作为补充信息，如适应症、市场等
            focus_candidates.extend(parsed_intent.get("constraints", []))
        research_focus = focus_candidates if focus_candidates else ["综合研究"]
    
    task = Task(
        goal=goal,
        research_focus=research_focus[:5] if research_focus else ["综合研究"],
    )
    
    # 构建 clarification
    clarification = None
    if result.questions:
        first_q = result.questions[0]
        clarification = {
            "question": first_q.question,
            "options": first_q.options,
            "missing_info": first_q.dimension or "project_details",
            "open_ended": len(first_q.options) == 0,
        }
    
    # 构建 Plan
    plan = Plan(
        next_action=next_action,
        task=task,
        confidence=result.confidence,
        why=result.reason,
        assumptions=result.assumptions,
        clarification=clarification,
        confirm_prompt=result.confirm_message if result.action == ClarifyAction.CONFIRM else None,
    )
    
    return plan


async def assess_input(
    model: AnthropicModel,
    messages: list[dict],
    task_draft: dict,
    enable_pre_search: bool = True
) -> Plan:
    """
    评估用户输入并决定是否需要澄清（向后兼容接口）
    
    Args:
        model: LLM 模型
        messages: 对话历史
        task_draft: 任务草稿
        enable_pre_search: 是否启用预搜索
    
    Returns:
        Plan 对象
    """
    # #region agent log
    import json as json_lib
    import os
    log_path = "/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "A",
                "location": "clarifier.py:157",
                "message": "assess_input entry",
                "data": {
                    "messages_count": len(messages),
                    "task_draft_keys": list(task_draft.keys()),
                    "task_draft_goal": task_draft.get("goal", ""),
                    "task_draft_project_info": task_draft.get("project_info", ""),
                    "task_draft_pipeline_info": task_draft.get("pipeline_info", ""),
                },
                "timestamp": int(__import__("time").time() * 1000)
            }, ensure_ascii=False) + "\n")
    except: pass
    # #endregion
    
    # 创建通用澄清器（Deep Research 特化）
    async def llm_call(prompt: str, system: str) -> str:
        response = await model.acompletion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
    
    clarifier = UniversalClarifier(
        llm_call=llm_call,
        confidence_threshold=0.75,
        max_questions=1,  # Deep Research 一次只问一个问题
        custom_prompt_additions=DEEP_RESEARCH_ADDITIONS,
    )
    
    # 获取用户输入
    user_input = ""
    conversation_history = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        conversation_history.append({"role": role, "content": content})
        if role == "user":
            user_input = content
    
    # #region agent log
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "B",
                "location": "clarifier.py:195",
                "message": "conversation_history extracted",
                "data": {
                    "user_input": user_input,
                    "history_length": len(conversation_history),
                    "history_last_3": conversation_history[-3:] if len(conversation_history) >= 3 else conversation_history,
                },
                "timestamp": int(__import__("time").time() * 1000)
            }, ensure_ascii=False) + "\n")
    except: pass
    # #endregion
    
    # 预搜索（临时禁用以提升性能）
    search_context = None
    if False and enable_pre_search and user_input and should_do_pre_search(user_input, task_draft):
        terms = extract_domain_terms(user_input)
        search_context = await pre_clarification_search(user_input, terms)
        if search_context:
            logger.info(f"✅ 轻量搜索完成，发现术语: {search_context.get('verified_terms', [])}")
        else:
            print(f"[DEBUG] Pre-search disabled for performance optimization")
    
    # 构建额外上下文
    current_date = datetime.now().strftime("%Y年%m月%d日")
    additional_context = {
        "task_draft": task_draft,
        "search_context": search_context,
        "current_date": current_date,
        "date_context": f"当前日期是 {current_date}。当用户询问'最新'或'近期'时，应该指最近1-2年内（{datetime.now().year - 1}-{datetime.now().year}年）的信息。",
    }
    
    # 构建对话摘要
    conversation_summary = ""
    if len(conversation_history) >= 2:
        first_user_msg = next((m for m in conversation_history if m.get("role") == "user"), None)
        if first_user_msg:
            conversation_summary = f"用户最初请求: {first_user_msg.get('content', '')}"
        
        # 检查是否有澄清问题的回答
        if task_draft.get("project_info"):
            conversation_summary += f"\n\n【重要】用户已补充项目信息: {task_draft['project_info']}"
            conversation_summary += "\n这表示用户已经回答了澄清问题，请基于这些信息继续处理，不要再次询问相同的问题。"
        elif task_draft.get("pipeline_info"):  # 兼容旧字段
            conversation_summary += f"\n\n【重要】用户已补充项目信息: {task_draft['pipeline_info']}"
            conversation_summary += "\n这表示用户已经回答了澄清问题，请基于这些信息继续处理，不要再次询问相同的问题。"
        
        if task_draft.get("clarification_responses"):
            conversation_summary += "\n\n澄清问答历史："
            for resp in task_draft["clarification_responses"]:
                conversation_summary += f"\n问: {resp.get('question', '')}\n答: {resp.get('answer', '')}"
        
        # 检查最新的对话，看是否有澄清问答
        assistant_msgs = [m for m in conversation_history if m.get("role") == "assistant"]
        user_msgs = [m for m in conversation_history if m.get("role") == "user"]
        if len(assistant_msgs) >= 1 and len(user_msgs) >= 2:
            last_assistant = assistant_msgs[-1].get("content", "")
            last_user = user_msgs[-1].get("content", "")
            # 如果最后一条 assistant 消息包含"请描述"或"请提供"，且用户有回复，说明用户已回答
            if ("请描述" in last_assistant or "请提供" in last_assistant or "请简单" in last_assistant) and last_user:
                conversation_summary += f"\n\n【最新澄清问答】\n系统问: {last_assistant[:100]}...\n用户答: {last_user}"
                conversation_summary += "\n用户已经回答了澄清问题，请基于用户的回答继续处理。"
    
    if conversation_summary:
        additional_context["conversation_summary"] = conversation_summary
    
    # #region agent log
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "C",
                "location": "clarifier.py:230",
                "message": "before clarifier.assess",
                "data": {
                    "conversation_summary": conversation_summary,
                    "additional_context_keys": list(additional_context.keys()),
                    "task_draft_in_context": additional_context.get("task_draft", {}),
                },
                "timestamp": int(__import__("time").time() * 1000)
            }, ensure_ascii=False) + "\n")
    except: pass
    # #endregion
    
    # 调用通用澄清器
    result = await clarifier.assess(
        user_input=user_input,
        conversation_history=conversation_history,
        additional_context=additional_context,
    )
    
    # #region agent log
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "D",
                "location": "clarifier.py:245",
                "message": "after clarifier.assess",
                "data": {
                    "result_action": str(result.action),
                    "result_confidence": result.confidence,
                    "result_reason": result.reason,
                    "result_parsed_intent": result.parsed_intent,
                    "result_questions_count": len(result.questions),
                    "result_questions": [q.question for q in result.questions],
                },
                "timestamp": int(__import__("time").time() * 1000)
            }, ensure_ascii=False) + "\n")
    except: pass
    # #endregion
    
    # 转换为 Plan 格式
    plan = _convert_to_plan(result, task_draft)
    
    # #region agent log
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "E",
                "location": "clarifier.py:260",
                "message": "plan converted",
                "data": {
                    "plan_next_action": plan.next_action,
                    "plan_confidence": plan.confidence,
                    "plan_task_goal": plan.task.goal,
                    "plan_clarification": plan.clarification,
                },
                "timestamp": int(__import__("time").time() * 1000)
            }, ensure_ascii=False) + "\n")
    except: pass
    # #endregion
    
    # 后处理：强制执行决策规则
    # 调整策略：几乎总是让用户确认计划，只有极高置信度（>= 0.95）才直接执行
    # 这样用户可以查看和修改研究计划
    if result.action == ClarifyAction.PROCEED and plan.confidence >= 0.95:
        # 极高置信度：直接执行（罕见情况）
        plan.next_action = "CONFIRM_PLAN"
        # plan.next_action = "START_RESEARCH"
    elif result.action == ClarifyAction.PROCEED and plan.confidence >= 0.7:
        # 高置信度：展示计划让用户确认/修改
        plan.next_action = "CONFIRM_PLAN"
    elif result.action == ClarifyAction.CONFIRM and plan.confidence >= 0.6:
        # 中等置信度：展示计划让用户确认
        plan.next_action = "CONFIRM_PLAN"
    elif result.action == ClarifyAction.NEED_CLARIFICATION:
        # 需要澄清
        plan.next_action = "NEED_CLARIFICATION"
    else:
        # 默认：需要澄清
        plan.next_action = "NEED_CLARIFICATION"

    return plan


def build_clarifier(model: AnthropicModel):
    """构建澄清器（向后兼容，实际不再使用）"""
    # 这个函数保留是为了向后兼容，实际逻辑在 assess_input 中
    return None
