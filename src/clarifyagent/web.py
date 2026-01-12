"""Web API for ClarifyAgent - Deep Research Platform."""
import asyncio
import json
import uuid
from typing import Optional, AsyncGenerator
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel
import logging

from .agent import build_model
from .config import MAX_PARALLEL_SUBAGENTS
from .orchestrator import Orchestrator
from .dialog import SessionState, add_user, add_assistant, update_task_draft, save_research_result, is_simple_followup, is_new_research_task, start_new_research_session
from .schema import ResearchResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ClarifyAgent",
    description="Deep Research Platform with Intelligent Clarification",
    version="1.0.0"
)

# Session storage (in-memory for demo)
sessions: dict[str, dict] = {}


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    response_type: str  # "clarification" | "research_result" | "confirm_plan" | "quick_answer" | "error"
    message: str
    options: Optional[list[str]] = None
    research_result: Optional[dict] = None
    next_action: Optional[str] = None


def get_or_create_session(session_id: Optional[str]) -> tuple[str, dict]:
    """Get existing session or create new one."""
    if session_id and session_id in sessions:
        return session_id, sessions[session_id]
    
    new_id = str(uuid.uuid4())[:8]
    sessions[new_id] = {
        "state": SessionState(),
        "pending_plan": None,
        "orchestrator": None
    }
    return new_id, sessions[new_id]


def create_orchestrator() -> Orchestrator:
    """Create a new orchestrator instance with different models for different purposes."""
    return Orchestrator(
        clarifier_model=build_model("clarifier"),
        planner_model=build_model("planner"),
        executor_model=build_model("executor"),
        synthesizer_model=build_model("synthesizer"),
        max_parallel=MAX_PARALLEL_SUBAGENTS
    )


def render_clarification(plan) -> tuple[str, list[str]]:
    """Render clarification question and options."""
    if not plan.clarification:
        return "请提供更多信息。", []
    
    clar = plan.clarification
    question = clar.get("question", "请提供更多信息")
    options = clar.get("options", [])
    
    return question, options


def render_plan(plan, subtasks=None) -> str:
    """
    Render plan for confirmation.

    Args:
        plan: Plan object from Clarifier
        subtasks: Optional list of Subtask objects from Planner
    """
    task = plan.task
    lines = [f"我理解你想做：**{task.goal}**", ""]
    
    # if getattr(task, "research_focus", None) and task.research_focus:
    #     lines.append("计划重点覆盖：")
    #     for f in task.research_focus:
    #         lines.append(f"• {f}")
    #     lines.append("")

    # if getattr(plan, "assumptions", None) and plan.assumptions:
    #     lines.append("*我的假设：" + "；".join(plan.assumptions) + "*")
    #     lines.append("")

    # lines.append("---")
    # lines.append("")
    lines.append(plan.confirm_prompt or "✅ 确认开始研究？")
    lines.append("")
    # lines.append("💡 提示：如需修改计划，请直接描述您的需求")

    return "\n".join(lines)

# ============== 修改 web.py 中的 render_research_result 函数 ==============
# 将下面的函数替换 web.py 中原来的 render_research_result 函数 (约第 101-139 行)

from urllib.parse import urlparse

def is_valid_url(url: str) -> bool:
    """检查是否是有效的 URL 格式"""
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    if not url:
        return False
    
    # 基本格式检查
    if not url.startswith(('http://', 'https://')):
        return False
    
    try:
        parsed = urlparse(url)
        # 必须有 scheme 和 netloc
        if not parsed.scheme or not parsed.netloc:
            return False
        # netloc 必须包含至少一个点（域名）
        if '.' not in parsed.netloc:
            return False
        return True
    except Exception:
        return False


