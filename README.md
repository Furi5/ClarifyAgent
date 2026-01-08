# Deep Research

专注深度研究的 AI Agent，通过多智能体协作完成复杂研究任务。

## 特性

- **智能澄清** - 研究前确认用户需求，确保研究方向正确
- **多智能体协作** - Clarifier → Planner → Executor → Synthesizer 流水线
- **并行检索** - 多个研究方向同时执行，大幅缩短研究时间
- **动态报告** - 根据问题类型自动选择最佳报告结构
- **实时进度** - SSE 流式传输研究进度

## 架构

```
用户输入
    ↓
┌─────────────┐
│  Clarifier  │  评估信息充分性，生成澄清问题
└─────────────┘
    ↓
┌─────────────┐
│   Planner   │  分析研究需求，规划研究方向
└─────────────┘
    ↓
┌─────────────┐
│  Executor   │  并行执行多个子任务搜索
└─────────────┘
    ↓
┌─────────────┐
│ Synthesizer │  综合分析，生成研究报告
└─────────────┘
    ↓
研究报告
```

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
export DEEPSEEK_API_KEY="your-api-key"
export SERPER_API_KEY="your-serper-key"
export JINA_API_KEY="your-jina-key"
```

### 3. 启动 Web 服务

```bash
uv run python run_web.py
```

打开浏览器访问 http://localhost:8080

### 4. 命令行模式

```bash
uv run python run_cli.py
```

## 示例查询

- "KRAS G12C 靶点的最新研究进展"
- "GLP-1 激动剂的市场竞争格局"
- "Keytruda 在美国的首次获批日期和适应症"
- "STAT6小分子抑制剂的开发现状"

## 技术栈

- **LLM**: DeepSeek (via LiteLLM)
- **Agent 框架**: OpenAI Agents SDK
- **Web 框架**: FastAPI
- **搜索**: SerpAPI
- **网页解析**: Jina AI

## 配置

主要配置在 `src/clarifyagent/config.py`:

```python
MODEL_NAME = "deepseek-chat"           # LLM 模型
MAX_PARALLEL_SUBAGENTS = 5             # 最大并行子任务数
MAX_CONTENT_CHARS = 3000               # 单次内容最大字符数
MAX_SEARCH_RESULTS = 3                 # 搜索结果数量
```

## 项目结构

```
src/clarifyagent/
├── clarifier.py      # 澄清模块 - 评估输入充分性
├── planner.py        # 规划模块 - 分解研究任务
├── executor.py       # 执行模块 - 管理并行搜索
├── synthesizer.py    # 综合模块 - 生成研究报告
├── orchestrator.py   # 编排层 - 协调各模块
├── web.py            # Web API
├── agents/           # 子智能体
│   ├── subagent.py   # 搜索子智能体
│   └── pool.py       # 子智能体池
└── tools/            # 工具
    ├── serperapi.py  # 搜索工具
    └── jina.py       # 网页解析工具
```

## License

MIT
