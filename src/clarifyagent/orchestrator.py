"""Orchestrator for coordinating the Deep Research workflow."""
from typing import Optional, Callable, Union
from .anthropic_model import AnthropicModel
from .deepseek_model import DeepseekModel

from .schema import Plan, ResearchResult, Subtask
from .clarifier import assess_input
from .planner import decompose_task
from .executor import Executor
from .synthesizer import synthesize_results
from .tools.serperapi import web_search


class Orchestrator:
    """Orchestrator coordinating Clarifier → Planner → Executor → Synthesizer."""
    
    def __init__(
        self,
        clarifier_model: Union[AnthropicModel, DeepseekModel],
        planner_model: Union[AnthropicModel, DeepseekModel],
        executor_model: Union[AnthropicModel, DeepseekModel],
        synthesizer_model: Union[AnthropicModel, DeepseekModel],
        max_parallel: int = 5,
        progress_callback: Optional[Callable[[str, str, str], None]] = None
    ):
        self.clarifier_model = clarifier_model
        self.planner_model = planner_model
        self.executor_model = executor_model
        self.synthesizer_model = synthesizer_model
        self.executor = Executor(executor_model, max_parallel=max_parallel)
        self.progress_callback = progress_callback
    
    def _report_progress(self, stage: str, message: str, detail: str = ""):
        """Report progress to callback if available."""
        if self.progress_callback:
            try:
                self.progress_callback(stage, message, detail)
            except Exception:
                pass  # Ignore callback errors
    
    async def run(
        self,
        user_input: str,
        messages: list[dict],
        task_draft: dict
    ) -> tuple[Plan, Optional[ResearchResult]]:
        """
        Run the complete research workflow.
        
        Args:
            user_input: User's research request
            messages: Conversation history
            task_draft: Current task draft
        
        Returns:
            Tuple of (Plan, Optional[ResearchResult])
            - Plan contains the assessment/clarification
            - ResearchResult is None if clarification is needed
        """
        # Step 1: Clarifier - Assess input sufficiency
        plan = await assess_input(
            self.clarifier_model,
            messages,
            task_draft
        )
        
        # Step 2: Handle different actions
        if plan.next_action == "NEED_CLARIFICATION":
            # Need clarification, return plan without research result
            return plan, None
        
        elif plan.next_action == "VERIFY_TOPIC":
            # Verify unknown topic first
            topic = plan.unknown_topic or "unknown"
            query = plan.search_query or topic
            
            try:
                search_result = await web_search(query)
                # Inject search result into messages for re-assessment
                messages.append({
                    "role": "user",
                    "content": f"[系统搜索结果] 关于「{topic}」的信息:\n\n{search_result}"
                })
                # Re-assess with verified information
                plan = await assess_input(
                    self.clarifier_model,
                    messages,
                    task_draft
                )
            except Exception as e:
                # If search fails, still return plan
                return plan, None
        
        if plan.next_action == "START_RESEARCH":
            try:
                # Step 3: Planner - 分析需要研究哪些方面
                self._report_progress("planning", "规划研究方向", plan.task.goal)
                print(f"[DEBUG] 分解任务: {plan.task.goal}")
                subtasks = await decompose_task(
                    self.planner_model,
                    plan.task
                )
                
                print(f"[DEBUG] Planner 创建了 {len(subtasks)} 个子任务")
                
                if not subtasks:
                    # Fallback: create subtasks from research_focus
                    print(f"[DEBUG] 使用 fallback，从 research_focus 创建子任务")
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
                    # Still no subtasks, return plan without result
                    print("[WARN] 无法创建子任务")
                    return plan, None
                
                print(f"[DEBUG] 创建了 {len(subtasks)} 个子任务")
                self._report_progress("planning", f"将研究 {len(subtasks)} 个方面", ", ".join([s.focus for s in subtasks]))
                
                # Step 4: Executor - Execute parallel search
                self._report_progress("searching", "开始检索", f"并行搜索 {len(subtasks)} 个方向")
                print(f"[DEBUG] 开始并行执行搜索...")
                
                # Execute with progress updates per subtask
                subtask_results = []
                for i, subtask in enumerate(subtasks):
                    self._report_progress("searching", f"检索中 ({i+1}/{len(subtasks)})", subtask.focus)
                    result = await self.executor.execute_single(subtask)
                    if result:
                        subtask_results.append(result)
                
                print(f"[DEBUG] 完成 {len(subtask_results)} 个子任务")
                
                if not subtask_results:
                    print("[WARN] 没有返回子任务结果")
                    self._report_progress("error", "检索失败", "未获取到任何结果")
                    return plan, None
                
                # Step 5: Synthesizer - Synthesize results
                self._report_progress("synthesizing", "分析整合", f"综合 {len(subtask_results)} 个方向的信息")
                print(f"[DEBUG] 开始综合结果...")
                research_result = await synthesize_results(
                    self.synthesizer_model,
                    plan.task.goal,
                    plan.task.research_focus,
                    subtask_results
                )
                print(f"[DEBUG] 结果综合完成")
                self._report_progress("complete", "研究完成", "")
                
                return plan, research_result
            except Exception as e:
                print(f"[ERROR] 研究执行失败: {e}")
                import traceback
                traceback.print_exc()
                self._report_progress("error", "研究执行出错", str(e))
                # Return plan without result on error
                return plan, None
        
        # For CONFIRM_PLAN or CANNOT_DO, return plan without research result
        return plan, None