def render_research_result(result: ResearchResult) -> dict:
    """
    Render research result as structured data.
    增强版：更严格的 URL 验证
    """
    # Findings sources come from subtask_results (search results), so they should be valid
    # Citations sources are already validated in synthesizer
    # We add extra validation here as a safety net
    
    filtered_findings = {}
    if result.findings:
        for focus, finding in result.findings.items():
            # 严格过滤：只保留有效 URL 格式的 sources
            valid_sources = []
            for s in finding.sources[:3]:
                if is_valid_url(s.url):
                    valid_sources.append(s)
                else:
                    print(f"[WARN] render_research_result: Filtering invalid URL in findings: {s.url[:100] if s.url else 'None'}")
            
            filtered_findings[focus] = {
                "findings": finding.findings[:5],
                "sources": [
                    {
                        "title": s.title or "Unknown",
                        "url": s.url,
                        "snippet": (s.snippet[:200] if s.snippet else "") if s.snippet else ""
                    }
                    for s in valid_sources
                ],
                "confidence": finding.confidence
            }
    
    # Citations are already validated in synthesizer to only include valid URLs
    # But we double-check to ensure URLs are valid format
    filtered_citations = []
    for cit in result.citations[:10]:
        # 严格过滤：只保留有效 URL 格式的 sources
        valid_cit_sources = []
        for s in cit.sources:
            if is_valid_url(s.url):
                valid_cit_sources.append(s)
            else:
                print(f"[WARN] render_research_result: Filtering invalid URL in citations: {s.url[:100] if s.url else 'None'}")
        
        if valid_cit_sources:  # Only add citation if it has at least one valid source
            filtered_citations.append({
                "text": cit.text,
                "sources": [{"title": s.title or "Unknown", "url": s.url} for s in valid_cit_sources]
            })
    
    return {
        "goal": result.goal,
        "synthesis": result.synthesis,
        "research_focus": result.research_focus,
        "findings": filtered_findings,
        "citations": filtered_citations
    }



def is_confirmation(text: str) -> bool:
    """Check if text is a confirmation."""
    confirms = [
        "可以", "好", "ok", "OK", "开始", "行", "没问题", "就这样", "确认",
        "yes", "好的", "可以的", "go", "继续", "是的", "对", "嗯", "可以开始"
    ]
    t = text.strip().lower()
    return any(c.lower() in t for c in confirms) and len(t) < 20


