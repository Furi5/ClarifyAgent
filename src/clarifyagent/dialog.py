from dataclasses import dataclass, field
from typing import Any

@dataclass
class SessionState:
    messages: list[dict] = field(default_factory=list)
    task_draft: dict[str, Any] = field(default_factory=dict)
    asked: int = 0
    last_research_result: dict[str, Any] = field(default_factory=dict)  # 保存最后的研究结果
    conversation_mode: str = "research"  # "research" 或 "chat"
    research_history: list[dict] = field(default_factory=list)  # 历史研究结果

def add_user(state: SessionState, text: str) -> None:
    state.messages.append({"role": "user", "content": text})

def add_clarification(state: SessionState, text: str) -> None:
    state.messages.append({"role": "user", "content": text})

def update_task_draft(state: SessionState, task: dict[str, Any]) -> None:
    state.task_draft = task

def add_assistant(state: SessionState, content: str):
    """记录 assistant 的回复"""
    state.messages.append({"role": "assistant", "content": content})


def save_research_result(state: SessionState, result: dict):
    """保存研究结果，切换到对话模式"""
    state.last_research_result = result
    state.conversation_mode = "chat"


def is_new_research_task(message: str, state: SessionState) -> bool:
    """检测是否是新的调研任务"""
    message_lower = message.strip().lower()
    
    # 新调研任务的强指标
    strong_indicators = [
        "请提供", "请分析", "请调研", "请研究", "请评估",
        "分析一下", "调研一下", "研究一下", "评估一下",
        "帮我分析", "帮我调研", "帮我研究", "帮我评估",
        "我想了解", "我需要", "想知道关于"
    ]
    
    # 专业调研领域关键词
    domain_keywords = [
        "管线", "pipeline", "合成路线", "逆合成", "synthesis", 
        "临床数据", "clinical", "市场分析", "竞争格局",
        "投资价值", "商业化", "开发阶段", "适应症",
        "靶点", "target", "机制", "moa", "疗效", "efficacy",
        "安全性", "safety", "获批", "approval", "审评",
        "专利", "patent", "技术", "工艺", "制备", "收率"
    ]
    
    # 检查是否包含强指标
    has_strong_indicator = any(indicator in message_lower for indicator in strong_indicators)
    
    # 检查是否包含专业关键词
    has_domain_keyword = any(keyword in message_lower for keyword in domain_keywords)
    
    # 长消息通常是新任务（超过50字符且包含专业词汇）
    is_substantial_query = len(message_lower) > 50 and has_domain_keyword
    
    return has_strong_indicator or is_substantial_query


def start_new_research_session(state: SessionState) -> None:
    """开始新的研究会话"""
    # 保存之前的研究结果到历史记录
    if state.last_research_result:
        state.research_history.append(state.last_research_result.copy())
    
    # 重置研究状态但保持会话历史
    state.last_research_result = {}
    state.conversation_mode = "research"
    state.task_draft = {}
    state.asked = 0
    
    print(f"[DEBUG] Started new research session, research history has {len(state.research_history)} previous results")


def is_simple_followup(message: str, state: SessionState) -> bool:
    """判断是否是简单的后续对话"""
    if state.conversation_mode != "chat" or not state.last_research_result:
        return False
    
    message_lower = message.strip().lower()
    
    # 新调研任务的关键词（这些明确表示要开始新的研究）
    new_research_indicators = [
        "请提供", "分析", "调研", "研究", "评估", "比较", "对比分析", 
        "管线", "pipeline", "合成路线", "临床数据", "市场分析",
        "竞争格局", "投资价值", "商业化", "开发阶段", "适应症",
        "靶点", "机制", "疗效", "安全性", "获批", "审评",
        "专利", "技术", "工艺", "制备", "收率"
    ]
    
    # 如果包含新调研关键词，不是简单后续
    if any(indicator in message_lower for indicator in new_research_indicators):
        return False
    
    # 简单后续问题的特征（基于之前结果的追问）
    followup_patterns = [
        "那", "而且", "另外", "还有", "进一步", "更进一步",
        "为什么", "怎么", "什么时候", "多少钱", "哪个更", "哪些更",
        "更多细节", "详细说明", "具体怎么", "能否解释", "意思是",
        "这意味着", "也就是说", "换句话说", "简单来说"
    ]
    
    # 长度检查：非常短的问题可能是后续（但要排除新任务关键词）
    if len(message_lower) < 15:
        # 检查是否包含简单疑问词
        simple_questions = ["为什么", "怎么", "什么", "哪个", "多少", "是吗", "对吗"]
        return any(q in message_lower for q in simple_questions)
    
    # 检查是否包含后续问题关键词
    return any(pattern in message for pattern in followup_patterns)