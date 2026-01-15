"""
Universal Clarifier Module
通用需求澄清模块 - 可嵌入任何 Agent 场景

核心理念：
1. 识别用户意图中的信息缺口
2. 用最少的问题获取最关键的信息
3. 场景无关，通过配置适配不同用途
"""

import json
import re
import logging
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构定义
# ============================================================

class ClarifyAction(str, Enum):
    """澄清决策结果"""
    PROCEED = "PROCEED"              # 信息充足，可以继续
    NEED_CLARIFICATION = "NEED_CLARIFICATION"  # 需要澄清
    CONFIRM = "CONFIRM"              # 需要确认假设
    REJECT = "REJECT"                # 无法处理的请求


@dataclass
class ClarificationQuestion:
    """澄清问题"""
    question: str                           # 问题文本
    options: List[str] = field(default_factory=list)  # 选项（空=开放式）
    dimension: str = ""                     # 针对的信息维度
    info_gain: float = 0.5                  # 预估信息增益 (0-1)
    required: bool = True                   # 是否必须回答


@dataclass 
class ClarifyResult:
    """澄清评估结果"""
    action: ClarifyAction
    confidence: float                       # 0-1，对用户意图的理解置信度
    reason: str                             # 决策原因
    
    # 解析出的信息
    parsed_intent: Dict[str, Any] = field(default_factory=dict)
    assumptions: List[str] = field(default_factory=list)
    
    # 如果需要澄清
    questions: List[ClarificationQuestion] = field(default_factory=list)
    
    # 如果需要确认
    confirm_message: str = ""
    
    # 信息维度分析
    dimensions: Dict[str, float] = field(default_factory=dict)


# ============================================================
# 信息维度框架（核心抽象）
# ============================================================

# 通用信息维度 - 适用于任何任务
UNIVERSAL_DIMENSIONS = {
    "what": {
        "name": "主体/对象",
        "description": "用户想要处理什么",
        "priority": 1,  # 最高优先级
        "clear_signals": ["具体名称", "明确类型", "可操作对象"],
        "unclear_signals": ["这个", "那个", "它", "我们的XX（未说明）"],
    },
    "action": {
        "name": "动作/操作", 
        "description": "用户想要做什么",
        "priority": 2,
        "clear_signals": ["创建", "修改", "删除", "查询", "分析", "生成"],
        "unclear_signals": ["处理一下", "帮我弄", "搞定"],
    },
    "constraint": {
        "name": "约束/条件",
        "description": "有什么限制或要求",
        "priority": 3,
        "clear_signals": ["时间范围", "数量限制", "格式要求", "质量标准"],
        "unclear_signals": [],  # 约束可以有默认值
    },
    "context": {
        "name": "背景/上下文",
        "description": "为什么需要这样做",
        "priority": 4,
        "clear_signals": ["因为", "为了", "目的是", "用于"],
        "unclear_signals": [],  # 上下文不总是必需
    },
    "output": {
        "name": "输出/结果",
        "description": "期望得到什么形式的结果",
        "priority": 5,
        "clear_signals": ["格式", "文件类型", "详细程度", "长度"],
        "unclear_signals": [],
    },
}


# ============================================================
# 通用 Prompt 模板
# ============================================================