def is_option_selection(text: str, options: list) -> Optional[int]:
    """Check if text is an option selection."""
    text = text.strip()
    try:
        choice = int(text)
        if 1 <= choice <= len(options):
            return choice
    except ValueError:
        pass
    
    text_lower = text.lower()
    for i, opt in enumerate(options, 1):
        if opt.lower() in text_lower or text_lower in opt.lower():
            return i
    return None


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    return FileResponse("src/clarifyagent/static/index.html")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Handle chat messages."""
    session_id, session = get_or_create_session(request.session_id)
    state = session["state"]
    pending_plan = session["pending_plan"]
    
    # Create orchestrator if needed
    if session["orchestrator"] is None:
        session["orchestrator"] = create_orchestrator()
    orchestrator = session["orchestrator"]
    
    user_message = request.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    try:
        # Handle confirmation for pending plan
        if pending_plan and is_confirmation(user_message):
            add_user(state, "[用户确认] 已确认按计划执行")
            session["pending_plan"] = None
            
            plan, research_result = await orchestrator.run(
                user_input=user_message,
                messages=state.messages,
                task_draft=state.task_draft
            )
            
            if research_result:
                add_assistant(state, f"研究完成：{research_result.goal}")
                return ChatResponse(
                    session_id=session_id,
                    response_type="research_result",
                    message="研究完成！",
                    research_result=render_research_result(research_result),
                    confidence=plan.confidence,
                    next_action=plan.next_action
                )
            else:
                return ChatResponse(
                    session_id=session_id,
                    response_type="error",
                    message="研究已完成，但未返回结果。"
                )
        
        # Handle option selection for clarification
        if pending_plan and pending_plan.clarification:
            options = pending_plan.clarification.get("options", [])
            choice = is_option_selection(user_message, options)
            if choice:
                selected_option = options[choice - 1]
                add_user(state, f"[澄清回复] {selected_option}")
                
                # Update task draft
                missing_info = pending_plan.clarification.get("missing_info", "")
                if missing_info == "research_topic":
                    state.task_draft["goal"] = selected_option
                elif missing_info == "research_focus":
                    if "research_focus" not in state.task_draft:
                        state.task_draft["research_focus"] = []
                    state.task_draft["research_focus"].append(selected_option)
                
                session["pending_plan"] = None
                user_message = selected_option
        
        # Normal input processing
        add_user(state, user_message)
        
        plan, research_result = await orchestrator.run(
            user_input=user_message,
            messages=state.messages,
            task_draft=state.task_draft
        )
        
        logger.info(f"[API] next_action: {plan.next_action}, confidence: {plan.confidence}")
        
        # Handle different actions
        if plan.next_action == "START_RESEARCH":
            if research_result:
                add_assistant(state, f"研究完成：{research_result.goal}")
                update_task_draft(state, plan.task.model_dump())
                return ChatResponse(
                    session_id=session_id,
                    response_type="research_result",
                    message="🔍 研究完成！",
                    research_result=render_research_result(research_result),
                    confidence=plan.confidence,
                    next_action=plan.next_action
                )
            else:
                return ChatResponse(
                    session_id=session_id,
                    response_type="error",
                    message="研究已启动但未返回结果。",
                    confidence=plan.confidence,
                    next_action=plan.next_action
                )
        
        elif plan.next_action == "NEED_CLARIFICATION":
            update_task_draft(state, plan.task.model_dump())
            question, options = render_clarification(plan)
            add_assistant(state, question)
            session["pending_plan"] = plan
            
            return ChatResponse(
                session_id=session_id,
                response_type="clarification",
                message=question,
                options=options,
                confidence=plan.confidence,
                next_action=plan.next_action
            )
        
        elif plan.next_action == "CONFIRM_PLAN":
            update_task_draft(state, plan.task.model_dump())
            message = render_plan(plan)
            add_assistant(state, message)
            session["pending_plan"] = plan
            
            return ChatResponse(
                session_id=session_id,
                response_type="confirm_plan",
                message=message,
                confidence=plan.confidence,
                next_action=plan.next_action
            )
        
        elif plan.next_action == "VERIFY_TOPIC":
            topic = plan.unknown_topic or "unknown"
            message = f"🔍 正在验证「{topic}」..."
            add_assistant(state, message)
            
            return ChatResponse(
                session_id=session_id,
                response_type="verifying",
                message=message,
                confidence=plan.confidence,
                next_action=plan.next_action
            )
        
        elif plan.next_action == "CANNOT_DO":
            reason = plan.block.reason if plan.block else "这个我暂时做不了。"
            alternatives = plan.block.alternatives if plan.block else []
            message = reason
            if alternatives:
                message += "\n\n我可以帮你：\n" + "\n".join([f"• {a}" for a in alternatives])
            add_assistant(state, message)
            
            return ChatResponse(
                session_id=session_id,
                response_type="cannot_do",
                message=message,
                options=alternatives,
                confidence=plan.confidence,
                next_action=plan.next_action
            )
        
        # Fallback
        return ChatResponse(
            session_id=session_id,
            response_type="error",
            message=f"未处理的状态: {plan.next_action}",
            confidence=plan.confidence,
            next_action=plan.next_action
        )
    
    except Exception as e:
        logger.exception(f"Error processing chat: {e}")
        return ChatResponse(
            session_id=session_id,
            response_type="error",
            message=f"处理出错: {str(e)}"
        )


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Get session info."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    return {
        "session_id": session_id,
        "message_count": len(session["state"].messages),
        "has_pending_plan": session["pending_plan"] is not None
    }


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a session."""
    if session_id in sessions:
        del sessions[session_id]
    return {"status": "ok"}


