# 测试指南

## 澄清模块测试

### 快速测试（推荐）

运行简单的交互式测试脚本：

```bash
# 确保设置了环境变量
export DEEPSEEK_API_KEY=your_api_key

# 运行简单测试
python tests/test_clarifier_simple.py
```

这个脚本会：
- 测试多个示例输入
- 显示评估结果（action、confidence、goal、research_focus）
- 显示决策函数的结果
- 显示澄清问题（如果需要）

### 使用 pytest 运行测试

```bash
# 安装测试依赖（如果还没安装）
uv sync --dev

# 运行所有测试
pytest tests/

# 运行特定测试文件
pytest tests/test_clarifier.py

# 运行特定测试类
pytest tests/test_clarifier.py::TestClarifierDecisionLogic

# 运行特定测试函数
pytest tests/test_clarifier.py::TestClarifierDecisionLogic::test_should_clarify_low_confidence

# 显示详细输出
pytest tests/test_clarifier.py -v

# 显示 print 输出
pytest tests/test_clarifier.py -s
```

### 测试分类

#### 1. 单元测试（不需要 API）

测试决策逻辑函数：

```bash
pytest tests/test_clarifier.py::TestClarifierDecisionLogic -v
```

这些测试：
- 不依赖 API
- 运行速度快
- 测试 `should_clarify()` 和 `should_start_research()` 函数

#### 2. 集成测试（需要 API key）

测试实际的澄清评估：

```bash
pytest tests/test_clarifier.py::TestClarifierIntegration -v
```

这些测试：
- 需要 DEEPSEEK_API_KEY
- 会调用实际的 LLM API
- 测试真实的澄清决策

#### 3. 示例测试（需要 API key）

测试设计文档中的示例：

```bash
pytest tests/test_clarifier.py::TestClarifierExamples -v
```

### 测试用例说明

#### 应该直接开始研究（START_RESEARCH）
- "KRAS G12C 靶点" - 主题明确，可推断研究重点
- "GLP-1 激动剂最新进展" - 主题和目标都明确

#### 需要澄清（NEED_CLARIFICATION）
- "帮我研究一下" - 主题缺失
- "那个新药" - 主题不明确

#### 需要确认计划（CONFIRM_PLAN）
- "GLP-1 激动剂" - 主题明确但目标不明确

### 环境变量

测试需要以下环境变量：

```bash
export DEEPSEEK_API_KEY=your_api_key
export DEEPSEEK_BASE_URL=https://api.deepseek.com  # 可选，默认值
```

### 调试测试

如果测试失败，可以：

1. **查看详细错误信息**：
```bash
pytest tests/test_clarifier.py -v -s
```

2. **运行交互式测试**：
```bash
python tests/test_clarifier_simple.py
```

3. **在代码中添加调试输出**：
```python
print(f"[DEBUG] Plan: {plan.model_dump()}")
```

### 测试覆盖率

查看测试覆盖率：

```bash
# 安装 coverage
pip install coverage

# 运行测试并生成覆盖率报告
coverage run -m pytest tests/test_clarifier.py
coverage report
coverage html  # 生成 HTML 报告
```

### 常见问题

1. **API key 未设置**：
   - 确保设置了 DEEPSEEK_API_KEY 环境变量
   - 或在 .env 文件中设置

2. **测试超时**：
   - 集成测试可能需要较长时间（每个测试几秒）
   - 可以增加 pytest 超时时间：`pytest --timeout=30`

3. **JSON 解析错误**：
   - LLM 可能返回格式不正确的 JSON
   - 检查 clarifier.py 中的 `_extract_json` 函数