UNIVERSAL_CLARIFIER_PROMPT = """\
You are a universal clarification module. Your job is to assess whether a user request has enough information to proceed, and if not, generate the minimum necessary clarifying questions.

## Core Principles

1. **Minimize friction**: Ask as few questions as possible. One good question > five mediocre ones.
2. **Maximize information gain**: Each question should significantly reduce uncertainty.
3. **Be domain-agnostic**: Don't assume any specific use case.

## Information Dimensions

Assess these 5 universal dimensions (in priority order):

| Dimension | What to Check | Priority |
|-----------|--------------|----------|
| **WHAT** | Is the subject/object clear? | 1 (highest) |
| **ACTION** | Is the desired action clear? | 2 |
| **CONSTRAINT** | Are there specific requirements? | 3 |
| **CONTEXT** | Is the purpose/background clear? | 4 |
| **OUTPUT** | Is the expected result format clear? | 5 |

## Decision Logic
```
confidence = weighted_average(dimension_scores)

if WHAT is unclear (score < 0.4):
    → Must clarify WHAT first (other dimensions don't matter yet)
elif ACTION is unclear (score < 0.4):
    → Clarify ACTION
elif confidence >= threshold:
    → PROCEED (can start with reasonable defaults)
elif confidence >= threshold - 0.15:
    → CONFIRM (state assumptions, ask for confirmation)
else:
    → NEED_CLARIFICATION (ask about lowest-scoring dimension)
```

## CRITICAL: Check Conversation Context

**ALWAYS check `additional_context.conversation_summary`** before making decisions:

1. **If conversation_summary contains "用户已补充项目信息" or "用户已回答澄清问题"**:
   - The user has ALREADY answered a clarification question
   - DO NOT ask the same question again
   - Extract information from the user's answer and proceed
   - Confidence should be HIGH (>= 0.8) if sufficient details provided

2. **If conversation_summary shows a Q&A pair**:
   - The user has provided information in response to a question
   - Use that information to fill in missing dimensions
   - Only ask NEW questions about remaining unclear dimensions

3. **Example**:
   - Summary: "用户最初请求: 评估我们的ADC管线\n【重要】用户已补充项目信息: 临床2期，B7-H3, 卵巢癌"
   - This means: User wants to evaluate ADC pipeline, and has provided: Phase 2, B7-H3 target, ovarian cancer
   - Action: PROCEED with high confidence (0.85+), do NOT ask again about target/stage/indication

## Private Information Detection

**Must ask user** when they reference:
- Their own data: "我的", "我们的", "公司的", "my", "our"
- Unnamed entities: "这个项目", "那个文件", "the thing"
- Internal context: "之前讨论的", "上次的"

**Can infer or use defaults** when:
- Public/general knowledge
- Standard conventions
- Optional preferences
- **User has already provided information in conversation_summary**

## Question Generation Guidelines

## Question Generation Guidelines

**Markdown Format (Strict Compliance Required)**:
- **Bold** the titles.
- Leave one blank line after the title.
- **Mandatory Numbering**: If there are two or more questions, they **must** be formatted as a numbered list (1. 2. 3.).
- **Bold** the field names.
- **Indentation for Sub-options**: Any sub-choices or options (A, B, C) under a question must be indented using bullet points.

**[Title]**

[Optional explanatory text]

1. **[Field 1]**: [Question Content]
   - A. [Option A]
   - B. [Option B]
2. **[Field 2]**: [Question Content]
   - A. [Option A]
   - B. [Option B]
```


1. **Open-ended** (for WHAT/ACTION unclear):
   - "**Please provide more information**\n\n- **Type**: What is the type?\n- **Features**: What are the main features?"

2. **Choice-based** (for CONSTRAINT/OUTPUT unclear):
   - "**Please choose**\n\n- **Format**: A / B / Other\n- **Scope**: X / Y / Other"

3. **Confirmation** (when mostly clear):
   - "**Please confirm**\n\nI understand you want X, is that correct?"


## Output Format (STRICT JSON)

{
    "action": "PROCEED|NEED_CLARIFICATION|CONFIRM|REJECT",
    "confidence": 0.0-1.0,
    "reason": "Brief explanation",
    "dimensions": {
        "what": 0.0-1.0,
        "action": 0.0-1.0,
        "constraint": 0.0-1.0,
        "context": 0.0-1.0,
        "output": 0.0-1.0
    },
    "parsed_intent": {
        "subject": "Identified subject or null",
        "action": "Identified action or null",
        "constraints": ["constraint1", ...],
        "context": "Identified context or null",
        "output_format": "Identified format or null"
    },
    "assumptions": ["assumption1", ...],
    "questions": [
        {
            "question": "Question text (use Markdown list for multiple questions)",
            "options": ["opt1", "opt2", "opt3"] or [],
            "dimension": "what|action|constraint|context|output",
            "info_gain": 0.0-1.0,
            "required": true|false
        }
    ],
    "confirm_message": "Confirmation message if action=CONFIRM"
}

## Examples

### Example 1: Clear Request
Input: "帮我把这个 CSV 文件转换成 JSON 格式"
Output:
```json
{
    "action": "PROCEED",
    "confidence": 0.9,
    "reason": "主体(CSV文件)、动作(转换)、输出格式(JSON)都很清晰",
    "dimensions": {"what": 0.9, "action": 1.0, "constraint": 0.7, "context": 0.5, "output": 1.0},
    "parsed_intent": {
        "subject": "CSV文件",
        "action": "格式转换",
        "constraints": [],
        "output_format": "JSON"
    },
    "assumptions": ["使用标准JSON格式", "保留所有字段"],
    "questions": []
}
```

### Example 2: Missing Subject
Input: "帮我分析一下"
Output:
```json
{
    "action": "NEED_CLARIFICATION",
    "confidence": 0.2,
    "reason": "缺少分析对象",
    "dimensions": {"what": 0.0, "action": 0.7, "constraint": 0.3, "context": 0.0, "output": 0.3},
    "parsed_intent": {"action": "分析"},
    "questions": [
        {
            "question": "请问您想分析什么内容？",
            "options": [],
            "dimension": "what",
            "info_gain": 0.9,
            "required": true
        }
    ]
}
```

### Example 3: Private Information
Input: "评估我们产品的市场前景"
Output:
```json
{
    "action": "NEED_CLARIFICATION",
    "confidence": 0.3,
    "reason": "用户提到'我们产品'但未说明具体是什么",
    "dimensions": {"what": 0.2, "action": 0.8, "constraint": 0.4, "context": 0.6, "output": 0.5},
    "parsed_intent": {"action": "市场前景评估", "context": "用户自有产品"},
    "questions": [
        {
            "question": "请简要描述您的产品：\n- 是什么类型的产品？\n- 主要面向哪些用户？",
            "options": [],
            "dimension": "what",
            "info_gain": 0.85,
            "required": true
        }
    ]
}
```

### Example 4: Needs Confirmation
Input: "写一篇关于人工智能的文章"
Output:
```json
{
    "action": "CONFIRM",
    "confidence": 0.7,
    "reason": "主题明确但范围和风格可以有多种理解",
    "dimensions": {"what": 0.8, "action": 0.9, "constraint": 0.5, "context": 0.4, "output": 0.6},
    "parsed_intent": {"subject": "人工智能", "action": "撰写文章"},
    "assumptions": ["通用科普风格", "中等长度(1000-2000字)", "面向一般读者"],
    "confirm_message": "我将撰写一篇面向一般读者的AI科普文章，约1500字。需要调整方向吗？",
    "questions": []
}
```
"""


