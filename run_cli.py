import asyncio
import os
from typing import Any

from dotenv import load_dotenv
load_dotenv()

from agents import Agent, Runner, RunContextWrapper, function_tool, set_tracing_disabled
from agents.extensions.models.litellm_model import LitellmModel

set_tracing_disabled(True)


@function_tool
def ask_user(ctx: RunContextWrapper[Any], question: str) -> str:
    print("\n[ClarifyAgent] I need one quick clarification:")
    print(question)
    return input("> ").strip()


# ✅ DeepSeek via LiteLLM (no api_base parameter)
llm = LitellmModel(
    model="deepseek/deepseek-chat",
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_API_BASE"),
)

clarify_agent = Agent(
    name="ClarifyAgent",
    model=llm,
    instructions=(
        "You are a clarification-first assistant.\n"
        "Your job: help the user complete their task with minimal back-and-forth.\n\n"
        "Rules:\n"
        "1) Default to proceeding without questions.\n"
        "2) Only ask a clarification if the task has a high-impact fork (two incompatible interpretations)\n"
        "   AND you cannot safely assume a default.\n"
        "3) If you ask, ask EXACTLY ONE question via the tool `ask_user`.\n"
        "   - Make it answerable in 1 second.\n"
        "   - Prefer multiple-choice (A/B/C) with an 'Other:' option.\n"
        "4) After you receive the answer, DO NOT ask more questions. Continue and finish.\n\n"
        "Output requirements:\n"
        "- Provide a short 'Assumptions' section (only if you assumed something).\n"
        "- Then provide the final actionable result.\n"
    ),
    tools=[ask_user],
)


async def main() -> None:
    user_input = input("User> ").strip()
    result = await Runner.run(clarify_agent, user_input)
    print("\n=== Final Output ===\n")
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
