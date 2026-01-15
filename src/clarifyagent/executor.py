"""Executor module for parallel task execution."""
from typing import List, Optional, Union
from .anthropic_model import AnthropicModel
from .deepseek_model import DeepseekModel

from .schema import Subtask, SubtaskResult
from .agents.pool import SubagentPool
from .agents.subagent import Subagent


class Executor:
    """Executor for parallel research task execution."""

    def __init__(self, model: Union[AnthropicModel, DeepseekModel], max_parallel: int = 5):
        self.model = model
        self.pool = SubagentPool(model, max_parallel=max_parallel)
        self._single_agent: Optional[Subagent] = None
    
    async def execute_single(self, subtask: Subtask) -> Optional[SubtaskResult]:
        """
        Execute a single subtask.
        
        Args:
            subtask: Subtask to execute
        
        Returns:
            Subtask result or None on error
        """
        import time
        start_time = time.time()
        print(f"[DEBUG] Executor.execute_single started for: {subtask.focus[:50]}...")
        
        if self._single_agent is None:
            self._single_agent = Subagent(0, self.model)
        
        try:
            result = await self._single_agent.search(subtask)
            elapsed = time.time() - start_time
            print(f"[DEBUG] Executor.execute_single completed: {elapsed:.2f}s, result={'OK' if result else 'None'}")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"[ERROR] execute_single failed after {elapsed:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def execute_parallel_search(
        self,
        subtasks: List[Subtask],
        max_parallel: int = None
    ) -> List[SubtaskResult]:
        """
        Execute multiple subtasks in parallel.
        
        Args:
            subtasks: List of subtasks to execute
            max_parallel: Maximum parallel executions (defaults to pool setting)
        
        Returns:
            List of subtask results
        """
        return await self.pool.execute_parallel(subtasks, max_parallel=max_parallel)
    
    def allocate_resources(self, num_focus: int) -> dict:
        """
        Allocate resources based on task complexity.
        
        Args:
            num_focus: Number of research focus areas
        
        Returns:
            Resource allocation config
        """
        if num_focus <= 2:
            return {
                "num_subagents": 1,
                "max_tool_calls": 10
            }
        elif num_focus <= 4:
            return {
                "num_subagents": num_focus,
                "max_tool_calls": 15
            }
        else:
            return {
                "num_subagents": min(num_focus, 10),
                "max_tool_calls": 20
            }
