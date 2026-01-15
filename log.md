
---

### 调小 Jina 深度检索次数

**修改内容：**

1. **`src/clarifyagent/tools/intelligent_research.py` - `create_research_plan` 方法**
   - 将 Jina 深度检索次数上限调小：
     - 简单任务（max_results <= 8）: 从 3 个减少到 **2 个**
     - 标准任务（8 < max_results <= 15）: 从 5 个减少到 **3 个**
     - 复杂任务（max_results > 15）: 从 8 个减少到 **5 个**

**技术细节：**
- 修改位置：第259-264行的 `max_jina_targets` 计算逻辑
- 这样可以减少 Jina API 调用次数，降低成本和执行时间
- 同时保持对不同复杂度任务的合理覆盖

**影响：**
- ✅ 减少了 Jina 深度读取次数，降低 API 成本
- ✅ 缩短了研究任务的执行时间
- ✅ 仍然保持对不同复杂度任务的合理信息覆盖

---

### 修复 Synthesizer 中 time 模块未导入的错误

**问题描述：**
- `synthesizer.py` 在第127和130行使用了 `time.time()`，但没有导入 `time` 模块
- 导致运行时错误：`name 'time' is not defined`

**修改内容：**

1. **`src/clarifyagent/synthesizer.py`**
   - 在文件顶部添加 `import time`（第3行）
   - 修复了 `time.time()` 调用时的未定义错误

**技术细节：**
- 代码在第128行和131行使用 `time.time()` 来计算 LLM 调用的执行时间
- 虽然注释掉的日志代码中有 `import time`，但实际运行的代码中缺少这个导入

**影响：**
- ✅ 修复了 Synthesizer 运行时的 `NameError`
- ✅ 现在可以正确计算 LLM 调用的执行时间

---

### 修复简单任务仍然使用 8 个 Jina 目标的问题

**问题描述：**
- 即使 LLM 指定了较小的 `max_results`（如 6），简单任务仍然会触发 8 个 Jina 深度读取目标
- `intelligent_research.py` 中硬编码了 Jina 目标数量限制（固定 8 个）
- 没有根据任务复杂度或 `max_results` 动态调整

**修改内容：**

1. **`src/clarifyagent/tools/intelligent_research.py` - `create_research_plan` 方法**
   - 添加 `max_results` 参数，用于动态调整 Jina 目标数量
   - 根据 `max_results` 动态调整分析范围：
     - 简单任务（max_results <= 8）: 分析所有结果
     - 复杂任务（max_results > 15）: 分析前 15 个
   - 根据 `max_results` 动态调整 Jina 目标数量上限：
     - 简单任务（max_results <= 8）: 最多 3 个 Jina 目标
     - 标准任务（8 < max_results <= 15）: 最多 5 个 Jina 目标
     - 复杂任务（max_results > 15）: 最多 8 个 Jina 目标
   - 添加日志记录 Jina 目标数量的决定过程

2. **`src/clarifyagent/tools/enhanced_research.py`**
   - 修改 `smart_research` 方法，将 `max_results` 传递给 `create_research_plan`
   - 确保 Jina 目标数量根据 LLM 指定的检索深度动态调整

3. **`src/clarifyagent/agents/subagent.py` - `enhanced_research_tool` 工具定义**
   - 增强参数说明，明确要求 LLM 必须提供 `max_results` 参数
   - 提供具体的数值建议（6, 12, 18, 22）而不是范围
   - 强调 "YOU MUST SPECIFY THIS PARAMETER"

4. **`src/clarifyagent/agents/subagent.py` - `SUBAGENT_INSTRUCTIONS`**
   - 在工作流程中明确要求 LLM 必须提供 `max_results` 参数
   - 提供具体的调用示例

**技术细节：**
- Jina 目标数量现在根据 `max_results` 动态调整，而不是固定 8 个
- 简单任务（max_results=6）现在最多使用 3 个 Jina 目标，而不是 8 个
- 保持了向后兼容性，如果 `max_results` 未指定，使用默认值 10，对应最多 5 个 Jina 目标

**影响：**
- ✅ 简单任务现在使用更少的 Jina 深度读取（最多 3 个而不是 8 个）
- ✅ 减少了简单任务的成本和执行时间
- ✅ Jina 目标数量现在与任务复杂度匹配
- ✅ LLM 通过指定 `max_results` 可以间接控制 Jina 使用量

---

