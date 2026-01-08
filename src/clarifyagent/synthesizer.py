"""Synthesizer module for combining results from multiple subagents."""
import json
from typing import Dict, List
from agents import Agent, Runner
from agents.extensions.models.litellm_model import LitellmModel

from .schema import SubtaskResult, ResearchResult, Citation, Source
from .config import MAX_CONTENT_CHARS

# 限制传递给 Synthesizer 的内容大小
MAX_FINDINGS_PER_FOCUS = 5  # 每个 focus 最多保留 5 条 findings
MAX_SOURCES_PER_FOCUS = 3   # 每个 focus 最多保留 3 个 sources
MAX_TOTAL_CHARS = 20000     # 总内容最大字符数


SYNTHESIZER_SYSTEM_PROMPT = """\
You are an expert research report writer. Analyze the research goal and findings, then write a well-structured report.

## CRITICAL: Output Format
You MUST output ONLY valid JSON with this structure:
{
    "synthesis": "Your complete research report in markdown format",
    "citations": []
}

## Report Writing Guidelines

### 1. FIRST: Identify the Question Type
Based on the goal, determine what kind of report structure fits best:

**Factual Query** (dates, approvals, definitions):
→ Lead with the direct answer, then provide context

**Market Analysis** (competition, market size, trends):
→ Use data-driven sections: market overview, key players, trends, outlook

**Drug/Target Research** (mechanism, pipeline, trials):
→ Scientific structure: background, mechanism, current status, future directions

**Comparison/Competitive Intelligence**:
→ Use comparison format, highlight differences

**General Research**:
→ Executive summary, key findings by topic, conclusion

### 2. Write the Report
- Write in **Chinese** (中文)
- Use markdown formatting in the synthesis field
- Structure should match the question type
- Be concise but comprehensive
- Include specific data points (numbers, dates, names)
- DO NOT just list bullet points - write coherent paragraphs

### 3. Quality Standards
- Answer the actual question directly
- Synthesize, don't just concatenate findings
- Resolve conflicting information
- Prioritize authoritative sources
- Include specific facts and figures

## Example Output

For a drug approval query:
{
    "synthesis": "## Keytruda 美国首次获批信息\\n\\nKeytruda (pembrolizumab) 于 **2014年9月4日** 获得美国FDA首次批准。\\n\\n### 首批适应症\\n\\n首次获批的适应症为**不可切除或转移性黑色素瘤**，用于经ipilimumab治疗后疾病进展的患者...\\n\\n### 审批背景\\n\\n该批准基于KEYNOTE-001临床试验数据...",
    "citations": []
}

For a market analysis:
{
    "synthesis": "## GLP-1激动剂市场竞争格局\\n\\n### 市场概览\\n\\n全球GLP-1激动剂市场规模在2023年达到约**420亿美元**，预计到2030年将超过1000亿美元。\\n\\n### 主要竞争者\\n\\n1. **诺和诺德** - 市场领导者\\n   - Ozempic/Wegovy：2023年销售额约210亿美元\\n   - 在减重适应症领域占据主导地位\\n\\n2. **礼来**\\n   - Mounjaro/Zepbound：快速增长...",
    "citations": []
}

Remember: The synthesis should be a COMPLETE, READABLE REPORT, not just bullet points or raw findings.
"""


def build_synthesizer(model: LitellmModel) -> Agent:
    """Build the synthesizer agent."""
    return Agent(
        name="Synthesizer",
        model=model,
        instructions=SYNTHESIZER_SYSTEM_PROMPT,
        tools=[]  # Synthesizer doesn't use tools
    )