async def stream_generator(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """Generate SSE events for streaming responses."""
    # #region agent log
    import json as json_lib
    log_path = "/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "SESSION_ENTRY",
                "location": "web.py:stream_generator_entry",
                "message": "stream_generator entry - checking session_id",
                "data": {
                    "incoming_session_id": session_id,
                    "message_preview": message[:100] if message else "",
                    "sessions_keys": list(sessions.keys()),
                },
                "timestamp": int(__import__("time").time() * 1000)
            }, ensure_ascii=False) + "\n")
    except: pass
    # #endregion
    
    session_id, session = get_or_create_session(session_id if session_id != "new" else None)
    state = session["state"]
    pending_plan = session["pending_plan"]
    
    # #region agent log
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json_lib.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "SESSION_AFTER",
                "location": "web.py:stream_generator_after_session",
                "message": "session retrieved/created",
                "data": {
                    "final_session_id": session_id,
                    "messages_count": len(state.messages),
                    "task_draft_keys": list(state.task_draft.keys()),
                    "has_pending_plan": pending_plan is not None,
                },
                "timestamp": int(__import__("time").time() * 1000)
            }, ensure_ascii=False) + "\n")
    except: pass
    # #endregion
    
    # Send session ID first
    yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

    # Import dependencies at the beginning so all branches can access them
    from .clarifier import assess_input
    from .planner import decompose_task
    from .executor import Executor
    from .synthesizer import synthesize_results
    from .schema import Subtask
    from .agent import build_model

    try:
        user_message = message.strip()
        if not user_message:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Message cannot be empty'})}\n\n"
            return
        
        # 检查是否是新的调研任务（在chat模式下）
        if state.conversation_mode == "chat" and is_new_research_task(user_message, state):
            print(f"[DEBUG] Detected new research task in chat mode, starting new research session")
            start_new_research_session(state)
            # 给用户一个提示，表明开始新的研究
            yield f"data: {json.dumps({'type': 'progress', 'stage': 'new_research', 'message': '开始新的调研任务', 'detail': f'检测到新调研需求，已保存之前的研究结果'})}\n\n"
            await asyncio.sleep(0.1)
            # 继续执行完整研究流程
        
        # 检查是否是简单后续对话
        elif is_simple_followup(user_message, state):
            print(f"[DEBUG] Detected simple followup, using chat mode")
            add_user(state, user_message)
            
            try:
                chat_response = await handle_simple_chat(state, user_message)
                add_assistant(state, chat_response)
                save_research_result(state, state.last_research_result)  # 保持聊天模式
                yield f"data: {json.dumps({'type': 'result', 'response_type': 'simple_chat', 'message': chat_response})}\n\n"
                return
            except Exception as e:
                print(f"[ERROR] Simple chat failed: {e}")
                # 降级到完整研究模式
                pass
        
        # Handle plan modification request
        if pending_plan and (user_message.startswith("修改计划:") or user_message.startswith("修改计划：")):
            modification = user_message.split(":", 1)[1].strip() if ":" in user_message else user_message.split("：", 1)[1].strip()
            add_user(state, f"[修改计划] {modification}")
            session["pending_plan"] = None
            
            # Add modification to task draft context
            if "modification_notes" not in state.task_draft:
                state.task_draft["modification_notes"] = []
            state.task_draft["modification_notes"].append(modification)
            
            # Continue to re-assess with modification
            user_message = modification
        
        # Handle confirmation for pending plan
        elif pending_plan and is_confirmation(user_message):
            add_user(state, user_message)  # 保留用户的实际输入，如"确认开始研究"

            # 使用已保存的 subtasks（如果有）
            planned_subtasks = session.get("planned_subtasks")

            session["pending_plan"] = None
            session["planned_subtasks"] = None  # 清除已使用的计划

            yield f"data: {json.dumps({'type': 'progress', 'stage': 'executing', 'message': '开始执行研究...', 'detail': '按计划进行深入调研'})}\n\n"
            await asyncio.sleep(0.1)

            # 构建 model（确认分支中需要）
            model = build_model()

            # 如果有预先规划的 subtasks，直接使用它们执行
            if planned_subtasks and len(planned_subtasks) > 0:
                try:
                    # Step 3: 直接执行已规划的 subtasks
                    focus_preview = ', '.join([s.focus[:20] for s in planned_subtasks[:3]]) + ('...' if len(planned_subtasks) > 3 else '')
                    yield f"data: {json.dumps({'type': 'progress', 'stage': 'searching', 'message': f'检索信息 ({len(planned_subtasks)} 个方向)', 'detail': f'正在并行检索：{focus_preview}'})}\n\n"
                    await asyncio.sleep(0.1)

                    executor = Executor(model, max_parallel=len(planned_subtasks))

                    # 并行执行
                    import time
                    from .tools.concurrency_manager import run_concurrent_tasks

                    parallel_start = time.time()
                    tasks = [executor.execute_single(subtask) for subtask in planned_subtasks]
                    results = await run_concurrent_tasks(tasks)
                    parallel_end = time.time()

                    print(f"[DEBUG] Executed planned subtasks: {parallel_end - parallel_start:.2f}s")

                    subtask_results = [r for r in results if r is not None and not isinstance(r, Exception)]

                    yield f"data: {json.dumps({'type': 'progress', 'stage': 'searching', 'message': f'检索完成 ({len(subtask_results)}/{len(planned_subtasks)})', 'detail': f'已获取 {len(subtask_results)} 个研究方向的信息'})}\n\n"
                    await asyncio.sleep(0.1)

                    if not subtask_results:
                        yield f"data: {json.dumps({'type': 'error', 'message': '检索失败，未获取到结果'})}\n\n"
                        return

                    # Step 4: Synthesizer
                    yield f"data: {json.dumps({'type': 'progress', 'stage': 'synthesizing', 'message': '整合分析结果', 'detail': f'正在综合分析 {len(subtask_results)} 个研究方向的信息'})}\n\n"
                    await asyncio.sleep(0.1)

                    research_result = await synthesize_results(
                        model,
                        pending_plan.task.goal,
                        pending_plan.task.research_focus,
                        subtask_results
                    )

                    yield f"data: {json.dumps({'type': 'progress', 'stage': 'complete', 'message': '研究完成', 'detail': '研究报告已生成'})}\n\n"

                    add_assistant(state, f"研究完成：{research_result.goal}")
                    update_task_draft(state, pending_plan.task.model_dump())
                    save_research_result(state, render_research_result(research_result))

                    yield f"data: {json.dumps({'type': 'result', 'response_type': 'research_result', 'message': '研究完成！', 'research_result': render_research_result(research_result)})}\n\n"
                    return

                except Exception as e:
                    logger.exception(f"Execution error: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'message': f'执行出错: {str(e)}'})}\n\n"
                    return

            # 否则，使用 Orchestrator 完整流程
            else:
                orchestrator = create_orchestrator()
                plan, research_result = await orchestrator.run(
                    user_input=user_message,
                    messages=state.messages,
                    task_draft=state.task_draft
                )

                if research_result:
                    add_assistant(state, f"研究完成：{research_result.goal}")
                    yield f"data: {json.dumps({'type': 'result', 'response_type': 'research_result', 'message': '研究完成！', 'research_result': render_research_result(research_result)})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': '研究已完成，但未返回结果。'})}\n\n"
            return
        
        # Handle clarification response (options or open-ended)
        # 注意：只有在不是确认的情况下才处理澄清回复
        if pending_plan and pending_plan.clarification and not is_confirmation(user_message):
            options = pending_plan.clarification.get("options", [])
            missing_info = pending_plan.clarification.get("missing_info", "")
            is_open_ended = pending_plan.clarification.get("open_ended", False) or not options
            
            # #region agent log
            import json as json_lib
            import os
            log_path = "/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log"
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json_lib.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "F",
                        "location": "web.py:409",
                        "message": "clarification response detected",
                        "data": {
                            "user_message": user_message,
                            "missing_info": missing_info,
                            "is_open_ended": is_open_ended,
                            "task_draft_before": dict(state.task_draft),
                        },
                        "timestamp": int(__import__("time").time() * 1000)
                    }, ensure_ascii=False) + "\n")
            except: pass
            # #endregion
            
            if is_open_ended:
                # 开放式问题：用户直接输入信息
                # 将用户回答与原始问题关联，更新到 task_draft
                add_user(state, user_message)  # 保留用户的原始输入，不添加标签
                
                if missing_info in ("pipeline_details", "project_details"):
                    # 解析用户提供的项目/产品信息，补充到 task_draft
                    state.task_draft["project_info"] = user_message
                    # 尝试从用户回答中提取关键信息
                    original_goal = state.task_draft.get("goal", "")
                    state.task_draft["goal"] = f"{original_goal}（{user_message}）"
                elif missing_info == "research_topic":
                    state.task_draft["goal"] = user_message
                else:
                    # 通用处理：将用户回答添加到上下文
                    if "clarification_responses" not in state.task_draft:
                        state.task_draft["clarification_responses"] = []
                    state.task_draft["clarification_responses"].append({
                        "question": pending_plan.clarification.get("question", ""),
                        "answer": user_message
                    })
                
                # #region agent log
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(json_lib.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "G",
                            "location": "web.py:440",
                            "message": "task_draft updated after open-ended answer",
                            "data": {
                                "task_draft_after": dict(state.task_draft),
                                "project_info": state.task_draft.get("project_info", ""),
                                "goal": state.task_draft.get("goal", ""),
                            },
                            "timestamp": int(__import__("time").time() * 1000)
                        }, ensure_ascii=False) + "\n")
                except: pass
                # #endregion
                
                session["pending_plan"] = None
                # 不改变 user_message，让它包含完整的用户输入
                # 注意：已经在上面 add_user 了，不需要再次添加
                skip_add_user = True
                
            else:
                # 选项式问题
                choice = is_option_selection(user_message, options)
                if choice:
                    selected_option = options[choice - 1]
                    add_user(state, selected_option)  # 保留用户的原始选择，不添加标签
                    
                    if missing_info == "research_topic":
                        state.task_draft["goal"] = selected_option
                    elif missing_info == "research_focus":
                        if "research_focus" not in state.task_draft:
                            state.task_draft["research_focus"] = []
                        state.task_draft["research_focus"].append(selected_option)
                    
                    session["pending_plan"] = None
                    user_message = selected_option
                    # 注意：已经在上面 add_user 了，不需要再次添加
                    skip_add_user = True
                else:
                    skip_add_user = False
        else:
            skip_add_user = False
        
        # Normal input processing (only if not already added above)
        if not skip_add_user:
            add_user(state, user_message)
        
        # Step 1: Clarifier - 分析研究需求
        yield f"data: {json.dumps({'type': 'progress', 'stage': 'clarifying', 'message': '分析研究需求', 'detail': '正在理解您的问题背景和目标'})}\n\n"
        await asyncio.sleep(0.1)  # Let the event flush

        model = build_model()
        
        # #region agent log
        import json as json_lib
        import os
        log_path = "/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json_lib.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "H",
                    "location": "web.py:515",
                    "message": "before assess_input call",
                    "data": {
                        "user_message": user_message,
                        "messages_count": len(state.messages),
                        "task_draft": dict(state.task_draft),
                        "task_draft_goal": state.task_draft.get("goal", ""),
                        "task_draft_project_info": state.task_draft.get("project_info", ""),
                    },
                    "timestamp": int(__import__("time").time() * 1000)
                }, ensure_ascii=False) + "\n")
        except: pass
        # #endregion
        
        # Step 1: Clarifier
        plan = await assess_input(model, state.messages, state.task_draft)
        
        logger.info(f"[API Stream] next_action: {plan.next_action}")
        
        # Handle different actions
        if plan.next_action == "NEED_CLARIFICATION":
            update_task_draft(state, plan.task.model_dump())
            question, options = render_clarification(plan)
            add_assistant(state, question)
            session["pending_plan"] = plan
            
            yield f"data: {json.dumps({'type': 'result', 'response_type': 'clarification', 'message': question, 'options': options})}\n\n"
        
        elif plan.next_action == "CONFIRM_PLAN":
            update_task_draft(state, plan.task.model_dump())

            # 在确认阶段调用 Planner 生成详细计划
            yield f"data: {json.dumps({'type': 'progress', 'stage': 'planning', 'message': '规划研究方向...', 'detail': '正在制定详细的研究计划'})}\n\n"
            await asyncio.sleep(0.1)

            try:
                subtasks = await decompose_task(model, plan.task)

                if not subtasks:
                    # Fallback: 从 research_focus 创建基本 subtasks
                    from .schema import Subtask
                    subtasks = [
                        Subtask(
                            id=i + 1,
                            focus=focus,
                            queries=[f"{plan.task.goal} {focus}"],
                            parallel=True
                        )
                        for i, focus in enumerate(plan.task.research_focus[:3])
                    ]

                # 保存 subtasks 到 session
                session["planned_subtasks"] = subtasks

                # 渲染详细计划
                msg = render_plan(plan, subtasks=subtasks)
                add_assistant(state, msg)
                session["pending_plan"] = plan

                yield f"data: {json.dumps({'type': 'result', 'response_type': 'confirm_plan', 'message': msg})}\n\n"

            except Exception as e:
                logger.exception(f"Planning error: {e}")
                # 降级：不展示详细计划
                msg = render_plan(plan)
                add_assistant(state, msg)
                session["pending_plan"] = plan
                yield f"data: {json.dumps({'type': 'result', 'response_type': 'confirm_plan', 'message': msg})}\n\n"
        
        elif plan.next_action == "CANNOT_DO":
            reason = plan.block.reason if plan.block else "这个我暂时做不了。"
            alternatives = plan.block.alternatives if plan.block else []
            msg = reason
            if alternatives:
                msg += "\n\n我可以帮你：\n" + "\n".join([f"• {a}" for a in alternatives])
            add_assistant(state, msg)
            
            yield f"data: {json.dumps({'type': 'result', 'response_type': 'cannot_do', 'message': msg, 'options': alternatives})}\n\n"
        
        elif plan.next_action == "START_RESEARCH":
            try:
                # Step 2: Planner - 分析需要研究哪些方面
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'planning', 'message': '规划研究方向', 'detail': f'正在分解研究任务：{plan.task.goal}'})}\n\n"
                await asyncio.sleep(0.1)
                
                subtasks = await decompose_task(model, plan.task)
                
                logger.info(f"[Planner] Created {len(subtasks)} subtasks")
                
                if not subtasks:
                    # Fallback: create from research_focus
                    subtasks = [
                        Subtask(
                            id=i + 1,
                            focus=focus,
                            queries=[f"{plan.task.goal} {focus}"],
                            parallel=True
                        )
                        for i, focus in enumerate(plan.task.research_focus[:3])
                    ]
                
                if not subtasks:
                    yield f"data: {json.dumps({'type': 'error', 'message': '无法创建研究计划'})}\n\n"
                    return
                
                # 显示研究方向
                focus_list = [s.focus for s in subtasks]
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'planning', 'message': f'已规划 {len(subtasks)} 个研究方向', 'detail': ', '.join(focus_list[:3]) + ('...' if len(focus_list) > 3 else '')})}\n\n"
                await asyncio.sleep(0.1)
                
                # Step 3: Executor - 并行执行所有子任务
                focus_preview = ', '.join([s.focus[:20] for s in subtasks[:3]]) + ('...' if len(subtasks) > 3 else '')
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'searching', 'message': f'检索信息 ({len(subtasks)} 个方向)', 'detail': f'正在并行检索：{focus_preview}'})}\n\n"
                await asyncio.sleep(0.1)
                
                executor = Executor(model, max_parallel=len(subtasks))
                
                # 并行执行所有子任务 - 使用智能并发控制
                import asyncio as aio
                import time
                from .tools.concurrency_manager import run_concurrent_tasks
                
                parallel_start = time.time()
                print(f"[DEBUG] Starting intelligent parallel execution of {len(subtasks)} subtasks...")
                
                # 创建任务列表
                tasks = [executor.execute_single(subtask) for subtask in subtasks]
                
                # 使用智能并发控制执行
                results = await run_concurrent_tasks(tasks)
                
                parallel_end = time.time()
                print(f"[DEBUG] Intelligent parallel execution completed: {parallel_end - parallel_start:.2f}s")
                
                # 过滤有效结果
                subtask_results = [r for r in results if r is not None and not isinstance(r, Exception)]
                
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'searching', 'message': f'检索完成 ({len(subtask_results)}/{len(subtasks)})', 'detail': f'已获取 {len(subtask_results)} 个研究方向的信息'})}\n\n"
                await asyncio.sleep(0.1)
                
                if not subtask_results:
                    yield f"data: {json.dumps({'type': 'error', 'message': '检索失败，未获取到结果'})}\n\n"
                    return
                
                # Step 4: Synthesizer
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'synthesizing', 'message': '整合分析结果', 'detail': f'正在综合分析 {len(subtask_results)} 个研究方向的信息，生成研究报告'})}\n\n"
                await asyncio.sleep(0.1)
                
                # #region debug log - before synthesize
                import json as json_lib
                import time
                log_path = "/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log"
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(json_lib.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "A,B,C,D,E", "location": "web.py:before_synthesize", "message": "About to call synthesize_results", "data": {"num_subtask_results": len(subtask_results), "goal": plan.task.goal, "research_focus": plan.task.research_focus}, "timestamp": time.time() * 1000}, ensure_ascii=False) + "\n")
                except Exception as e:
                    print(f"[DEBUG] Failed to write log in web.py: {e}")
                # #endregion
                
                research_result = await synthesize_results(
                    model,
                    plan.task.goal,
                    plan.task.research_focus,
                    subtask_results
                )
                
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'complete', 'message': '研究完成', 'detail': '研究报告已生成'})}\n\n"
                await asyncio.sleep(0.1)
                
                add_assistant(state, f"研究完成：{research_result.goal}")
                update_task_draft(state, plan.task.model_dump())
                save_research_result(state, render_research_result(research_result))  # 保存研究结果以便后续对话
                yield f"data: {json.dumps({'type': 'result', 'response_type': 'research_result', 'message': '研究完成！', 'research_result': render_research_result(research_result)})}\n\n"
                
            except Exception as e:
                logger.exception(f"Research error: {e}")
                yield f"data: {json.dumps({'type': 'error', 'message': f'研究执行出错: {str(e)}'})}\n\n"
        
        else:
            yield f"data: {json.dumps({'type': 'error', 'message': f'未处理的状态: {plan.next_action}'})}\n\n"
    
    except Exception as e:
        logger.exception(f"Error in stream: {e}")
        yield f"data: {json.dumps({'type': 'error', 'message': f'处理出错: {str(e)}'})}\n\n"
    
    finally:
        yield "data: {\"type\": \"done\"}\n\n"


