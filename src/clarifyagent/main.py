import asyncio

from .agent import build_model
from .config import (
    CLARIFIER_MODEL, PLANNER_MODEL, EXECUTOR_MODEL, SYNTHESIZER_MODEL,
    MAX_PARALLEL_SUBAGENTS
)
from .dialog import SessionState, add_user, add_assistant, update_task_draft
from .orchestrator import Orchestrator
from .schema import ResearchResult
from typing import Optional


def render_plan(plan) -> str:
    """Render plan for display."""
    task = plan.task
    lines = [f"我理解你想做：**{task.goal}**", ""]
    
    # if getattr(task, "research_focus", None):
    # if task.research_focus:
        # lines.append("计划重点覆盖：")
        # for f in task.research_focus:
        #     lines.append(f"• {f}")
        # lines.append("")
    
    # if getattr(plan, "assumptions", None):
    # if plan.assumptions:
    #     lines.append("（我的假设：" + "；".join(plan.assumptions) + "）")
    #     lines.append("")
    
    lines.append(plan.confirm_prompt or "这样可以开始吗？")
    return "\n".join(lines)


def render_clarification(plan) -> str:
    """Render clarification question."""
    if not plan.clarification:
        return "请提供更多信息。"
    
    clar = plan.clarification
    lines = [clar.get("question", "请提供更多信息"), ""]
    
    if options := clar.get("options"):
        for i, opt in enumerate(options, 1):
            lines.append(f"{i}) {opt}")
    
    return "\n".join(lines)


def render_research_result(result: ResearchResult) -> str:
    """Render research result."""
    lines = [f"# 研究结果：{result.goal}", ""]
    
    if result.synthesis:
        lines.append("## 综合报告")
        lines.append(result.synthesis)
        lines.append("")
    
    if result.findings:
        lines.append("## 详细发现")
        for focus, finding in result.findings.items():
            lines.append(f"### {focus}")
            for f in finding.findings:
                lines.append(f"- {f}")
            if finding.sources:
                lines.append("\n**来源：**")
                for src in finding.sources[:3]:  # Show top 3 sources
                    lines.append(f"- [{src.title}]({src.url})")
            lines.append("")
    
    if result.citations:
        lines.append("## 引用")
        for cit in result.citations:
            lines.append(f"- {cit.text}")
            for src in cit.sources:
                lines.append(f"  - [{src.title}]({src.url})")
    
    return "\n".join(lines)


def is_confirmation(text: str) -> bool:
    """用于确认 CONFIRM_PLAN 的快捷确认。"""
    confirms = [
        "可以", "好", "ok", "OK", "开始", "行", "没问题", "就这样", "确认",
        "yes", "好的", "可以的", "go", "继续", "是的", "对", "嗯", "可以开始"
    ]
    t = text.strip().lower()
    # 避免把长句误判为确认
    return any(c.lower() in t for c in confirms) and len(t) < 20


def is_clarification_response(text: str, options: list) -> Optional[int]:
    """
    检查用户是否选择了澄清选项。
    
    Args:
        text: 用户输入
        options: 澄清选项列表
    
    Returns:
        选项索引（1-based），如果不是有效选择则返回 None
    """
    text = text.strip()
    
    # 检查数字选择（1, 2, 3...）
    try:
        choice = int(text)
        if 1 <= choice <= len(options):
            return choice
    except ValueError:
        pass
    
    # 检查文本匹配
    text_lower = text.lower()
    for i, opt in enumerate(options, 1):
        if opt.lower() in text_lower or text_lower in opt.lower():
            return i
    
    return None


