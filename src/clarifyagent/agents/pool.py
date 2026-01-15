"""Subagent Pool for managing and executing parallel tasks."""
import asyncio
import time
from typing import List, Optional, Union
from ..anthropic_model import AnthropicModel
from ..deepseek_model import DeepseekModel

from .subagent import Subagent
from ..schema import Subtask, SubtaskResult


class SubagentPool:
    """Pool of Subagents for parallel execution."""

    def __init__(self, model: Union[AnthropicModel, DeepseekModel], max_parallel: int = 5):
        self.model = model
        self.max_parallel = max_parallel
        self._subagents: List[Subagent] = []
    
    def _get_or_create_subagent(self, index: int) -> Subagent:
        """Get existing subagent or create new one."""
        while len(self._subagents) <= index:
            self._subagents.append(Subagent(len(self._subagents), self.model))
        return self._subagents[index]
    
    async def execute_parallel(
        self,
        subtasks: List[Subtask],
        max_parallel: Optional[int] = None
    ) -> List[SubtaskResult]:
        """
        Execute subtasks in parallel.
        
        Args:
            subtasks: List of subtasks to execute
            max_parallel: Maximum number of parallel executions (defaults to self.max_parallel)
        
        Returns:
            List of subtask results
        """
        if not subtasks:
            return []
        
        max_parallel = max_parallel or self.max_parallel
        num_parallel = min(len(subtasks), max_parallel)
        
        # Create subagents
        subagents = [
            self._get_or_create_subagent(i)
            for i in range(num_parallel)
        ]
        
        # 建议 4：给每个 task 打 wall-clock
        t0 = time.monotonic()
        print(f"[DEBUG] SubagentPool.execute_parallel: Starting {len(subtasks)} tasks (max_parallel={num_parallel})")
        
        # Execute in parallel using asyncio.gather with return_exceptions
        # 必做 3：gather 改为 fail-fast 或 partial return
        tasks = [
            subagent.search(subtask)
            for subagent, subtask in zip(subagents, subtasks)
        ]
        
        # 给每个 task 添加时间记录
        async def timed_search(subagent, subtask, task_id):
            """Wrapper to add timing for each task"""
            task_t0 = time.monotonic()
            try:
                result = await subagent.search(subtask)
                task_elapsed = time.monotonic() - task_t0
                print(f"[DEBUG] Task {task_id} ({subtask.focus[:30]}...) finished in {task_elapsed:.2f}s (wall-clock)")
                return result
            except Exception as e:
                task_elapsed = time.monotonic() - task_t0
                print(f"[ERROR] Task {task_id} ({subtask.focus[:30]}...) failed after {task_elapsed:.2f}s: {e}")
                raise
        
        # If we have more subtasks than parallel capacity, process in batches
        if len(subtasks) > num_parallel:
            results = []
            for i in range(0, len(subtasks), num_parallel):
                batch = subtasks[i:i + num_parallel]
                batch_tasks = [
                    timed_search(subagents[j % num_parallel], subtask, f"batch{i//num_parallel}-task{j}")
                    for j, subtask in enumerate(batch)
                ]
                # 必做 3：使用 return_exceptions=True 允许部分失败
                batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                # 过滤掉异常，转换为 None
                batch_results = [r if not isinstance(r, Exception) else None for r in batch_results]
                results.extend(batch_results)
            
            total_elapsed = time.monotonic() - t0
            print(f"[DEBUG] SubagentPool.execute_parallel: Completed {len(results)} tasks in {total_elapsed:.2f}s (wall-clock)")
            return results
        else:
            # 必做 3：使用 return_exceptions=True 允许部分失败
            timed_tasks = [
                timed_search(subagent, subtask, f"task{i}")
                for i, (subagent, subtask) in enumerate(zip(subagents, subtasks))
            ]
            results = await asyncio.gather(*timed_tasks, return_exceptions=True)
            # 过滤掉异常，转换为 None
            results = [r if not isinstance(r, Exception) else None for r in results]
            
            total_elapsed = time.monotonic() - t0
            print(f"[DEBUG] SubagentPool.execute_parallel: Completed {len(results)} tasks in {total_elapsed:.2f}s (wall-clock)")
            return results
