"""Subagent Pool for managing and executing parallel tasks."""
import asyncio
from typing import List, Optional
from ..anthropic_model import AnthropicModel

from .subagent import Subagent
from ..schema import Subtask, SubtaskResult


class SubagentPool:
    """Pool of Subagents for parallel execution."""

    def __init__(self, model: AnthropicModel, max_parallel: int = 5):
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
        
        # Execute in parallel using asyncio.gather
        tasks = [
            subagent.search(subtask)
            for subagent, subtask in zip(subagents, subtasks)
        ]
        
        # If we have more subtasks than parallel capacity, process in batches
        if len(subtasks) > num_parallel:
            results = []
            for i in range(0, len(subtasks), num_parallel):
                batch = subtasks[i:i + num_parallel]
                batch_tasks = [
                    subagents[j % num_parallel].search(subtask)
                    for j, subtask in enumerate(batch)
                ]
                batch_results = await asyncio.gather(*batch_tasks)
                results.extend(batch_results)
            return results
        else:
            return await asyncio.gather(*tasks)
