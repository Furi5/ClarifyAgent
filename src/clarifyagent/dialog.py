from dataclasses import dataclass, field
from typing import Any

@dataclass
class SessionState:
    messages: list[dict] = field(default_factory=list)
    task_draft: dict[str, Any] = field(default_factory=dict)
    asked: int = 0

def add_user(state: SessionState, text: str) -> None:
    state.messages.append({"role": "user", "content": text})

def add_clarification(state: SessionState, text: str) -> None:
    state.messages.append({"role": "user", "content": text})

def update_task_draft(state: SessionState, task: dict[str, Any]) -> None:
    state.task_draft = task

def add_assistant(state: SessionState, content: str):
    """记录 assistant 的回复"""
    state.messages.append({"role": "assistant", "content": content})