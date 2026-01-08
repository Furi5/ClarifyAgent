"""Synthesizer module for combining results from multiple subagents."""
import json
from typing import Dict, List
from agents import Agent, Runner
from agents.extensions.models.litellm_model import LitellmModel

from .schema import SubtaskResult, ResearchResult, Citation, Source
from .config import MAX_CONTENT_CHARS

# 限制传递给 Synthesizer 的内容大小
MAX_FINDINGS_PER_FOCUS = 10  # 每个 focus 最多保留 5 条 findings
MAX_SOURCES_PER_FOCUS = 5   # 每个 focus 最多保留 3 个 sources
MAX_TOTAL_CHARS = 20000     # 总内容最大字符数


SYNTHESIZER_SYSTEM_PROMPT = """\
You are an expert research report writer. Write clear, actionable research reports.

## Output Format
Output ONLY valid JSON:
{
    "synthesis": "Your report in markdown format",
    "citations": []
}

## Writing Rules

1. **NO Executive Summary** - 直接给内容，不要写执行摘要
2. **Write in Chinese** (中文)
3. **Start with the answer** - 第一段直接回答用户问题
4. **Use clear sections** - 用 ## 和 ### 分节
5. **Include specific data** - 数字、日期、名称要具体
6. **Be concise** - 简洁有力，不要废话

## Structure by Question Type

**Factual Query** (日期、定义):
→ 直接答案 + 背景说明

**Market Analysis** (市场、竞争):
→ 市场规模 → 主要玩家 → 趋势 → 策略建议

**Drug/Target Research** (药物、靶点):
→ 当前状态 → 机制 → 临床进展 → 未来方向

**Competitive Intelligence** (竞争分析):
→ 竞争格局 → 对比分析 → 差异化建议

## Example

{
    "synthesis": "## KRAS G12C 抑制剂研究进展\\n\\n目前全球有**2款**KRAS G12C抑制剂已获批上市：\\n\\n### 已上市药物\\n\\n1. **Sotorasib (Lumakras)** - 安进\\n   - 2021年5月FDA批准\\n   - 适应症：KRAS G12C突变NSCLC\\n   - 2023年销售额：约3亿美元\\n\\n2. **Adagrasib (Krazati)** - Mirati\\n   - 2022年12月FDA批准\\n   - 具有更长半衰期和CNS渗透性\\n\\n### 临床管线\\n\\n多个联合用药方案正在探索中...",
    "citations": []
}
"""


def build_synthesizer(model: LitellmModel = None) -> Agent:
    """Build the synthesizer agent with quality model."""
    if model is None:
        from .agent import build_model
        model = build_model("quality")  # 使用高质量模型进行最终综合
        print("[DEBUG] Synthesizer using quality model for final synthesis")
    
    return Agent(
        name="Synthesizer",
        model=model,
        instructions=SYNTHESIZER_SYSTEM_PROMPT,
        tools=[]  # Synthesizer doesn't use tools
    )


def _extract_json(s: str) -> dict:
    """Extract JSON from agent output, handling control characters."""
    import re
    
    s = (s or "").strip()
    
    # 移除 markdown 代码块标记
    if s.startswith("```"):
        lines = s.split("\n")
        # 移除首尾的 ``` 行
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    
    # 提取 JSON 部分
    if s.startswith("{") and s.endswith("}"):
        json_str = s
    else:
        a, b = s.find("{"), s.rfind("}")
        if a != -1 and b != -1 and b > a:
            json_str = s[a:b+1]
        else:
            raise ValueError(f"Synthesizer did not return JSON: {s[:200]}")
    
    # 尝试直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    # 清理控制字符并重试
    # 在 JSON 字符串值内部，换行符应该是 \\n 而不是实际的换行
    # 但我们需要保留转义的 \n (\\n)
    def clean_json_string(s: str) -> str:
        # 匹配 JSON 字符串值 ("..." 内的内容)
        def replace_in_string(match):
            content = match.group(1)
            # 替换未转义的控制字符
            content = content.replace('\n', '\\n')
            content = content.replace('\r', '\\r')
            content = content.replace('\t', '\\t')
            return f'"{content}"'
        
        # 简单的字符串值替换（不完美但适用于大多数情况）
        # 替换字符串内的实际换行为 \n
        result = re.sub(r'"((?:[^"\\]|\\.)*)"', replace_in_string, s)
        return result
    
    try:
        cleaned = clean_json_string(json_str)
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 最后尝试：更激进的清理
        try:
            # 移除所有控制字符（除了已转义的）
            aggressive_clean = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)
            return json.loads(aggressive_clean)
        except json.JSONDecodeError:
            raise ValueError(f"JSON parse failed: {e}. Preview: {json_str[:300]}")


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
    
    synthesizer = build_synthesizer()  # 使用默认高质量模型
    
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
        synthesis_start = time.time()
        print(f"[DEBUG] Synthesizer starting LLM call...")
        result = await Runner.run(synthesizer, payload_str)
        synthesis_end = time.time()
        print(f"[DEBUG] Synthesizer LLM call completed: {synthesis_end - synthesis_start:.2f}s")
        
        # #region synthesizer log
        with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H2_H4", "location": "synthesizer.py:after_api_call", "message": "After LLM API call", "data": {"has_result": result is not None, "has_final_output": bool(result.final_output if result else False), "final_output_preview": (result.final_output or "")[:500] if result else ""}, "timestamp": time.time() * 1000}) + "\n")
        # #endregion
        
        json_start = time.time()
        data = _extract_json(result.final_output or "")
        json_end = time.time()
        print(f"[DEBUG] Synthesizer JSON extraction: {json_end - json_start:.2f}s")
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