### 增强 LLM 对多次搜索和检索深度的完全控制

**问题描述：**
- 用户希望 LLM 能够根据实际需要决定是否进行多次搜索
- LLM 应该能够决定进行多少次检索，直到觉得有足够的信息
- 需要让 LLM 完全控制整个检索流程，而不是受固定规则限制

**修改内容：**

1. **`src/clarifyagent/agents/subagent.py` - SUBAGENT_INSTRUCTIONS**
   - 重写"RESEARCH STRATEGY PLANNING"章节，强调 LLM 的完全控制权
   - 添加"迭代搜索策略"（Iterative Search Strategy）：
     - LLM 应该持续搜索直到信息充分
     - 提供明确的信息充分性评估框架
     - 说明何时停止（sufficient）vs 何时继续（insufficient）
     - 移除硬性限制，强调效率原则
   - 改进工作流程为三个阶段：
     - Phase 1: 初始规划
     - Phase 2: 迭代搜索循环（无硬性次数限制）
     - Phase 3: 提取和返回
   - 增强工具输出格式说明，帮助 LLM 评估信息充分性

2. **`src/clarifyagent/tools/enhanced_research.py`**
   - 移除源数量限制（之前限制为 12 个）
   - 返回所有 sources，让 LLM 决定使用哪些
   - 添加 `search_metadata` 字段，提供更多上下文信息：
     - `num_search_results`: 搜索结果数量
     - `num_jina_reads`: Jina 深度读取数量
     - `scenario`: 检测到的研究场景

3. **`src/clarifyagent/agents/subagent.py` - enhanced_research_tool**
   - 在返回的 JSON 中添加 `search_metadata` 和 `performance` 字段
   - 帮助 LLM 更好地评估搜索结果的质量和充分性

**核心改进：**

1. **完全由 LLM 控制**：
   - 无硬性调用次数限制
   - LLM 根据信息充分性决定是否继续
   - LLM 可以调整每次搜索的 max_results

2. **明确的信息充分性评估框架**：
   - ✅ 充分的条件：confidence >= 0.7 AND 关键信息完整 AND 可以回答问题
   - ❌ 不充分的条件：confidence < 0.5 OR 缺少关键信息 OR 无法回答问题

3. **迭代搜索循环**：
   - 每次搜索后评估
   - 如果充分 → 停止并返回
   - 如果不充分 → 继续搜索（可调整查询和深度）

4. **效率原则**：
   - 简单任务通常 1-2 次调用
   - 标准任务通常 1-3 次调用
   - 复杂任务可能需要更多，但每次都要评估

**影响：**
- ✅ LLM 现在完全控制搜索次数和深度
- ✅ 简单任务可以快速完成（1 次调用）
- ✅ 复杂任务可以充分检索（多次调用直到信息充分）
- ✅ 更智能、更灵活的研究策略
- ✅ 移除硬编码限制，让 LLM 根据实际情况决策

---

### 实现检索深度和调用次数的 LLM 控制

**问题描述：**
- 当前检索深度固定为 10 个结果，无法根据任务复杂度调整
- 工具调用次数固定为最多 2 次，无法根据信息充分性灵活调整
- 用户希望由 LLM 根据任务内容智能决定检索策略

**修改内容：**

1. **`src/clarifyagent/agents/subagent.py`**
   - 修改 `enhanced_research_tool` 函数，添加 `max_results` 参数（可选）
   - LLM 可以根据任务复杂度指定检索深度（5-25 个结果）
   - 如果 LLM 不指定，使用默认值 `MAX_SEARCH_RESULTS`

2. **`src/clarifyagent/agents/subagent.py` - SUBAGENT_INSTRUCTIONS**
   - 添加"RESEARCH STRATEGY PLANNING"章节，指导 LLM 如何规划检索策略
   - **检索深度决策指南**：
     - 简单事实查询：5-8 个结果
     - 标准研究：10-15 个结果
     - 综合分析：15-20 个结果
     - 深度调研：20-25 个结果
   - **工具调用策略**：
     - 移除固定的"最多 2 次"限制
     - 让 LLM 根据信息充分性决定是否需要多次调用
     - 提供决策流程：评估 confidence、信息完整性、源质量
     - 强调效率原则：如果第一次调用已足够（confidence > 0.7），直接提取结果

3. **工作流程改进**：
   - 步骤 1：规划研究策略（分析复杂度、决定 max_results）
   - 步骤 2：首次搜索调用
   - 步骤 3：评估结果（confidence、完整性、质量）
   - 步骤 4：决定是否需要更多搜索
   - 步骤 5：提取和返回结果

