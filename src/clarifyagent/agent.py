from typing import Any
from agents import Agent, RunContextWrapper, function_tool, set_tracing_disabled

import os

from .tools.serperapi import web_search
from .anthropic_model import AnthropicModel
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
    from .anthropic_model import build_anthropic_model
    llm = build_anthropic_model("fast")

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



def build_model(model_type: str = "standard") -> AnthropicModel:
    """
    Build the Anthropic model adapter with performance optimization.

    Args:
        model_type: "fast" for tool calls, "quality" for synthesis, "standard" for default
    """
    from .anthropic_model import build_anthropic_model

    return build_anthropic_model(model_type)