async def handle_simple_chat(state: SessionState, message: str) -> str:
    """处理简单的后续对话"""
    # 使用简单的Agent进行对话
    from .agent import build_model
    
    model = build_model("fast")
    
    # 构建上下文：最近几轮对话 + 研究结果摘要
    context_messages = state.messages[-6:]  # 最近3轮对话
    
    context = "基于之前的研究：\n"
    if state.last_research_result.get("synthesis"):
        context += state.last_research_result["synthesis"][:500] + "...\n\n"
    
    context += "最近对话：\n"
    for msg in context_messages:
        role = "用户" if msg["role"] == "user" else "助手"
        context += f"{role}: {msg['content'][:200]}\n"
    
    prompt = f"""
作为研究助手，基于上述研究内容和对话历史，简洁回答用户的后续问题：

{message}

要求：
- 直接回答，不需要重新研究
- 基于已有信息进行分析
- 如果信息不足，说明需要新的研究
- 保持简洁，1-3段落即可
"""
    
    try:
        # Use Anthropic API directly
        response = await model.acompletion(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"对话出错：{str(e)}"


@app.get("/api/chat/stream")
async def chat_stream(session_id: str = "new", message: str = ""):
    """Stream chat responses with progress updates."""
    return StreamingResponse(
        stream_generator(session_id, message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, debug=True)
