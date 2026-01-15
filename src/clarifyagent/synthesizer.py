"""Synthesizer module for combining results from multiple subagents."""
import json
import time
from typing import Dict, List
from agents import Agent, Runner
from agents.extensions.models.litellm_model import LitellmModel
from typing import Union
from .anthropic_model import AnthropicModel
from .deepseek_model import DeepseekModel

from .schema import SubtaskResult, ResearchResult, Citation, Source
from .config import MAX_CONTENT_CHARS
from .prompts import SYNTHESIZER_SYSTEM_PROMPT

# 限制传递给 Synthesizer 的内容大小
MAX_FINDINGS_PER_FOCUS = 10  # 每个 focus 最多保留 5 条 findings
MAX_SOURCES_PER_FOCUS = 5   # 每个 focus 最多保留 3 个 sources
MAX_TOTAL_CHARS = 20000     # 总内容最大字符数


def build_synthesizer(model: Union[AnthropicModel, DeepseekModel] = None) -> Agent:
    """Build the synthesizer agent with quality model."""
    if model is None:
        from .agent import build_model
        model = build_model("quality")  # 使用高质量模型进行最终综合
        print("[DEBUG] Synthesizer using quality model for final synthesis")

    # Use LitellmModel wrapper for agents framework compatibility
    from .config import get_litellm_model_config
    model_str, api_key = get_litellm_model_config(model.model)
    litellm_model = LitellmModel(
        model=model_str,
        api_key=api_key
    )
    return Agent(
        name="Synthesizer",
        model=litellm_model,
        instructions=SYNTHESIZER_SYSTEM_PROMPT,
        tools=[]  # Synthesizer doesn't use tools
    )


def truncate_findings(subtask_results: List[SubtaskResult]) -> Dict:
    """Truncate findings to prevent content overflow."""
    findings_dict = {}
    
    for result in subtask_results:
        # 限制 findings 数量
        truncated_findings = result.findings[:MAX_FINDINGS_PER_FOCUS]
        
        # 限制 sources 数量，并截断 snippet
        truncated_sources = []
        for src in result.sources[:MAX_SOURCES_PER_FOCUS]:
            src_dict = src.model_dump()
            # 截断 snippet
            if src_dict.get("snippet") and len(src_dict["snippet"]) > 200:
                src_dict["snippet"] = src_dict["snippet"][:200] + "..."
            truncated_sources.append(src_dict)
        
        findings_dict[result.focus] = {
            "findings": truncated_findings,
            "sources": truncated_sources,
            "confidence": result.confidence
        }
    
    return findings_dict