# ============================================================
# 核心澄清器类
# ============================================================

class UniversalClarifier:
    """
    通用需求澄清器
    
    使用方式:
        clarifier = UniversalClarifier(llm_call_func)
        result = await clarifier.assess(user_input, context)
        
        if result.action == ClarifyAction.NEED_CLARIFICATION:
            # 向用户提问
            for q in result.questions:
                answer = ask_user(q.question, q.options)
        elif result.action == ClarifyAction.PROCEED:
            # 继续执行任务
            execute_task(result.parsed_intent)
    """
    
    def __init__(
        self,
        llm_call: Callable,  # async func(prompt, system) -> str
        confidence_threshold: float = 0.75,
        max_questions: int = 3,
        custom_dimensions: Optional[Dict] = None,
        custom_prompt_additions: str = "",
    ):
        """
        初始化澄清器
        
        Args:
            llm_call: LLM 调用函数，签名为 async (prompt: str, system: str) -> str
            confidence_threshold: 置信度阈值，高于此值可直接执行
            max_questions: 单次最多问几个问题
            custom_dimensions: 自定义信息维度（会与默认维度合并）
            custom_prompt_additions: 添加到 prompt 末尾的自定义内容
        """
        self.llm_call = llm_call
        self.confidence_threshold = confidence_threshold
        self.max_questions = max_questions
        self.dimensions = {**UNIVERSAL_DIMENSIONS, **(custom_dimensions or {})}
        self.custom_prompt = custom_prompt_additions
    
    def _build_system_prompt(self) -> str:
        """构建系统 prompt"""
        prompt = UNIVERSAL_CLARIFIER_PROMPT.replace(
            "confidence >= threshold",
            f"confidence >= {self.confidence_threshold}"
        )
        if self.custom_prompt:
            prompt += f"\n\n## Additional Context\n{self.custom_prompt}"
        return prompt
    
    def _detect_private_info(self, text: str) -> bool:
        """检测是否涉及私有信息"""
        patterns = [
            r'我们的', r'我的', r'公司的', r'团队的',
            r'这个项目', r'那个文件', r'之前的',
            r'\bour\b', r'\bmy\b', r'\bthis\b.*\bproject\b',
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)
    
    def _pre_analyze(self, user_input: str) -> Dict[str, Any]:
        """预分析用户输入（规则基础，不需要 LLM）"""
        analysis = {
            "has_private_info": self._detect_private_info(user_input),
            "input_length": len(user_input),
            "has_question_mark": "?" in user_input or "？" in user_input,
            "detected_entities": [],
            "detected_actions": [],
        }
        
        # 检测动作词
        action_patterns = [
            (r'(创建|生成|写|制作|做)', 'create'),
            (r'(修改|编辑|更新|改)', 'modify'),
            (r'(删除|移除|清除)', 'delete'),
            (r'(查询|搜索|查找|找)', 'search'),
            (r'(分析|评估|研究|调研)', 'analyze'),
            (r'(转换|转成|变成)', 'convert'),
            (r'(总结|概括|归纳)', 'summarize'),
            (r'(解释|说明|介绍)', 'explain'),
        ]
        for pattern, action in action_patterns:
            if re.search(pattern, user_input):
                analysis["detected_actions"].append(action)
        
        return analysis
    
    async def assess(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict]] = None,
        additional_context: Optional[Dict] = None,
    ) -> ClarifyResult:
        """
        评估用户输入，决定是否需要澄清
        
        Args:
            user_input: 用户当前输入
            conversation_history: 对话历史 [{"role": "user/assistant", "content": "..."}]
            additional_context: 额外上下文信息
            
        Returns:
            ClarifyResult 包含决策和可能的澄清问题
        """
        # #region agent log
        import os
        log_path = "/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "I",
                    "location": "universal_clarifier.py:400",
                    "message": "UniversalClarifier.assess entry",
                    "data": {
                        "user_input": user_input,
                        "conversation_history_length": len(conversation_history) if conversation_history else 0,
                        "conversation_history_last_3": conversation_history[-3:] if conversation_history and len(conversation_history) >= 3 else (conversation_history if conversation_history else []),
                        "additional_context_keys": list(additional_context.keys()) if additional_context else [],
                        "additional_context_conversation_summary": additional_context.get("conversation_summary", "") if additional_context else "",
                        "additional_context_task_draft": additional_context.get("task_draft", {}) if additional_context else {},
                    },
                    "timestamp": int(__import__("time").time() * 1000)
                }, ensure_ascii=False) + "\n")
        except: pass
        # #endregion
        
        # 预分析
        pre_analysis = self._pre_analyze(user_input)
        
        # 构建 LLM 输入
        payload = {
            "user_input": user_input,
            "pre_analysis": pre_analysis,
            "conversation_history": conversation_history[-5:] if conversation_history else [],
            "additional_context": additional_context or {},
            "config": {
                "confidence_threshold": self.confidence_threshold,
                "max_questions": self.max_questions,
            }
        }
        
        # #region agent log
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "J",
                    "location": "universal_clarifier.py:430",
                    "message": "before LLM call",
                    "data": {
                        "payload_conversation_history": payload["conversation_history"],
                        "payload_additional_context": payload["additional_context"],
                    },
                    "timestamp": int(__import__("time").time() * 1000)
                }, ensure_ascii=False) + "\n")
        except: pass
        # #endregion
        
        # 调用 LLM
        system_prompt = self._build_system_prompt()
        response = await self.llm_call(
            json.dumps(payload, ensure_ascii=False),
            system_prompt
        )
        
        # #region agent log
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "K",
                    "location": "universal_clarifier.py:450",
                    "message": "after LLM call",
                    "data": {
                        "response_preview": response[:500] if response else "",
                    },
                    "timestamp": int(__import__("time").time() * 1000)
                }, ensure_ascii=False) + "\n")
        except: pass
        # #endregion
        
        # 解析结果
        result = self._parse_response(response)
        
        # #region agent log
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "L",
                    "location": "universal_clarifier.py:465",
                    "message": "UniversalClarifier.assess exit",
                    "data": {
                        "result_action": str(result.action),
                        "result_confidence": result.confidence,
                        "result_reason": result.reason,
                        "result_parsed_intent": result.parsed_intent,
                        "result_questions": [q.question for q in result.questions],
                    },
                    "timestamp": int(__import__("time").time() * 1000)
                }, ensure_ascii=False) + "\n")
        except: pass
        # #endregion
        
        return result
    
    def _parse_response(self, response: str) -> ClarifyResult:
        """解析 LLM 响应"""
        try:
            # 提取 JSON
            data = self._extract_json(response)
            
            # 构建结果
            questions = [
                ClarificationQuestion(
                    question=q.get("question", ""),
                    options=q.get("options", []),
                    dimension=q.get("dimension", ""),
                    info_gain=q.get("info_gain", 0.5),
                    required=q.get("required", True),
                )
                for q in data.get("questions", [])[:self.max_questions]
            ]
            
            return ClarifyResult(
                action=ClarifyAction(data.get("action", "NEED_CLARIFICATION")),
                confidence=data.get("confidence", 0.5),
                reason=data.get("reason", ""),
                parsed_intent=data.get("parsed_intent", {}),
                assumptions=data.get("assumptions", []),
                questions=questions,
                confirm_message=data.get("confirm_message", ""),
                dimensions=data.get("dimensions", {}),
            )
        except Exception as e:
            logger.error(f"Failed to parse clarifier response: {e}")
            # 返回安全的默认值
            return ClarifyResult(
                action=ClarifyAction.NEED_CLARIFICATION,
                confidence=0.0,
                reason=f"解析失败: {e}",
                questions=[ClarificationQuestion(
                    question="请问您具体想要做什么？",
                    dimension="what",
                    info_gain=0.9,
                )]
            )
    
    def _extract_json(self, s: str) -> dict:
        """从响应中提取 JSON"""
        s = (s or "").strip()
        # 尝试直接解析
        if s.startswith("{"):
            try:
                return json.loads(s)
            except:
                pass
        # 查找 JSON 块
        patterns = [
            r'```json\s*(.*?)\s*```',
            r'```\s*(.*?)\s*```',
            r'\{.*\}',
        ]
        for pattern in patterns:
            match = re.search(pattern, s, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1) if '```' in pattern else match.group(0))
                except:
                    continue
        raise ValueError(f"Cannot extract JSON from: {s[:200]}")


