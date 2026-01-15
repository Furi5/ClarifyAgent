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

        # 导入超时配置
        from .config import API_TIMEOUT
        import httpx
        
        # Initialize both sync and async clients with timeout
        # OpenAI SDK 支持 timeout 参数，可以直接设置
        # 使用 httpx.Timeout 可以更精细控制（connect, read, write）
        timeout_config = httpx.Timeout(
            API_TIMEOUT,  # 总超时时间
            connect=10.0,  # 连接超时 10 秒
            read=API_TIMEOUT,  # 读取超时
            write=10.0  # 写入超时 10 秒
        )
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
            timeout=timeout_config
        )
        self.async_client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
            timeout=timeout_config
        )
        
        self.api_timeout = API_TIMEOUT
        print(f"[DEBUG] DeepseekModel initialized: model={model}, timeout={API_TIMEOUT}s (connect=10s, read={API_TIMEOUT}s, write=10s)")

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
        import time
        
        # 计算请求大小（用于诊断）
        total_chars = sum(len(str(msg.get("content", ""))) for msg in messages)
        
        # 添加超时和诊断日志
        call_start = time.time()
        print(f"[DEBUG] Deepseek API call starting: model={self.model}, messages_chars={total_chars}, timeout={self.api_timeout}s")
        
        try:
            # OpenAI SDK 的 timeout 已经在 client 初始化时设置
            # 如果超时，SDK 会抛出 APITimeoutError
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature if temperature is not None else self.temperature,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                stream=False
            )
            
            call_elapsed = time.time() - call_start
            response_chars = len(response.choices[0].message.content) if response.choices else 0
            print(f"[DEBUG] Deepseek API call completed: {call_elapsed:.2f}s, response_chars={response_chars}")
            
            if call_elapsed > 10:
                print(f"[WARN] Deepseek API call took {call_elapsed:.2f}s (slow, >10s) - 可能是网络延迟或 API 响应慢")
            elif call_elapsed > 5:
                print(f"[INFO] Deepseek API call took {call_elapsed:.2f}s (moderate delay)")
            
        except Exception as e:
            call_elapsed = time.time() - call_start
            error_type = type(e).__name__
            if "timeout" in error_type.lower() or "timeout" in str(e).lower():
                print(f"[ERROR] Deepseek API call TIMEOUT after {call_elapsed:.2f}s (limit: {self.api_timeout}s): {e}")
            else:
                print(f"[ERROR] Deepseek API call failed after {call_elapsed:.2f}s: {error_type}: {e}")
            raise

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
