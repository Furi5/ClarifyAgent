import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
JINA_API_KEY = os.getenv("JINA_API_KEY")

# Model configuration for different modules
CLARIFIER_MODEL = os.getenv("CLARIFIER_MODEL", "deepseek/deepseek-chat")
PLANNER_MODEL = os.getenv("PLANNER_MODEL", "deepseek/deepseek-chat")
EXECUTOR_MODEL = os.getenv("EXECUTOR_MODEL", "deepseek/deepseek-chat")
SYNTHESIZER_MODEL = os.getenv("SYNTHESIZER_MODEL", "deepseek/deepseek-chat")

# Parallel execution configuration
MAX_PARALLEL_SUBAGENTS = int(os.getenv("MAX_PARALLEL_SUBAGENTS", "5"))
MAX_TOOL_CALLS_PER_AGENT = int(os.getenv("MAX_TOOL_CALLS_PER_AGENT", "5"))

# Content length limits (to prevent context window overflow)
# 参考 GPT-Researcher 的做法，使用更保守的限制
MAX_CONTENT_CHARS = int(os.getenv("MAX_CONTENT_CHARS", "3000"))   # 单次工具返回最大字符数
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "3"))    # 搜索结果数量
MAX_SNIPPET_CHARS = int(os.getenv("MAX_SNIPPET_CHARS", "200"))    # 每个 snippet 最大字符数
MAX_TOOL_OUTPUT = int(os.getenv("MAX_TOOL_OUTPUT", "2000"))       # 工具输出最大字符数
