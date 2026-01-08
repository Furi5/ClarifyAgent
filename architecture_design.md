# Deep Research Agent 架构设计（基于行业最佳实践）

## 一、整体架构设计

### 1.1 核心架构模式

```
┌─────────────────────────────────────────────────────────────┐
│                  Deep Research Agent                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐│
│  │  Clarifier   │ →   │   Planner    │ →   │   Executor   ││
│  │  (轻量级)    │     │  (Orchestrator)│    │  (Workers)   ││
│  │              │     │              │     │              ││
│  │ - 意图理解   │     │ - 任务分解   │     │ - 并行搜索   ││
│  │ - 槽位填充   │     │ - 策略选择   │     │ - 结果评估   ││
│  │ - 澄清决策   │     │ - 资源分配   │     │ - 迭代优化   ││
│  │ - 置信度评估 │     │ - 子任务分配 │     │              ││
│  └──────────────┘     └──────┬───────┘     └──────┬───────┘│
│                               │                    │        │
│                               ▼                    │        │
│                    ┌──────────────────┐            │        │
│                    │  Subagent Pool   │◄──────────┘        │
│                    │  (Worker Agents) │                     │
│                    │                  │                     │
│                    │  - Subagent 1   │                     │
│                    │  - Subagent 2   │                     │
│                    │  - Subagent N   │                     │
│                    └──────────────────┘                     │
│                               │                             │
│                               ▼                             │
│                    ┌──────────────────┐                     │
│                    │   Synthesizer    │                     │
│                    │                  │                     │
│                    │ - 信息综合       │                     │
│                    │ - 冲突解决       │                     │
│                    │ - 引用标注       │                     │
│                    │ - 报告生成       │                     │
│                    └──────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 模块职责划分

#### Clarifier（澄清模块）
- **模型**：DeepSeek-chat（轻量级，成本低）
- **职责**：
  - 理解用户意图
  - 评估信息充分性（置信度）
  - 决定是否需要澄清
  - 生成澄清问题（提供选项）

#### Planner（规划模块 / Orchestrator）
- **模型**：DeepSeek-reasoner（复杂推理）
- **职责**：
  - 任务分解（将复杂问题拆成子问题）
  - 识别可并行任务
  - 分配子任务给 Subagents
  - 动态调整策略
  - 决定何时停止

#### Executor（执行模块 / Workers）
- **模型**：DeepSeek-chat（并行执行）
- **职责**：
  - 并行执行搜索任务
  - 评估搜索结果质量
  - 迭代优化查询
  - 先广后深策略

#### Synthesizer（综合模块）
- **模型**：DeepSeek-reasoner（综合推理）
- **职责**：
  - 综合多个 Subagent 的结果
  - 解决信息冲突
  - 添加引用标注
  - 生成最终报告

---

## 二、澄清模块设计（Clarifier）

### 2.1 澄清的黄金法则

1. **只问真正影响检索方向的问题**
   - ❌ 不问："您想研究什么？"（太宽泛）
   - ✅ 问："您想研究 KRAS G12C 的哪个方面？A) 靶点验证 B) 已上市药物 C) 临床进展"

2. **提供选项而非开放问题**
   - ❌ 开放问题：用户需要思考，容易偏离
   - ✅ 选项：降低认知负担，引导方向

3. **最多问 3-5 个问题**
   - 超过 5 个问题用户会疲劳
   - 设置最大澄清轮次（建议 3 轮）

4. **展示计划让用户确认（Gemini 模式）**
   - 对于高置信度但需要确认的情况
   - 展示推断的计划，让用户确认或调整

### 2.2 澄清决策逻辑

```python
def should_clarify(plan: Plan) -> bool:
    """决定是否需要澄清"""
    confidence = plan.confidence
    
    # 硬边界：必须澄清
    if confidence < 0.6:
        return True
    
    # 软边界：有关键槽位缺失
    if confidence < 0.85 and has_missing_slots(plan):
        return True
    
    # 高置信度：直接执行，结果覆盖多种解读
    return False

def clarification_strategy(plan: Plan) -> str:
    """选择澄清策略"""
    if plan.confidence < 0.6:
        return "MUST_CLARIFY"  # 必须澄清
    elif plan.confidence < 0.85:
        return "CONFIRM_PLAN"   # 展示计划确认
    else:
        return "START_RESEARCH" # 直接执行
```

### 2.3 澄清问题生成原则

**原则 1：一次澄清一个关键点**
- 避免信息过载
- 保持对话流畅

**原则 2：提供 3-5 个选项**
- 选项要互斥且覆盖主要方向
- 最后一个选项："其他（请说明）"

**原则 3：基于领域知识推断选项**
- 不要问"您想研究什么"
- 要问"您想研究 [主题] 的哪个方面？"

**示例：**

```json
{
  "next_action": "NEED_CLARIFICATION",
  "clarification": {
    "question": "您想研究 KRAS G12C 的哪个方面？",
    "options": [
      "靶点验证证据与机制",
      "已上市/在研抑制剂",
      "临床管线进展",
      "耐药机制与克服策略",
      "其他（请说明）"
    ],
    "missing_info": "研究重点",
    "context": "基于 KRAS G12C 靶点研究的常见方向"
  }
}
```

---

## 三、规划检索模块设计（Planner + Executor）

### 3.1 Plan-and-Execute 架构

**核心思想**：先生成完整计划，再执行（而非纯 ReAct）

```
用户输入
  ↓
