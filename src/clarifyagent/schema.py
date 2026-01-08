from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any

NextAction = Literal[
    "START_RESEARCH",      # 🆕 信息足够，直接开始检索
    "NEED_CLARIFICATION",  # 🆕 信息不够，需要澄清
    "CONFIRM_PLAN",
    "VERIFY_TOPIC",
    "CANNOT_DO",
]

class Task(BaseModel):
    goal: str = ""
    research_focus: List[str] = Field(default_factory=list)
    
class Block(BaseModel):
    reason: Optional[str] = None
    alternatives: List[str] = Field(default_factory=list)

class Plan(BaseModel):
    next_action: NextAction
    
    # CONFIRM_PLAN / START_RESEARCH
    task: Task = Field(default_factory=Task)
    assumptions: List[str] = Field(default_factory=list)
    confirm_prompt: Optional[str] = None
    
    # NEED_CLARIFICATION 🆕
    clarification: Optional[Dict[str, Any]] = None
    
    # VERIFY_TOPIC
    unknown_topic: Optional[str] = None
    search_query: Optional[str] = None
    
    # CANNOT_DO
    block: Block = Field(default_factory=Block)
    
    # Debug
    why: str = ""
    confidence: float = 0.5

# 🆕 新增数据模型
class Source(BaseModel):
    title: str
    url: str
    snippet: Optional[str] = None
    source_type: Optional[str] = None  # "academic", "patent", "news", "clinical"

class Citation(BaseModel):
    text: str
    sources: List[Source]

class Subtask(BaseModel):
    id: int
    focus: str
    queries: List[str]
    parallel: bool = True

class SubtaskResult(BaseModel):
    subtask_id: int
    focus: str
    findings: List[str]
    sources: List[Source]
    confidence: float

class ResearchResult(BaseModel):
    goal: str
    research_focus: List[str]
    findings: Dict[str, SubtaskResult] = Field(default_factory=dict)
    synthesis: str = ""
    citations: List[Citation] = Field(default_factory=list)