def _extract_json(s: str) -> dict:
    """Extract JSON from agent output."""
    s = (s or "").strip()
    if s.startswith("{") and s.endswith("}"):
        return json.loads(s)
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        return json.loads(s[a:b+1])
    raise ValueError(f"Synthesizer did not return JSON: {s[:200]}")


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
    model: LitellmModel,
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
    # #region synthesizer log
    import time
    with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H1_H3", "location": "synthesizer.py:entry", "message": "Synthesizer entry", "data": {"num_results": len(subtask_results), "result_focuses": [r.focus for r in subtask_results], "total_findings": sum(len(r.findings) for r in subtask_results), "total_sources": sum(len(r.sources) for r in subtask_results)}, "timestamp": time.time() * 1000}) + "\n")
    # #endregion
    
    synthesizer = build_synthesizer(model)
    
    # Prepare input data with truncation
    findings_dict = truncate_findings(subtask_results)
    
    payload = {
        "goal": goal,
        "research_focus": research_focus,
        "findings": findings_dict
    }
    
    # 检查 payload 大小，如果太大则进一步截断
    payload_str = json.dumps(payload, ensure_ascii=False)
    
    # #region synthesizer log
    with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H1", "location": "synthesizer.py:before_truncate", "message": "Payload size before truncation", "data": {"payload_size": len(payload_str), "max_allowed": MAX_TOTAL_CHARS, "will_truncate": len(payload_str) > MAX_TOTAL_CHARS, "num_focuses": len(findings_dict)}, "timestamp": time.time() * 1000}) + "\n")
    # #endregion
    
    if len(payload_str) > MAX_TOTAL_CHARS:
        print(f"[WARN] Payload too large ({len(payload_str)} chars), truncating...")
        # 进一步减少每个 focus 的 findings
        for focus in findings_dict:
            findings_dict[focus]["findings"] = findings_dict[focus]["findings"][:3]
            findings_dict[focus]["sources"] = findings_dict[focus]["sources"][:2]
        payload["findings"] = findings_dict
        payload_str = json.dumps(payload, ensure_ascii=False)
        print(f"[DEBUG] Truncated payload size: {len(payload_str)} chars")
    
    # #region synthesizer log
    with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H2", "location": "synthesizer.py:before_api_call", "message": "Before calling LLM API", "data": {"payload_size": len(payload_str), "payload_preview": payload_str[:500]}, "timestamp": time.time() * 1000}) + "\n")
    # #endregion
    
    try:
        result = await Runner.run(synthesizer, payload_str)
        
        # #region synthesizer log
        with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H2_H4", "location": "synthesizer.py:after_api_call", "message": "After LLM API call", "data": {"has_result": result is not None, "has_final_output": bool(result.final_output if result else False), "final_output_preview": (result.final_output or "")[:500] if result else ""}, "timestamp": time.time() * 1000}) + "\n")
        # #endregion
        
        data = _extract_json(result.final_output or "")
    except Exception as e:
        # #region synthesizer log
        with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H4", "location": "synthesizer.py:exception", "message": "Synthesizer exception", "data": {"error_type": type(e).__name__, "error_message": str(e)}, "timestamp": time.time() * 1000}) + "\n")
        # #endregion
        
        print(f"[ERROR] Synthesizer failed: {e}")
        # 返回一个基本的结果，而不是完全失败
        return ResearchResult(
            goal=goal,
            research_focus=research_focus,
            findings={r.focus: r for r in subtask_results},
            synthesis=f"综合失败: {str(e)}。以下是各研究方向的原始发现：\n" + 
                     "\n".join([f"- {r.focus}: {', '.join(r.findings[:3])}" for r in subtask_results]),
            citations=[]
        )
    
    # Convert citations
    citations = []
    for cit_data in data.get("citations", []):
        sources = [
            Source(**src) for src in cit_data.get("sources", [])
        ]
        citations.append(Citation(
            text=cit_data.get("text", ""),
            sources=sources
        ))
    
    return ResearchResult(
        goal=goal,
        research_focus=research_focus,
        findings={r.focus: r for r in subtask_results},
        synthesis=data.get("synthesis", ""),
        citations=citations
    )