async def synthesize_results(
    model: Union[AnthropicModel, DeepseekModel],
    goal: str,
    research_focus: List[str],
    subtask_results: List[SubtaskResult]
) -> ResearchResult:
    """
    Synthesize results from multiple subagents.
    
    Args:
        model: LLM model for synthesis
        goal: Research goal
        research_focus: List of research focus areas
        subtask_results: Results from subagents
    
    Returns:
        Synthesized research result
    """
    # # #region synthesizer log
    # import time
    # with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
    #     f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H1_H3", "location": "synthesizer.py:entry", "message": "Synthesizer entry", "data": {"num_results": len(subtask_results), "result_focuses": [r.focus for r in subtask_results], "total_findings": sum(len(r.findings) for r in subtask_results), "total_sources": sum(len(r.sources) for r in subtask_results)}, "timestamp": time.time() * 1000}) + "\n")
    # # #endregion
    
    print(f"[DEBUG] Synthesizer entry: {len(subtask_results)} subtask results")
    synthesizer = build_synthesizer()  # 使用默认高质量模型
    
    # Prepare input data with truncation
    findings_dict = truncate_findings(subtask_results)
    print(f"[DEBUG] Synthesizer: prepared findings_dict with {len(findings_dict)} focuses")
    
    payload = {
        "goal": goal,
        "research_focus": research_focus,
        "findings": findings_dict
    }
    
    # 检查 payload 大小，如果太大则进一步截断
    payload_str = json.dumps(payload, ensure_ascii=False)
    
    # # #region synthesizer log
    # with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
    #     f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H1", "location": "synthesizer.py:before_truncate", "message": "Payload size before truncation", "data": {"payload_size": len(payload_str), "max_allowed": MAX_TOTAL_CHARS, "will_truncate": len(payload_str) > MAX_TOTAL_CHARS, "num_focuses": len(findings_dict)}, "timestamp": time.time() * 1000}) + "\n")
    # # #endregion
    
    if len(payload_str) > MAX_TOTAL_CHARS:
        print(f"[WARN] Payload too large ({len(payload_str)} chars), truncating...")
        # 进一步减少每个 focus 的 findings
        for focus in findings_dict:
            findings_dict[focus]["findings"] = findings_dict[focus]["findings"][:3]
            findings_dict[focus]["sources"] = findings_dict[focus]["sources"][:2]
        payload["findings"] = findings_dict
        payload_str = json.dumps(payload, ensure_ascii=False)
        print(f"[DEBUG] Truncated payload size: {len(payload_str)} chars")
    
    # # #region synthesizer log
    # with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
    #     f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H2", "location": "synthesizer.py:before_api_call", "message": "Before calling LLM API", "data": {"payload_size": len(payload_str), "payload_preview": payload_str[:500]}, "timestamp": time.time() * 1000}) + "\n")
    # # #endregion
    
    try:
        synthesis_start = time.time()
        print(f"[DEBUG] Synthesizer starting LLM call...")
        result = await Runner.run(synthesizer, payload_str)
        synthesis_end = time.time()
        print(f"[DEBUG] Synthesizer LLM call completed: {synthesis_end - synthesis_start:.2f}s")

        # # #region synthesizer log
        # with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
        #     f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H2_H4", "location": "synthesizer.py:after_api_call", "message": "After LLM API call", "data": {"has_result": result is not None, "has_final_output": bool(result.final_output if result else False), "final_output_preview": (result.final_output or "")[:500] if result else ""}, "timestamp": time.time() * 1000}) + "\n")
        # # #endregion

        # Directly use the markdown output (no JSON parsing needed)
        synthesis_text = (result.final_output or "").strip()

        # Remove markdown code block markers if present
        if synthesis_text.startswith("```"):
            lines = synthesis_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            synthesis_text = "\n".join(lines).strip()

        print(f"[DEBUG] Synthesizer output length: {len(synthesis_text)} chars")

        # 准备返回结果
        print(f"[DEBUG] Synthesizer: Creating ResearchResult...")
        result_obj = ResearchResult(
            goal=goal,
            research_focus=research_focus,
            findings={r.focus: r for r in subtask_results},
            synthesis=synthesis_text,
            citations=[]  # Citations are now inline in the markdown text
        )
        print(f"[DEBUG] Synthesizer: ResearchResult created successfully")
        return result_obj

    except Exception as e:
        # # #region synthesizer log
        # with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
        #     f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H4", "location": "synthesizer.py:exception", "message": "Synthesizer exception", "data": {"error_type": type(e).__name__, "error_message": str(e)}, "timestamp": time.time() * 1000}) + "\n")
        # # #endregion

        print(f"[ERROR] Synthesizer failed: {e}")
        # 返回一个基本的结果，而不是完全失败
        return ResearchResult(
            goal=goal,
            research_focus=research_focus,
            findings={r.focus: r for r in subtask_results},
            synthesis=f"综合失败: {str(e)}。以下是各研究方向的原始发现：\n\n" +
                     "\n".join([f"## {r.focus}\n\n" + "\n".join([f"- {f}" for f in r.findings[:5]]) for r in subtask_results]),
            citations=[]
        )

    # No need for citation validation - citations are embedded in the text as [[site](url)]
    return ResearchResult(
        goal=goal,
        research_focus=research_focus,
        findings={r.focus: r for r in subtask_results},
        synthesis=synthesis_text,
        citations=[]  # Citations are now inline in the markdown text
    )
