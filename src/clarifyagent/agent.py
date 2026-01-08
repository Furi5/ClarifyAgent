from typing import Any
from agents import Agent, RunContextWrapper, function_tool, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel

import os

from .tools.serperapi import web_search
from .tools.jina import jina_read

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

@function_tool
async def read_url(ctx: RunContextWrapper[Any], url: str) -> str:
    return await jina_read(url=url)

def build_agent() -> Agent:
    llm = LitellmModel(
        model="deepseek/deepseek-chat",
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )

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
        tools=[ask_user, web_search_tool, read_url],
    )



def build_model() -> LitellmModel:
    """
    Build the LLM model adapter for openai-agents Runner.
    Uses LiteLLM under the hood (DeepSeek / etc).
    """
    model = os.getenv("LLM_MODEL", "deepseek/deepseek-chat")
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing LLM_API_KEY (or DEEPSEEK_API_KEY) in environment/.env")

    return LitellmModel(model=model, base_url=base_url, api_key=api_key)