async def main():
    """
    主循环：使用 Orchestrator 协调整个研究流程
    - Clarifier 评估信息充分性
    - Planner 分解任务
    - Executor 并行执行
    - Synthesizer 综合结果
    """
    # Build models for different modules
    base_model = build_model()
    clarifier_model = build_model()  # Can use different model
    planner_model = build_model()
    executor_model = build_model()
    synthesizer_model = build_model()
    
    # Create orchestrator
    orchestrator = Orchestrator(
        clarifier_model=clarifier_model,
        planner_model=planner_model,
        executor_model=executor_model,
        synthesizer_model=synthesizer_model,
        max_parallel=MAX_PARALLEL_SUBAGENTS
    )
    
    state = SessionState()
    pending_plan = None

    print("🧪 Deep Research Agent\n")

    while True:
        user = input("User> ").strip()
        if not user:
            continue
        
        # Handle confirmation
        if pending_plan and is_confirmation(user):
            add_user(state, "[用户确认] 已确认按计划执行")
            pending_plan = None
            
            # Re-run orchestrator with confirmation
            plan, research_result = await orchestrator.run(
                user_input=user,
                messages=state.messages,
                task_draft=state.task_draft
            )
            
            if research_result:
                print("\n" + render_research_result(research_result))
                add_assistant(state, render_research_result(research_result))
            continue
        
        # Normal input
        add_user(state, user)
        pending_plan = None
        
        # Run orchestrator
        plan, research_result = await orchestrator.run(
            user_input=user,
            messages=state.messages,
            task_draft=state.task_draft
        )
        
        print(f"[DEBUG] next_action: {plan.next_action}, confidence: {plan.confidence}")
        
        # Handle different actions
        if plan.next_action == "START_RESEARCH":
            print("🔍 开始研究...")
            if research_result:
                print("\n" + render_research_result(research_result))
                add_assistant(state, render_research_result(research_result))
            else:
                print("⚠️ 研究已完成，但未返回结果。")
                add_assistant(state, "研究已完成，但未返回结果。")
            update_task_draft(state, plan.task.model_dump())
            continue

        elif plan.next_action == "NEED_CLARIFICATION":
            update_task_draft(state, plan.task.model_dump())
            response = render_clarification(plan)
            print(response)
            add_assistant(state, response)
            pending_plan = plan
            
            # Wait for user clarification response
            clar_response = input("\n请选择（输入数字或选项）> ").strip()
            if clar_response:
                # Check if user selected an option
                options = plan.clarification.get("options", []) if plan.clarification else []
                choice = is_clarification_response(clar_response, options)
                
                # #region debug log
                import json, time
                with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
                    f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H1", "location": "main.py:clarification_input", "message": "User clarification input", "data": {"clar_response": clar_response, "options_count": len(options), "options": options[:3], "choice": choice}, "timestamp": time.time() * 1000}) + "\n")
                # #endregion
                
                if choice:
                    selected_option = options[choice - 1] if choice <= len(options) else clar_response
                    # Add clarification response to conversation
                    add_user(state, f"[澄清回复] {selected_option}")
                    # Update task_draft with clarification
                    if plan.clarification:
                        missing_info = plan.clarification.get("missing_info", "")
                        if missing_info == "research_topic":
                            state.task_draft["goal"] = selected_option
                        elif missing_info == "research_focus":
                            if "research_focus" not in state.task_draft:
                                state.task_draft["research_focus"] = []
                            state.task_draft["research_focus"].append(selected_option)
                    
                    # Re-run orchestrator with clarification
                    plan, research_result = await orchestrator.run(
                        user_input=selected_option,
                        messages=state.messages,
                        task_draft=state.task_draft
                    )
                    
                    # #region debug log
                    with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H2_H3", "location": "main.py:after_rerun", "message": "After orchestrator rerun", "data": {"next_action": plan.next_action, "has_research_result": research_result is not None, "confidence": plan.confidence}, "timestamp": time.time() * 1000}) + "\n")
                    # #endregion
                    
                    # Handle the new plan
                    if plan.next_action == "START_RESEARCH" and research_result:
                        print("\n" + render_research_result(research_result))
                        add_assistant(state, render_research_result(research_result))
                    elif plan.next_action == "NEED_CLARIFICATION":
                        # Still need more clarification
                        response = render_clarification(plan)
                        print(response)
                        add_assistant(state, response)
                        pending_plan = plan
                    else:
                        # #region debug log
                        with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
                            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H2", "location": "main.py:unhandled_action", "message": "Unhandled next_action after clarification", "data": {"next_action": plan.next_action, "has_research_result": research_result is not None}, "timestamp": time.time() * 1000}) + "\n")
                        # #endregion
                        print(f"[DEBUG] 未处理的状态: next_action={plan.next_action}, has_result={research_result is not None}")
                else:
                    # #region debug log
                    with open("/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log", "a") as f:
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "H1", "location": "main.py:no_choice", "message": "No valid choice detected", "data": {"clar_response": clar_response, "options": options}, "timestamp": time.time() * 1000}) + "\n")
                    # #endregion
                    print(f"[DEBUG] 未能识别选项：{clar_response}")
            continue

        elif plan.next_action == "CONFIRM_PLAN":
            update_task_draft(state, plan.task.model_dump())
            response = render_plan(plan)
            print(response)
            add_assistant(state, response)
            pending_plan = plan
            continue
            
        elif plan.next_action == "VERIFY_TOPIC":
            topic = plan.unknown_topic or "unknown"
            print(f"🔍 正在验证「{topic}」...")
            add_assistant(state, f"正在验证「{topic}」...")
            # Orchestrator already handles VERIFY_TOPIC, so we just continue
            continue
            
        elif plan.next_action == "CANNOT_DO":
            reason = plan.block.reason or "这个我暂时做不了。"
            print(reason)
            if plan.block.alternatives:
                print("我可以帮你：")
                for i, a in enumerate(plan.block.alternatives, 1):
                    print(f"  {i}) {a}")
            add_assistant(state, reason)
            continue

        # Fallback
        print(f"[WARN] 未处理的 next_action: {plan.next_action}")
        add_assistant(state, f"[WARN] 未处理的 next_action: {plan.next_action}")


if __name__ == "__main__":
    asyncio.run(main())
