"""Base Agent classes and utilities."""
from typing import Any, List, Optional
from agents import Agent, Runner
from agents.extensions.models.litellm_model import LitellmModel


class BaseAgent:
    """Base class for all agents."""
    
    def __init__(self, name: str, model: LitellmModel, instructions: str, tools: Optional[List[Any]] = None):
        self.name = name
        self.model = model
        self.instructions = instructions
        self.tools = tools or []
        self.agent = Agent(
            name=name,
            model=model,
            instructions=instructions,
            tools=self.tools
        )
    
    async def run(self, input_data: str) -> str:
        """Run the agent with input data."""
        result = await Runner.run(self.agent, input_data)
        return result.final_output or ""
