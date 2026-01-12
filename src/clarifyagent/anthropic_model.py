"""Anthropic model wrapper compatible with the agents framework."""
import os
from typing import Optional
from anthropic import Anthropic, AsyncAnthropic


class AnthropicModel:
    """
    Anthropic model adapter for use with the agents framework.
    Provides a simple interface to Anthropic's Claude models.
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ):
        """
        Initialize Anthropic model.

        Args:
            model: Model name (e.g., "claude-sonnet-4-5", "claude-opus-4-5")
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        """
        self.model = model
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment or provided")

        # Initialize both sync and async clients
        self.client = Anthropic(api_key=self.api_key)
        self.async_client = AsyncAnthropic(api_key=self.api_key)

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
        # Extract system message if present
        system_message = None
        user_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            else:
                user_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })

        # Call Anthropic API
        response = await self.async_client.messages.create(
            model=self.model,
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            temperature=temperature if temperature is not None else self.temperature,
            system=system_message if system_message else None,
            messages=user_messages
        )

        # Convert to litellm-compatible format
        class Choice:
            def __init__(self, content):
                self.message = type('Message', (), {'content': content})()

        class Response:
            def __init__(self, content):
                self.choices = [Choice(content)]

        # Extract text content from response
        content = ""
        for block in response.content:
            if hasattr(block, 'text'):
                content += block.text

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
        # Extract system message if present
        system_message = None
        user_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            else:
                user_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })

        # Call Anthropic API
        response = self.client.messages.create(
            model=self.model,
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
            temperature=temperature if temperature is not None else self.temperature,
            system=system_message if system_message else None,
            messages=user_messages
        )

        # Convert to litellm-compatible format
        class Choice:
            def __init__(self, content):
                self.message = type('Message', (), {'content': content})()

        class Response:
            def __init__(self, content):
                self.choices = [Choice(content)]

        # Extract text content from response
        content = ""
        for block in response.content:
            if hasattr(block, 'text'):
                content += block.text

        return Response(content)


def build_anthropic_model(model_type: str = "standard") -> AnthropicModel:
    """
    Build Anthropic model based on type.

    Args:
        model_type: "fast" for Sonnet, "quality" for Opus, "standard" for default

    Returns:
        AnthropicModel instance
    """
    from .config import FAST_MODEL, QUALITY_MODEL, ANTHROPIC_API_KEY

    if model_type == "fast":
        model = FAST_MODEL
    elif model_type == "quality":
        model = QUALITY_MODEL
    else:
        model = os.getenv("LLM_MODEL", FAST_MODEL)

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("Missing ANTHROPIC_API_KEY in environment/.env")

    print(f"[DEBUG] Using Anthropic model: {model}")

    return AnthropicModel(
        model=model,
        api_key=ANTHROPIC_API_KEY,
        temperature=0.7,
        max_tokens=4096
    )
