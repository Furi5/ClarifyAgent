"""Deepseek model wrapper compatible with the agents framework."""
import os
from typing import Optional
from openai import OpenAI, AsyncOpenAI


class DeepseekModel:
    """
    Deepseek model adapter for use with the agents framework.
    Provides a simple interface to Deepseek's models.
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ):
        """
        Initialize Deepseek model.

        Args:
            model: Model name (e.g., "deepseek-chat")
            api_key: Deepseek API key (defaults to DEEPSEEK_API_KEY env var)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        """
        self.model = model
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens

        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment or provided")

        # Initialize both sync and async clients
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )
        self.async_client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )

    async def acompletion(self, messages: list, temperature: Optional[float] = None, **kwargs):
        """
        Async completion compatible with litellm interface.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Override default temperature
            **kwargs: Additional parameters

        Returns:
            Response object compatible with litellm format
        """
        # Call Deepseek API
        response = await self.async_client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=False
        )

        # Convert to litellm-compatible format
        class Choice:
            def __init__(self, content):
                self.message = type('Message', (), {'content': content})()

        class Response:
            def __init__(self, content):
                self.choices = [Choice(content)]

        # Extract text content from response
        content = response.choices[0].message.content

        return Response(content)

    def completion(self, messages: list, temperature: Optional[float] = None, **kwargs):
        """
        Sync completion (not recommended, use acompletion instead).

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Override default temperature
            **kwargs: Additional parameters

        Returns:
            Response object compatible with litellm format
        """
        # Call Deepseek API
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature if temperature is not None else self.temperature,
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            stream=False
        )

        # Convert to litellm-compatible format
        class Choice:
            def __init__(self, content):
                self.message = type('Message', (), {'content': content})()

        class Response:
            def __init__(self, content):
                self.choices = [Choice(content)]

        # Extract text content from response
        content = response.choices[0].message.content

        return Response(content)


def build_deepseek_model(model_type: str = "standard") -> DeepseekModel:
    """
    Build Deepseek model based on type.

    Args:
        model_type: "fast" for fast model, "quality" for quality model, "standard" for default

    Returns:
        DeepseekModel instance
    """
    from .config import (
        DEEPSEEK_API_KEY, 
        DEEPSEEK_FAST_MODEL, 
        DEEPSEEK_QUALITY_MODEL,
        DEEPSEEK_CLARIFIER_MODEL,
        DEEPSEEK_PLANNER_MODEL,
        DEEPSEEK_EXECUTOR_MODEL,
        DEEPSEEK_SYNTHESIZER_MODEL
    )

    if model_type == "fast":
        model = DEEPSEEK_FAST_MODEL
    elif model_type == "quality":
        model = DEEPSEEK_QUALITY_MODEL
    elif model_type == "clarifier":
        model = DEEPSEEK_CLARIFIER_MODEL
    elif model_type == "planner":
        model = DEEPSEEK_PLANNER_MODEL
    elif model_type == "executor":
        model = DEEPSEEK_EXECUTOR_MODEL
    elif model_type == "synthesizer":
        model = DEEPSEEK_SYNTHESIZER_MODEL
    else:
        model = os.getenv("DEEPSEEK_MODEL", DEEPSEEK_FAST_MODEL)

    if not DEEPSEEK_API_KEY:
        raise RuntimeError("Missing DEEPSEEK_API_KEY in environment/.env")

    print(f"[DEBUG] Using Deepseek model: {model}")

    return DeepseekModel(
        model=model,
        api_key=DEEPSEEK_API_KEY,
        temperature=0.7,
        max_tokens=4096
    )