**技术细节：**
- `max_results` 参数是可选的，向后兼容
- LLM 可以根据任务内容动态调整检索深度
- LLM 可以根据信息充分性决定调用次数，不再受固定限制
- 保留效率原则，避免不必要的调用

**影响：**
- ✅ 简单任务使用更少的检索结果，提高效率
- ✅ 复杂任务可以使用更多结果，提高信息覆盖
- ✅ LLM 可以根据实际需要决定是否进行多次搜索
- ✅ 更智能、更灵活的检索策略

**下一步计划：**
- 实现 Jina 使用判断的 LLM 控制（中等难度）
- 实现聚焦程度的 LLM 控制（中等难度）

---

### 添加表格自动规划功能

**问题描述：**
- 用户希望在总结报告时能够自动规划和使用表格
- 需要让 LLM 根据检索到的内容自动判断何时使用表格，并设计表格结构

**修改内容：**

1. **`src/clarifyagent/prompts.py`**
   - 在 `SYNTHESIZER_SYSTEM_PROMPT` 中添加了"表格使用指南"章节
   - 指导 LLM 在以下场景自动使用表格：
     - 对比分析（3个或以上实体的多维度对比）
     - 结构化数据（明确列结构的数据）
     - 多维度信息（每个实体有2个或以上可对比属性）
     - 数据汇总（数值、日期、阶段等结构化信息）
   - 提供了表格格式规范和设计原则
   - 包含表格使用示例（产品对比、临床数据汇总等）
   - 在 Quality Checklist 中添加表格使用检查项

**技术细节：**
- 采用 Prompt 指导方式，让 LLM 根据内容深度自动判断
- 不进行代码层面的预处理，完全由 LLM 智能决策
- 表格格式使用标准 Markdown 表格语法
- 表格中的引用使用内联格式 `[[site](url)]`
- 表格前添加说明文字，表格后可添加分析文字

**表格使用场景：**
- 产品/药物对比（疗效、安全性、价格等）
- 公司/企业对比（市场份额、管线数量等）
- 临床数据汇总（多个试验的数据对比）
- 研发管线对比（阶段、适应症、公司等）
- 市场数据（市场份额、增长率等）
- 技术参数对比（多个技术方案的参数）

**影响：**
- LLM 现在会自动识别适合表格的内容并生成表格
- 报告中的对比分析将更加清晰易读
- 结构化数据展示更加专业

---

### 修复 Planner 中的 Agent model 类型错误

**问题描述：**
- 错误：`TypeError: Agent model must be a string, Model, or None, got AnthropicModel`
- `planner.py` 中的 `build_planner` 函数直接使用了 `AnthropicModel` 对象
- `agents` 框架的 `Agent` 类不接受 `AnthropicModel` 对象

**修复内容：**

1. **`src/clarifyagent/planner.py`**
   - 导入 `LitellmModel`
   - 修改 `build_planner` 函数，使用 `LitellmModel` 包装器
   - 传递 `anthropic/{model.model}` 格式的模型名称和 API key

**技术细节：**
- `agents` 框架通过 litellm 处理模型调用
- litellm 需要 `LitellmModel` 对象或模型名称字符串
- 使用 `LitellmModel` 包装器确保兼容性

**影响：**
- Planner 现在可以正确工作
- 不再出现 `TypeError` 错误


---

### 添加 Deepseek LLM 支持

**问题描述：**
- 需要添加 Deepseek 作为 LLM 选择
- 需要在 config 中控制，允许只走 Deepseek 或 Claude

**修改内容：**

1. **`src/clarifyagent/deepseek_model.py`** (新建)
   - 创建 `DeepseekModel` 类，实现与 `AnthropicModel` 兼容的接口
   - 实现 `acompletion` 和 `completion` 方法
   - 创建 `build_deepseek_model` 函数，支持不同的模型类型（fast, quality, clarifier, planner, executor, synthesizer）

2. **`src/clarifyagent/config.py`**
   - 添加 `LLM_PROVIDER` 配置选项（支持 "claude" 和 "deepseek"）
   - 添加 Deepseek 相关的模型配置：
     - `DEEPSEEK_CLARIFIER_MODEL`
     - `DEEPSEEK_PLANNER_MODEL`
     - `DEEPSEEK_EXECUTOR_MODEL`
     - `DEEPSEEK_SYNTHESIZER_MODEL`
     - `DEEPSEEK_FAST_MODEL`
     - `DEEPSEEK_QUALITY_MODEL`
   - 添加 `get_litellm_model_config` 辅助函数，根据 `LLM_PROVIDER` 返回正确的 litellm 模型格式和 API key