Clarifier 评估
  ↓
Planner 生成完整计划
  ├─ 任务分解（子问题列表）
  ├─ 识别可并行任务
  ├─ 分配资源（Subagent 数量）
  └─ 设置完成条件
  ↓
Executor 并行执行
  ├─ Subagent 1: 搜索子问题 1
  ├─ Subagent 2: 搜索子问题 2
  └─ Subagent N: 搜索子问题 N
  ↓
Synthesizer 综合结果
```

### 3.2 任务分解原则

**原则 1：分解是关键**
- 将复杂问题拆成可独立回答的子问题
- 每个子问题对应一个 research_focus

**原则 2：识别可并行任务**
- 能并行的任务不要串行
- 并行度 = min(子任务数, 最大 Subagent 数)

**原则 3：先广后深**
- 从宽泛查询开始
- 评估可用信息后再细化

**示例：**

```python
# 用户输入："KRAS G12C 靶点"
# Planner 分解：

plan = {
    "goal": "KRAS G12C 靶点研究",
    "research_focus": [
        "KRAS G12C 靶点验证证据",
        "KRAS G12C 已上市/在研抑制剂",
        "KRAS G12C 临床管线进展",
        "KRAS G12C 耐药机制"
    ],
    "subtasks": [
        {
            "id": 1,
            "focus": "靶点验证证据",
            "queries": ["KRAS G12C target validation", "KRAS G12C mechanism"],
            "parallel": True
        },
        {
            "id": 2,
            "focus": "已上市/在研抑制剂",
            "queries": ["KRAS G12C inhibitors", "KRAS G12C drugs"],
            "parallel": True
        },
        {
            "id": 3,
            "focus": "临床管线进展",
            "queries": ["KRAS G12C clinical trials", "KRAS G12C pipeline"],
            "parallel": True
        },
        {
            "id": 4,
            "focus": "耐药机制",
            "queries": ["KRAS G12C resistance", "KRAS G12C resistance mechanisms"],
            "parallel": True
        }
    ],
    "max_parallel": 4  # 可以并行执行
}
```

### 3.3 按复杂度扩展资源

**资源分配策略：**

| 复杂度 | Subagent 数 | 每个 Agent 工具调用 | 总 Token 估算 |
|--------|------------|-------------------|--------------|
| 简单事实查询 | 1 | 3-10 次 | 1x |
| 直接对比 | 2-4 | 10-15 次 | 4-8x |
| 复杂研究 | 5-10 | 15-20 次 | 15-20x |

**决策逻辑：**

```python
def allocate_resources(plan: Plan) -> dict:
    """根据复杂度分配资源"""
    num_focus = len(plan.research_focus)
    
    if num_focus <= 2:
        # 简单任务：单 Agent
        return {
            "num_subagents": 1,
            "max_tool_calls": 10
        }
    elif num_focus <= 4:
        # 中等任务：2-4 个 Subagent
        return {
            "num_subagents": num_focus,
            "max_tool_calls": 15
        }
    else:
        # 复杂任务：5-10 个 Subagent
        return {
            "num_subagents": min(num_focus, 10),
            "max_tool_calls": 20
        }
```

### 3.4 并行工具调用策略

**核心原则：**
- Lead Agent 同时启动 3-5 个 Subagent
- Subagent 同时使用 3+ 工具
- 复杂查询研究时间减少 90%

**实现：**

```python
async def execute_parallel_search(plan: Plan):
    """并行执行搜索"""
    subtasks = plan.subtasks
    num_parallel = min(len(subtasks), plan.max_parallel)
    
    # 创建 Subagent pool
    subagents = [create_subagent(i) for i in range(num_parallel)]
    
    # 并行执行
    results = await asyncio.gather(*[
        subagent.search(subtask) 
        for subagent, subtask in zip(subagents, subtasks)
    ])
    
    return results
```

### 3.5 教会 Orchestrator 如何委派

**每个 Subagent 需要的信息：**

1. **目标**：明确的任务目标
2. **输出格式**：期望的输出格式
3. **工具/来源指引**：使用哪些工具，从哪里获取信息
4. **任务边界**：什么该做，什么不该做

**示例 Subagent 指令：**

```python
subagent_instructions = """
你是一个专门研究 {focus} 的 Subagent。

任务目标：
- 深入研究：{focus}
- 生成查询：{queries}
- 搜索来源：学术论文、专利、新闻、临床数据

输出格式：
{
    "focus": "{focus}",
    "key_findings": ["发现1", "发现2", ...],
    "sources": [
        {"title": "...", "url": "...", "snippet": "..."},
        ...
    ],
    "confidence": 0.0-1.0
}

任务边界：
- ✅ 专注于 {focus}
- ❌ 不要偏离到其他 focus
- ✅ 优先高质量来源（Nature, Science, PubMed）
- ❌ 不要重复其他 Subagent 的工作
"""
```

---

## 四、工具设计原则

### 4.1 工具描述质量至关重要

**原则：**
- 工具描述质量直接影响 Agent 决策
- 用 LLM 自动改进工具描述（40% 效率提升）

**示例：**

```python
# ❌ 差的工具描述
@function_tool
def search(query: str) -> str:
    """搜索信息"""
    pass