# ============================================================
# 便捷函数和集成助手
# ============================================================

def create_clarifier_for_litellm(
    model: str = "gpt-4o-mini",
    **kwargs
) -> UniversalClarifier:
    """为 LiteLLM 创建澄清器"""
    import litellm
    
    async def llm_call(prompt: str, system: str) -> str:
        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content
    
    return UniversalClarifier(llm_call, **kwargs)


# ============================================================
# 场景特化配置示例
# ============================================================

# Deep Research 场景
DEEP_RESEARCH_ADDITIONS = """
## Deep Research Specific

For research tasks, also consider:
- **Scope**: Time range, geographic focus, industry vertical
- **Depth**: Overview vs comprehensive analysis
- **Sources**: Academic, industry reports, news, primary data

When action=PROCEED, also output:
- "research_focus": List of 3-5 specific research areas
- "confirm_message": MUST include all research_focus items as bullet list

## CRITICAL: Multi-Question Clarification Format

When you need to ask MULTIPLE questions (e.g., asking about indication, development stage, and target market together):

**DO NOT** put all options in the `options` array. This causes rendering issues.

**INSTEAD**, format the `question` field as a complete Markdown document with embedded options:

```json
{
    "question": "**请补充您的产品关键信息**\n\n为了准确分析，需要了解：\n\n1. **目标适应症**：主要针对哪种疾病？\n   * A. 特应性皮炎（AD）\n   * B. 哮喘\n   * C. 其他（请说明）\n\n2. **开发阶段**：目前处于什么阶段？\n   * A. 临床前\n   * B. 临床I期\n   * C. 临床II期\n   * D. 临床III期\n   * E. 已提交上市申请\n\n3. **目标市场**：计划在哪些地区上市？\n   * A. 美国\n   * B. 欧洲\n   * C. 中国\n   * D. 全球",
    "options": [],
    "dimension": "what",
    "info_gain": 0.9,
    "required": true
}
```

Key rules:
1. Put ALL questions and their options in the `question` field using Markdown
2. Keep `options` array EMPTY when asking multiple questions
3. Number the questions (1. 2. 3.)
4. Use `* A.` `* B.` `* C.` format for sub-options with indentation
5. User will answer like "1. A, 2. C, 3. B" or "1. 特应性皮炎, 2. 临床II期, 3. 中国"
"""

# 代码生成场景
CODE_GEN_ADDITIONS = """
## Code Generation Specific

For coding tasks, also consider:
- **Language**: Programming language preference
- **Framework**: Specific libraries or frameworks
- **Style**: Coding conventions, documentation level

When action=PROCEED, also output:
- "tech_stack": Identified technologies
- "file_structure": Suggested file organization
"""

# 客服场景
CUSTOMER_SERVICE_ADDITIONS = """
## Customer Service Specific

For support queries:
- Try to identify the product/service involved
- Check if it's a complaint, question, or request
- Assess urgency level

When action=PROCEED, also output:
- "category": Issue category
- "urgency": low/medium/high
- "sentiment": positive/neutral/negative
"""