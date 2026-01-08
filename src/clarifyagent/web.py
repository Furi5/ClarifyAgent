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
from .dialog import SessionState, add_user, add_assistant, update_task_draft
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
    """Create a new orchestrator instance."""
    return Orchestrator(
        clarifier_model=build_model(),
        planner_model=build_model(),
        executor_model=build_model(),
        synthesizer_model=build_model(),
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


def render_plan(plan) -> str:
    """Render plan for confirmation."""
    task = plan.task
    lines = [f"我理解你想做：**{task.goal}**", ""]
    
    if getattr(task, "research_focus", None) and task.research_focus:
        lines.append("计划重点覆盖：")
        for f in task.research_focus:
            lines.append(f"• {f}")
        lines.append("")
    
    if getattr(plan, "assumptions", None) and plan.assumptions:
        lines.append("（我的假设：" + "；".join(plan.assumptions) + "）")
        lines.append("")
    
    lines.append(plan.confirm_prompt or "这样可以开始吗？")
    return "\n".join(lines)


def render_research_result(result: ResearchResult) -> dict:
    """Render research result as structured data."""
    return {
        "goal": result.goal,
        "synthesis": result.synthesis,
        "research_focus": result.research_focus,
        "findings": {
            focus: {
                "findings": finding.findings[:5],
                "sources": [
                    {"title": s.title, "url": s.url, "snippet": s.snippet[:200] if s.snippet else ""}
                    for s in finding.sources[:3]
                ],
                "confidence": finding.confidence
            }
            for focus, finding in result.findings.items()
        } if result.findings else {},
        "citations": [
            {
                "text": cit.text,
                "sources": [{"title": s.title, "url": s.url} for s in cit.sources]
            }
            for cit in result.citations[:10]
        ] if result.citations else []
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
    session_id, session = get_or_create_session(session_id if session_id != "new" else None)
    state = session["state"]
    pending_plan = session["pending_plan"]
    
    # Send session ID first
    yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"
    
    try:
        user_message = message.strip()
        if not user_message:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Message cannot be empty'})}\n\n"
            return
        
        # Handle confirmation for pending plan
        if pending_plan and is_confirmation(user_message):
            add_user(state, "[用户确认] 已确认按计划执行")
            session["pending_plan"] = None
            
            yield f"data: {json.dumps({'type': 'progress', 'stage': 'planning', 'message': '开始执行研究计划...'})}\n\n"
            
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
        
        # Handle option selection for clarification
        if pending_plan and pending_plan.clarification:
            options = pending_plan.clarification.get("options", [])
            choice = is_option_selection(user_message, options)
            if choice:
                selected_option = options[choice - 1]
                add_user(state, f"[澄清回复] {selected_option}")
                
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
        
        yield f"data: {json.dumps({'type': 'progress', 'stage': 'clarifying', 'message': '分析研究需求...'})}\n\n"
        await asyncio.sleep(0.1)  # Let the event flush
        
        # Import and run steps individually for progress updates
        from .clarifier import assess_input
        from .planner import decompose_task
        from .executor import Executor
        from .synthesizer import synthesize_results
        from .schema import Subtask
        from .agent import build_model
        
        model = build_model()
        
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
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'planning', 'message': '规划研究方向...', 'detail': plan.task.goal})}\n\n"
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
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'planning', 'message': f'将研究 {len(subtasks)} 个方面', 'detail': ', '.join(focus_list[:3])})}\n\n"
                await asyncio.sleep(0.1)
                
                # Step 3: Executor - 并行执行所有子任务
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'searching', 'message': f'并行检索 {len(subtasks)} 个方向', 'detail': ', '.join([s.focus for s in subtasks][:3])})}\n\n"
                await asyncio.sleep(0.1)
                
                executor = Executor(model, max_parallel=len(subtasks))
                
                # 并行执行所有子任务
                import asyncio as aio
                tasks = [executor.execute_single(subtask) for subtask in subtasks]
                results = await aio.gather(*tasks, return_exceptions=True)
                
                # 过滤有效结果
                subtask_results = [r for r in results if r is not None and not isinstance(r, Exception)]
                
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'searching', 'message': f'检索完成', 'detail': f'获取 {len(subtask_results)}/{len(subtasks)} 个结果'})}\n\n"
                await asyncio.sleep(0.1)
                
                if not subtask_results:
                    yield f"data: {json.dumps({'type': 'error', 'message': '检索失败，未获取到结果'})}\n\n"
                    return
                
                # Step 4: Synthesizer
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'synthesizing', 'message': '分析整合', 'detail': f'{len(subtask_results)} 个方向的信息'})}\n\n"
                await asyncio.sleep(0.1)
                
                research_result = await synthesize_results(
                    model,
                    plan.task.goal,
                    plan.task.research_focus,
                    subtask_results
                )
                
                yield f"data: {json.dumps({'type': 'progress', 'stage': 'complete', 'message': '研究完成'})}\n\n"
                await asyncio.sleep(0.1)
                
                add_assistant(state, f"研究完成：{research_result.goal}")
                update_task_draft(state, plan.task.model_dump())
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
