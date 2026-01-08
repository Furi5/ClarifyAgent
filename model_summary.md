# 🤖 ClarifyAgent 模型配置

## 🎯 **模型分层策略**

### **快速模型 (Tool Calling)**
- **模型**: `openrouter/anthropic/claude-4.5-sonnet`
- **用途**: 工具调用决策、子任务执行
- **优势**: 快速响应、成本效率高
- **使用场景**: 
  - Clarifier（需求分析）
  - Planner（任务分解）
  - Executor（信息检索）
  - Subagents（并行研究）

### **高质量模型 (Synthesis)**
- **模型**: `openrouter/anthropic/claude-opus-4.5`
- **用途**: 最终报告生成、复杂分析
- **优势**: 最高质量输出、最深度分析
- **使用场景**:
  - Synthesizer（最终报告生成）
  - 复杂研究任务的总结

## 🔧 **技术配置**

### **API 配置**
- **Provider**: OpenRouter
- **Base URL**: `https://openrouter.ai/api/v1`
- **API Key**: `OPENROUTER_API_KEY` (已配置)

### **模型映射**
```python
# 智能模型选择
def build_model(model_type):
    if model_type == "fast":
        return "anthropic/claude-sonnet-4.5"  # 工具调用
    elif model_type == "quality": 
        return "anthropic/claude-opus-4.5"    # 高质量生成
```

## 🚀 **性能优化**

### **并行处理能力**
- **子代理数量**: 最多5个并行
- **快速模型**: 处理多个工具调用
- **智能聚合**: 高质量模型整合结果

### **成本效率**
- **90%工具调用**: Sonnet-4.5（成本更低）
- **10%最终生成**: Opus-4.5（质量最高）
- **智能选择**: 根据任务复杂度自动分配

## 🎯 **预期效果**

### **研究质量提升**
- ✅ **深度分析**: Opus在最终报告中提供更深入的洞察
- ✅ **技术准确性**: Claude系列在专业领域表现优异
- ✅ **逻辑严密**: 更好的推理和分析能力

### **响应速度优化**
- ✅ **工具调用**: Sonnet快速处理搜索和信息提取
- ✅ **并行效率**: 多个Sonnet实例同时工作
- ✅ **整体时间**: 总体研究时间预计保持在30-45秒

### **专业场景适配**
- 🧪 **逆合成路线**: 更准确的化学分析
- 💼 **管线评估**: 更精准的商业洞察  
- 🏥 **临床研究**: 更专业的医学分析
- 📊 **市场分析**: 更深入的竞争格局分析