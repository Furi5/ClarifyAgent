# 检索策略分析：当前方案 vs LLM 驱动方案

## 当前方案（规则驱动）

### 1. 检索深度控制
- **位置**: `enhanced_research.py` → `smart_research(query, max_results=10)`
- **方式**: 固定 `max_results=10`
- **问题**: 
  - 简单查询可能不需要 10 个结果
  - 复杂查询可能需要更多结果
  - 无法根据任务复杂度动态调整

### 2. Jina 使用判断
- **位置**: `intelligent_research.py` → `should_use_jina()` 和 `create_research_plan()`
- **方式**: 
  - 硬编码域名列表（`HIGH_VALUE_DOMAINS`）
  - 硬编码场景规则（`SCENARIO_RULES`）
  - 固定阈值 `priority >= 2`
  - 固定数量限制：最多 8 个
- **问题**:
  - 规则可能不够灵活
  - 无法理解内容的实际价值
  - 无法根据上下文动态调整

### 3. 聚焦程度
- **位置**: `intelligent_research.py` → `create_research_plan()` 中 `search_results[:15]`
- **方式**: 固定分析前 15 个搜索结果
- **问题**:
  - 可能错过更相关的后续结果
  - 无法根据相关性动态调整

### 4. 工具调用次数
- **位置**: `subagent.py` → `SUBAGENT_INSTRUCTIONS`
- **方式**: 固定最多 2 次调用
- **问题**:
  - 简单任务可能 1 次就够了
  - 复杂任务可能需要更多次

## 用户预期（LLM 驱动）

### 核心思想
**让 LLM 根据任务内容、上下文和检索结果，智能决定：**
1. 需要检索多少结果（检索深度）
2. 哪些源需要深度读取（Jina 使用）
3. 需要聚焦哪些信息（聚焦程度）
4. 是否需要多次检索（工具调用次数）

### 优势
- ✅ **更灵活**: 根据实际内容判断，而非固定规则
- ✅ **更智能**: LLM 能理解内容的语义和价值
- ✅ **更高效**: 简单任务不浪费资源，复杂任务充分检索
- ✅ **更准确**: 根据上下文动态调整策略

## 改进方案设计

### 方案 A: 两阶段 LLM 决策

#### 阶段 1: 检索前规划（Research Planning）
在 Subagent 调用工具前，让 LLM 先做规划：

```python
# 在 Subagent 中，LLM 先做研究规划
research_plan = await llm_plan_research(
    focus=focus,
    queries=queries,
    context=task_context
)
# 返回: {
#   "max_results": 15,  # LLM 决定需要多少结果
#   "search_strategy": "broad" | "focused" | "deep",
#   "expected_sources": ["academic", "patent", "regulatory"],
#   "depth_level": "shallow" | "medium" | "deep"
# }
```

#### 阶段 2: 检索后决策（Post-Search Decision）
在获得搜索结果后，让 LLM 决定哪些需要深度读取：

```python
# 在 enhanced_research_tool 中，LLM 分析搜索结果
jina_decisions = await llm_decide_jina_usage(
    query=query,
    search_results=search_results,  # 包含 title, snippet, url
    research_plan=research_plan
)
# 返回: [
#   {"url": "...", "should_read": True, "reason": "包含关键合成步骤"},
#   {"url": "...", "should_read": False, "reason": "snippet 已包含足够信息"}
# ]
```

### 方案 B: 增强工具参数（推荐）

让 `enhanced_research_tool` 接受 LLM 的决策参数：

```python
@function_tool
async def enhanced_research_tool(
    ctx: RunContextWrapper[Any], 
    query: str,
    max_results: int = None,  # LLM 可以指定
    jina_strategy: str = None,  # "auto" | "selective" | "none"
    focus_areas: List[str] = None  # LLM 指定聚焦领域
) -> str:
    """
    Enhanced research tool with LLM-controlled parameters.
    
    Parameters (all optional, LLM decides):
    - max_results: How many search results to retrieve (default: 10)
    - jina_strategy: 
      - "auto": Let tool decide (current behavior)
      - "selective": LLM will specify which URLs to read
      - "none": Only use Serper, no Jina
    - focus_areas: Specific domains/types to focus on
    """
```

然后在 `SUBAGENT_INSTRUCTIONS` 中指导 LLM 如何决策：

```python
SUBAGENT_INSTRUCTIONS = """
## RESEARCH STRATEGY PLANNING

Before calling enhanced_research_tool, analyze your research task:

1. **Determine search depth (max_results)**:
   - Simple fact lookup: 5-8 results
   - Standard research: 10-15 results  
   - Comprehensive analysis: 15-20 results
   - Deep investigation: 20+ results

2. **Decide Jina usage**:
   - If task needs detailed technical content (synthesis, protocols): use "selective"
   - If task needs quick overview: use "none"
   - If uncertain: use "auto" (let tool decide)

3. **Specify focus areas** (optional):
   - ["academic", "patent"] for technical research
   - ["regulatory", "clinical"] for clinical research
   - ["market", "financial"] for business research

## EXAMPLE

Task: "KRAS G12C 抑制剂的合成路线"
Analysis:
- This is technical synthesis research → needs deep content
- Should check multiple routes → need 15-20 results
- Patents and papers likely contain detailed procedures → use "selective" Jina
- Focus on: ["patent", "academic"]

Call: enhanced_research_tool(
    query="KRAS G12C inhibitor synthesis route",
    max_results=18,
    jina_strategy="selective",
    focus_areas=["patent", "academic"]
)
"""
```

### 方案 C: LLM 直接控制 Jina 选择（最灵活）

在工具返回搜索结果后，让 LLM 直接决定哪些 URL 需要 Jina 读取：

```python
# enhanced_research_tool 返回搜索结果后
# LLM 分析并决定哪些需要深度读取

@function_tool  
async def jina_read_selected(
    ctx: RunContextWrapper[Any],
    urls: List[str],  # LLM 选择的 URLs
    reasons: List[str]  # LLM 提供的原因
) -> str:
    """Read selected URLs with Jina for deep content extraction."""
```

## 推荐实现路径

### 阶段 1: 快速改进（最小改动）
1. 让 `enhanced_research_tool` 接受 `max_results` 参数（LLM 可指定）
2. 在 `SUBAGENT_INSTRUCTIONS` 中添加策略规划指导
3. 保留现有的规则驱动 Jina 选择作为默认

### 阶段 2: 深度改进（完全 LLM 驱动）
1. 实现方案 B 的完整版本
2. 让 LLM 在检索后分析结果，决定 Jina 使用
3. 移除或弱化硬编码规则，作为 fallback

## 对比总结

| 维度 | 当前方案（规则驱动） | 用户预期（LLM 驱动） | 改进难度 |
|------|-------------------|-------------------|---------|
| 检索深度 | 固定 10 个 | LLM 根据任务决定 | ⭐ 简单 |
| Jina 使用 | 硬编码规则 | LLM 分析内容价值 | ⭐⭐ 中等 |
| 聚焦程度 | 固定前 15 个 | LLM 根据相关性决定 | ⭐⭐ 中等 |
| 调用次数 | 固定最多 2 次 | LLM 根据充分性决定 | ⭐ 简单 |

## 下一步行动

1. **确认方案**: 选择方案 A、B 或 C，或组合使用
2. **实现优先级**: 先实现检索深度和调用次数的 LLM 控制（简单）
3. **逐步迁移**: 保留规则作为 fallback，逐步增强 LLM 决策能力