# ✅ 好的工具描述
@function_tool
def search_academic(query: str, max_results: int = 10) -> List[Dict]:
    """
    搜索学术论文和研究成果。
    
    参数：
    - query: 搜索查询，应包含关键词和领域限定（如 "KRAS G12C inhibitor clinical trial"）
    - max_results: 最大结果数，默认 10
    
    返回：
    - List[Dict]: 包含 title, authors, journal, year, abstract, url 的论文列表
    
    使用场景：
    - 查找特定主题的学术研究
    - 获取最新的研究成果
    - 查找特定药物的临床数据
    
    注意事项：
    - 查询应具体，避免过于宽泛
    - 优先返回高影响因子期刊的论文
    """
    pass
```

### 4.2 工具分类

**按来源分类：**
- `search_academic`: 学术论文（PubMed, arXiv）
- `search_patent`: 专利（USPTO, EPO）
- `search_news`: 新闻（Google News）
- `search_clinical`: 临床数据（ClinicalTrials.gov）

**按功能分类：**
- `web_search`: 通用网络搜索
- `read_url`: 读取网页内容
- `extract_citations`: 提取引用信息

### 4.3 避免运行中动态增减工具

- 工具集应在启动时确定
- 避免 Agent 自己创建工具
- 保持工具接口稳定

---

## 五、综合模块设计（Synthesizer）

### 5.1 信息综合策略

**步骤：**

1. **收集所有 Subagent 结果**
2. **去重和合并**
3. **解决冲突**（不同来源的冲突信息）
4. **按 research_focus 组织**
5. **添加引用标注**
6. **生成最终报告**

### 5.2 冲突解决策略

**策略：**
- 优先高权威来源（Nature > 普通期刊 > 新闻）
- 时间优先（最新信息优先）
- 多源验证（多个来源一致的信息更可信）

### 5.3 引用标注

**要求：**
- 每个关键信息都要有来源
- 引用格式统一（如 Markdown 格式）
- 包含 URL、标题、作者、日期

---

## 六、性能优化

### 6.1 Token 使用优化

**多智能体 Token 使用：**
- 单 Agent：1x
- 多智能体：15x

**优化策略：**
- 简单任务用单 Agent
- 复杂任务才用多智能体
- 合理设置 max_tool_calls

### 6.2 并行优化

**并行度设置：**
- Lead Agent 同时启动 3-5 个 Subagent
- Subagent 同时使用 3+ 工具
- 使用 asyncio 实现真正的并行

### 6.3 缓存策略

**缓存内容：**
- 搜索结果（避免重复搜索）
- 网页内容（避免重复读取）
- 工具调用结果

---

## 七、实施路线图

### 阶段 1：基础架构（MVP）
1. ✅ Clarifier 模块（澄清决策）
2. ✅ Planner 模块（任务分解）
3. ✅ Executor 模块（单 Agent 执行）
4. ✅ Synthesizer 模块（结果综合）

### 阶段 2：多智能体（V1.0）
1. 实现 Subagent Pool
2. 实现并行执行
3. 优化资源分配

### 阶段 3：优化（V1.1）
1. 工具描述自动优化
2. 缓存机制
3. 性能监控

### 阶段 4：增强（V2.0）
1. 动态策略调整
2. 用户反馈学习
3. 结果质量评估

---

## 八、关键决策点

### Q1: 何时用多智能体？
**答案：**
- 任务价值高，值得花更多 token
- 大量可并行的子任务（≥3 个 research_focus）
- 信息量超出单一上下文窗口
- 需要与多个复杂工具交互

### Q2: 澄清的阈值？
**答案：**
- confidence < 0.6：必须澄清
- 0.6 ≤ confidence < 0.85：可选澄清（展示计划）
- confidence ≥ 0.85：直接执行

### Q3: 最大澄清轮次？
**答案：**
- 建议 3 轮
- 超过后使用最佳猜测

### Q4: Subagent 数量？
**答案：**
- 简单任务：1 个
- 中等任务：2-4 个
- 复杂任务：5-10 个
- 最大不超过 10 个（避免过度并行）

---

## 九、总结

**核心设计原则：**
1. ✅ 澄清模块：轻量级，只问关键问题
2. ✅ 规划模块：Plan-and-Execute，先规划再执行
3. ✅ 执行模块：并行执行，先广后深
4. ✅ 综合模块：多源验证，引用标注

**性能目标：**
- 简单任务：1-2 分钟
- 中等任务：3-5 分钟
- 复杂任务：5-10 分钟

**质量目标：**
- 事实准确性：>90%
- 引用准确性：>95%
- 完整性：覆盖所有 research_focus