3. **`src/clarifyagent/agent.py`**
   - 修改 `build_model` 函数，根据 `LLM_PROVIDER` 配置选择使用 Deepseek 或 Claude
   - 更新返回类型为 `Union[AnthropicModel, DeepseekModel]`
   - 导入 `DeepseekModel` 和 `Union` 类型

4. **`src/clarifyagent/planner.py`**
   - 更新类型注解，支持 `Union[AnthropicModel, DeepseekModel]`
   - 使用 `get_litellm_model_config` 获取正确的模型格式和 API key

5. **`src/clarifyagent/synthesizer.py`**
   - 更新类型注解，支持 `Union[AnthropicModel, DeepseekModel]`
   - 使用 `get_litellm_model_config` 获取正确的模型格式和 API key

6. **`src/clarifyagent/executor.py`**
   - 更新类型注解，支持 `Union[AnthropicModel, DeepseekModel]`

7. **`src/clarifyagent/clarifier.py`**
   - 移除 `AnthropicModel` 类型注解，改为通用类型

8. **`src/clarifyagent/agents/subagent.py`**
   - 更新类型注解，支持 `Union[AnthropicModel, DeepseekModel]`
   - 使用 `get_litellm_model_config` 获取正确的模型格式和 API key

9. **`src/clarifyagent/agents/pool.py`**
   - 更新类型注解，支持 `Union[AnthropicModel, DeepseekModel]`

10. **`src/clarifyagent/orchestrator.py`**
    - 更新类型注解，支持 `Union[AnthropicModel, DeepseekModel]`（不再使用 `LitellmModel`）

**技术细节：**
- Deepseek API 使用 OpenAI SDK，base_url 为 "https://api.deepseek.com"
- 通过环境变量 `LLM_PROVIDER` 控制使用哪个 LLM 提供商（默认 "claude"）
- 所有模型相关的函数都支持两种模型类型
- `get_litellm_model_config` 函数根据 `LLM_PROVIDER` 返回正确的 litellm 格式（`anthropic/{model}` 或 `deepseek/{model}`）

**使用方法：**
- 设置环境变量 `LLM_PROVIDER=deepseek` 使用 Deepseek
- 设置环境变量 `LLM_PROVIDER=claude` 使用 Claude（默认）
- 确保设置了相应的 API key（`DEEPSEEK_API_KEY` 或 `ANTHROPIC_API_KEY`）

**影响：**
- 现在可以通过配置选择使用 Deepseek 或 Claude
- 所有模块都支持两种 LLM 提供商
- 向后兼容，默认使用 Claude

---

### 修复确认逻辑和 Executor 未定义问题

**问题描述：**
1. 错误：`UnboundLocalError: cannot access local variable 'Executor' where it is not associated with a value`
2. 用户点击一次确认后还需要再次确认

**修复内容：**

1. **`src/clarifyagent/web.py` - 修复导入顺序**
   - 将 `Executor`、`assess_input`、`decompose_task`、`synthesize_results` 等导入移到函数开头
   - 避免在使用前未导入的问题

2. **`src/clarifyagent/web.py` - 修复确认分支中的 model 变量**
   - 在确认分支中定义 `model = build_model()`
   - 确保 `Executor` 可以使用 `model`

3. **`src/clarifyagent/web.py` - 优化确认逻辑**
   - 确保确认消息不会被误判为澄清回复
   - 在澄清回复处理中添加 `not is_confirmation(user_message)` 检查

4. **`src/clarifyagent/planner.py` - 修复 Agent model 类型错误**
   - 导入 `LitellmModel`
   - 修改 `build_planner` 函数，使用 `LitellmModel` 包装器
   - 传递 `anthropic/{model.model}` 格式的模型名称和 API key

**技术细节：**
- 确认逻辑优先于澄清回复处理
- 所有模块导入在函数开头完成
- 使用 `LitellmModel` 包装器确保与 `agents` 框架兼容

**影响：**
- 确认后直接开始研究，不再需要再次确认
- 不再出现 `UnboundLocalError` 和 `TypeError` 错误

