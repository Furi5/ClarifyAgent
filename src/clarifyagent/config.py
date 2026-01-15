import os
from dotenv import load_dotenv

load_dotenv()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
JINA_API_KEY = os.getenv("JINA_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# LLM Provider selection: "claude" or "deepseek"
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "claude").lower()

# Claude model configuration for different modules
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

# Deepseek model configuration for different modules
DEEPSEEK_CLARIFIER_MODEL = os.getenv("DEEPSEEK_CLARIFIER_MODEL", "deepseek-chat")
DEEPSEEK_PLANNER_MODEL = os.getenv("DEEPSEEK_PLANNER_MODEL", "deepseek-chat")
DEEPSEEK_EXECUTOR_MODEL = os.getenv("DEEPSEEK_EXECUTOR_MODEL", "deepseek-chat")
DEEPSEEK_SYNTHESIZER_MODEL = os.getenv("DEEPSEEK_SYNTHESIZER_MODEL", "deepseek-chat")
DEEPSEEK_FAST_MODEL = os.getenv("DEEPSEEK_FAST_MODEL", "deepseek-chat")  # For fast synthesis
DEEPSEEK_QUALITY_MODEL = os.getenv("DEEPSEEK_QUALITY_MODEL", "deepseek-chat")  # For critical thinking

# Parallel execution configuration
MAX_PARALLEL_SUBAGENTS = int(os.getenv("MAX_PARALLEL_SUBAGENTS", "5"))
MAX_TOOL_CALLS_PER_AGENT = int(os.getenv("MAX_TOOL_CALLS_PER_AGENT", "5"))

# Content length limits (to prevent context window overflow)
# 参考 GPT-Researcher 的做法，使用更保守的限制
MAX_CONTENT_CHARS = int(os.getenv("MAX_CONTENT_CHARS", "3000"))   # 单次工具返回最大字符数
MAX_SEARCH_RESULTS = int(os.getenv("MAX_SEARCH_RESULTS", "15"))    # 搜索结果数量（增加以获取更多候选页面）
MAX_SNIPPET_CHARS = int(os.getenv("MAX_SNIPPET_CHARS", "200"))    # 每个 snippet 最大字符数
MAX_TOOL_OUTPUT = int(os.getenv("MAX_TOOL_OUTPUT", "2000"))       # 工具输出最大字符数

# Performance optimization settings
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "30"))                # API调用超时时间(秒)
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "4"))  # 最大并发请求数
ADAPTIVE_CONCURRENCY = os.getenv("ADAPTIVE_CONCURRENCY", "true").lower() == "true"  # 自适应并发
AGENT_EXECUTION_TIMEOUT = int(os.getenv("AGENT_EXECUTION_TIMEOUT", "180"))  # Agent 执行超时时间(秒)，默认5分钟

# LLM confidence evaluation settings
ENABLE_LLM_CONFIDENCE = os.getenv("ENABLE_LLM_CONFIDENCE", "false").lower() == "true"  # 是否启用 LLM 评分
_llm_weight_raw = float(os.getenv("LLM_CONFIDENCE_WEIGHT", "0.4"))
LLM_CONFIDENCE_WEIGHT = max(0.0, min(1.0, _llm_weight_raw))  # LLM 评分权重，强制限制在 0.0-1.0 范围内
if _llm_weight_raw != LLM_CONFIDENCE_WEIGHT:
    print(f"[WARN] LLM_CONFIDENCE_WEIGHT={_llm_weight_raw} 超出范围，已修正为 {LLM_CONFIDENCE_WEIGHT}")

# Jina configuration
JINA_TIMEOUT = float(os.getenv("JINA_TIMEOUT", "3.0"))  # Jina 硬超时时间(秒)，默认3秒
JINA_RETRIES = int(os.getenv("JINA_RETRIES", "0"))  # Jina 重试次数，默认0（零重试）

# Subagent configuration
MAX_AGENT_TURNS = int(os.getenv("MAX_AGENT_TURNS", "4"))  # 每个子代理最大搜索轮次，默认2（1次搜索+1次输出）

# Jina 黑名单域名（这些域名直接禁用 Jina 读取）
JINA_SKIP_DOMAINS = [
    "pmc.ncbi.nlm.nih.gov",
    "nejm.org",
    "sciencedirect.com",
    "annalsofoncology.org",
    "ascopubs.org",
    "aacrjournals.org",
    "onlinelibrary.wiley.com",
    "link.springer.com",
    "nature.com",
    "clinicaltrials.gov",
    "asco.org",
    "esmo.org",
    # 403 Forbidden
    "jto.org",
    "mdpi.com",
    "ilcn.org",
    "drugs.com",
    "tandfonline.com",
    "nytimes.com",
    "consultant360.com",
    "cancerresearch.org",
    "wikipedia.org",
    "merck.com",
    "personalizedmedonc.com",
    "cancerletter.com",
]


def get_litellm_model_config(model_name: str):
    """
    Get the correct litellm model format and API key based on LLM_PROVIDER.
    
    Args:
        model_name: The model name (e.g., "claude-sonnet-4-5" or "deepseek-chat")
    
    Returns:
        tuple: (litellm_model_string, api_key)
    """
    if LLM_PROVIDER == "deepseek":
        return f"deepseek/{model_name}", DEEPSEEK_API_KEY
    else:
        return f"anthropic/{model_name}", ANTHROPIC_API_KEY
