
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

