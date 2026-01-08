from typing import Any
from agents import Agent, RunContextWrapper, function_tool, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel

import os

from .tools.serperapi import web_search
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
        tools=[ask_user, web_search_tool],  # read_url 已移除
    )



def build_model(model_type: str = "standard") -> LitellmModel:
    """
    Build the LLM model adapter with performance optimization.
    
    Args:
        model_type: "fast" for tool calls, "quality" for synthesis, "standard" for default
    """
    from .config import FAST_MODEL, QUALITY_MODEL, OPENROUTER_API_KEY
    
    if model_type == "fast":
        model = FAST_MODEL
    elif model_type == "quality":
        model = QUALITY_MODEL
    else:
        model = os.getenv("LLM_MODEL", "openrouter/anthropic/claude-4.5-sonnet")
    
    # Set OpenRouter API key for LiteLLM
    os.environ["OPENROUTER_API_KEY"] = OPENROUTER_API_KEY
    
    # Determine API configuration based on model
    if model.startswith("openrouter/"):
        # Using OpenRouter - LiteLLM will handle routing automatically
        base_url = "https://openrouter.ai/api/v1"
        api_key = OPENROUTER_API_KEY
        if not api_key:
            raise RuntimeError("Missing OPENROUTER_API_KEY in environment/.env for Claude models")
        print(f"[DEBUG] Using OpenRouter for model: {model}")
        
    else:
        # Fallback to DeepSeek or other providers
        base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
        api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("Missing LLM_API_KEY (or DEEPSEEK_API_KEY) in environment/.env")
        print(f"[DEBUG] Using default provider for model: {model}")

    return LitellmModel(model=model, base_url=base_url, api_key=api_key)
