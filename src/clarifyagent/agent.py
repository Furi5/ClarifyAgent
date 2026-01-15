from typing import Any, Union
from agents import Agent, RunContextWrapper, function_tool, set_tracing_disabled

import os

from .tools.serperapi import web_search
from .anthropic_model import AnthropicModel
from .deepseek_model import DeepseekModel
# from .tools.jina import jina_read  # 已禁用以提升性能

set_tracing_disabled(True)

@function_tool
def ask_user(ctx: RunContextWrapper[Any], question: str) -> str:
    print("\n[ClarifyAgent] I need one quick clarification:")
    print(question)
    return input("> ").strip()

@function_tool
async def web_search_tool(ctx: RunContextWrapper[Any], query: str) -> dict:
    """Search the web for information."""
    from .tools.serperapi import web_search
    result = await web_search(query)
    return {"result": result}

# @function_tool  
# async def read_url(ctx: RunContextWrapper[Any], url: str) -> str:
#     return await jina_read(url=url)  # 已禁用以提升性能

def build_agent() -> Agent:
    from .agent import build_model
    llm = build_model("fast")

    return Agent(
        name="ClarifyAgent",
        model=llm,
        instructions=(
            "You are a clarification-first assistant.\n"
            "Use tools when helpful:\n"
            "- web_search: to search the web\n"
            "- read_url: to fetch/clean a page\n"
            "Ask at most ONE clarification question via ask_user.\n"
        ),
        tools=[ask_user, web_search_tool],  # read_url 已移除
    )



def build_model(model_type: str = "standard") -> Union[AnthropicModel, DeepseekModel]:
    """
    Build the LLM model adapter with performance optimization.
    Supports both Anthropic (Claude) and Deepseek models based on LLM_PROVIDER config.

    Args:
        model_type: "fast" for tool calls, "quality" for synthesis, "standard" for default,
                   "clarifier", "planner", "executor", "synthesizer" for specific modules

    Returns:
        AnthropicModel or DeepseekModel instance based on LLM_PROVIDER configuration
    """
    from .config import LLM_PROVIDER
    from .anthropic_model import build_anthropic_model
    from .deepseek_model import build_deepseek_model

    if LLM_PROVIDER == "deepseek":
        return build_deepseek_model(model_type)
    else:
        # Default to Claude
        return build_anthropic_model(model_type)
