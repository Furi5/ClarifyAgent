"""Planner module for task decomposition and strategy planning."""
import json
from typing import List
from agents import Agent, Runner
from agents.extensions.models.litellm_model import LitellmModel
from .anthropic_model import AnthropicModel

from .schema import Task, Subtask


PLANNER_SYSTEM_PROMPT = """\
You are a research planner. Analyze what needs to be researched.
Output ONLY valid JSON.

## Your Task
Given a research goal and context, identify what specific aspects need to be investigated.
**Pay close attention to the user's actual need** - it may be scientific research, market analysis, competitive intelligence, or other types.

## Principles
1. Each subtask should answer a DISTINCT question
2. Avoid overlap between subtasks
3. Be efficient - only create subtasks that add real value
4. **Match the research type to user's goal** (科研 vs 市场分析 vs 竞争情报)
5. No arbitrary limits - create as many or as few as needed

## Output Format

{
    "subtasks": [
        {
            "id": 1,
            "focus": "What this subtask investigates",
            "queries": ["search query 1", "search query 2"]
        }
    ]
}

## Example 1: Scientific Research

Goal: "KRAS G12C 抑制剂的研究进展"
Context: []

{
    "subtasks": [
        {"id": 1, "focus": "已上市/临床阶段的KRAS G12C抑制剂", "queries": ["KRAS G12C inhibitor approved drugs", "KRAS G12C clinical trials"]},
        {"id": 2, "focus": "临床疗效和安全性数据", "queries": ["sotorasib adagrasib efficacy safety data"]},
        {"id": 3, "focus": "耐药机制和联合用药策略", "queries": ["KRAS G12C resistance mechanisms combination therapy"]}
    ]
}

## Example 2: Market Analysis & Competitive Intelligence

Goal: "STAT6抑制剂 - 市场分析和销售预测 (Competitive Decision)"
Context: ["销售预测和竞争决策分析", "适应症：特应性皮炎", "研发阶段：二期", "目标市场：中国"]

{
    "subtasks": [
        {"id": 1, "focus": "特应性皮炎市场规模和增长趋势（中国）", "queries": ["atopic dermatitis market size China 2024", "特应性皮炎中国市场规模"]},
        {"id": 2, "focus": "STAT6抑制剂竞争格局和竞品分析", "queries": ["STAT6 inhibitor pipeline competitors", "STAT6抑制剂竞品企业"]},
        {"id": 3, "focus": "特应性皮炎现有治疗方案和定价", "queries": ["atopic dermatitis treatment pricing China", "Dupixent Rinvoq price China"]},
        {"id": 4, "focus": "二期临床药物市场预测方法", "queries": ["phase 2 drug sales forecast methodology", "药物销售预测模型"]},
        {"id": 5, "focus": "JAK/STAT通路药物商业化案例", "queries": ["JAK inhibitor commercialization case study", "Rinvoq Cibinqo launch success"]}
    ]
}
"""


def build_planner(model: AnthropicModel) -> Agent:
    """Build the planner (orchestrator) agent."""
    # Use LitellmModel wrapper for agents framework compatibility
    # litellm will use ANTHROPIC_API_KEY from environment
    from .config import ANTHROPIC_API_KEY
    litellm_model = LitellmModel(
        model=f"anthropic/{model.model}",
        api_key=ANTHROPIC_API_KEY
    )
    return Agent(
        name="Planner",
        model=litellm_model,
        instructions=PLANNER_SYSTEM_PROMPT,
        tools=[]  # Planner doesn't use tools
    )


def _extract_json(s: str) -> dict:
    """Extract JSON from agent output."""
    s = (s or "").strip()
    if s.startswith("{") and s.endswith("}"):
        return json.loads(s)
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        return json.loads(s[a:b+1])
    raise ValueError(f"Planner did not return JSON: {s[:200]}")


async def decompose_task(
    model: AnthropicModel,
    task: Task
) -> List[Subtask]:
    """
    Decompose a research task into subtasks.
    LLM 自由决定需要研究哪些方面。
    
    Args:
        model: LLM model for planning
        task: Research task to decompose
    
    Returns:
        List of subtasks
    """
    planner = build_planner(model)
    
    payload = {
        "goal": task.goal,
        "context": task.research_focus if task.research_focus else []
    }
    
    result = await Runner.run(planner, json.dumps(payload, ensure_ascii=False))
    data = _extract_json(result.final_output or "")
    
    # Convert to Subtask objects
    subtasks = []
    for st_data in data.get("subtasks", []):
        subtasks.append(Subtask(
            id=st_data.get("id", len(subtasks) + 1),
            focus=st_data.get("focus", ""),
            queries=st_data.get("queries", []),
            parallel=True
        ))
    
    print(f"[PLANNER] Created {len(subtasks)} subtasks: {[s.focus for s in subtasks]}")
    
    return subtasks
