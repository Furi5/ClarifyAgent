import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
JINA_API_KEY = os.getenv("JINA_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Model configuration for different modules
# Using official Anthropic SDK with direct Claude models
# Strategy: Use Opus for critical thinking (clarify, plan, execute), Sonnet for final synthesis
CLARIFIER_MODEL = os.getenv("CLARIFIER_MODEL", "claude-sonnet-4-5")
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "claude-sonnet-4-5")
EXECUTOR_MODEL = os.getenv("EXECUTOR_MODEL", "claude-sonnet-4-5")
SYNTHESIZER_MODEL = os.getenv("SYNTHESIZER_MODEL", "claude-opus-4-5")

# Performance optimization: Model layering strategy
# Opus for critical decisions, Sonnet for fast synthesis
FAST_MODEL = os.getenv("FAST_MODEL", "claude-sonnet-4-5")  # For fast synthesis
QUALITY_MODEL = os.getenv("QUALITY_MODEL", "claude-sonnet-4-5")  # For critical thinking

# Parallel execution configuration
MAX_PARALLEL_SUBAGENTS = int(os.getenv("MAX_PARALLEL_SUBAGENTS", "5"))
MAX_TOOL_CALLS_PER_AGENT = int(os.getenv("MAX_TOOL_CALLS_PER_AGENT", "5"))

# Content length limits (to prevent context window overflow)
# 参考 GPT-Researcher 的做法，使用更保守的限制
MAX_CONTENT_CHARS = int(os.getenv("MAX_CONTENT_CHARS", "3000"))   # 单次工具返回最大字符数
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "10"))    # 搜索结果数量
MAX_SNIPPET_CHARS = int(os.getenv("MAX_SNIPPET_CHARS", "200"))    # 每个 snippet 最大字符数
MAX_TOOL_OUTPUT = int(os.getenv("MAX_TOOL_OUTPUT", "2000"))       # 工具输出最大字符数

# Performance optimization settings
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "30"))                # API调用超时时间(秒)
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))  # 最大并发请求数
ADAPTIVE_CONCURRENCY = os.getenv("ADAPTIVE_CONCURRENCY", "true").lower() == "true"  # 自适应并发