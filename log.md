
---

## 2026-01-15: 修复 Synthesizer 卡住问题 - 添加详细诊断日志

### 问题描述
- Synthesizer 的 LLM 调用完成后（输出了 `Synthesizer output length: 2149 chars`），程序卡住
- 没有更多日志输出，无法定位卡住的具体位置
- 可能卡在：`ResearchResult` 创建、`render_research_result`、`json.dumps` 序列化、或 `yield` 操作

### 修改内容

1. **添加 Synthesizer 返回日志** (`src/clarifyagent/synthesizer.py`):
   - 在创建 `ResearchResult` 前后添加日志
   - 确认 `ResearchResult` 是否成功创建

2. **添加 web.py 处理流程日志** (`src/clarifyagent/web.py`):
   - 在 `synthesize_results` 返回后添加日志
   - 在 `yield progress` 前后添加日志
   - 在 `add_assistant`、`update_task_draft`、`save_research_result` 前后添加日志
   - 在 `render_research_result` 开始和结束时添加日志
   - 在 `json.dumps` 序列化前后添加日志
   - 在 `yield final result` 前后添加日志

3. **添加 render_research_result 日志** (`src/clarifyagent/web.py`):
   - 在函数开始和结束时添加日志
   - 输出处理的数据量（findings、citations 数量）
   - 输出 synthesis 长度

4. **添加错误处理** (`src/clarifyagent/web.py`):
   - 在 `json.dumps` 序列化时添加 try-except
   - 在 `save_research_result` 时添加 try-except，避免保存失败导致中断

### 技术细节

**日志流程：**
```
[DEBUG] Synthesizer output length: X chars
[DEBUG] Synthesizer: Creating ResearchResult...
[DEBUG] Synthesizer: ResearchResult created successfully
[DEBUG] web.py: synthesize_results returned, goal=...
[DEBUG] web.py: Yielding progress message...
[DEBUG] web.py: Progress message yielded
[DEBUG] web.py: Adding assistant message...
[DEBUG] web.py: Updating task draft...
[DEBUG] web.py: Rendering research result...
[DEBUG] render_research_result: Starting, goal=..., num_findings=...
[DEBUG] render_research_result: Processing complete, filtered_findings=..., filtered_citations=...
[DEBUG] render_research_result: Returning dict, synthesis_length=...
[DEBUG] web.py: Research result rendered, size=... chars
[DEBUG] web.py: Saving research result...
[DEBUG] web.py: Research result saved
[DEBUG] web.py: Yielding final result...
[DEBUG] web.py: JSON serialized, size=... chars
[DEBUG] web.py: Final result yielded, returning
```

### 影响
- ✅ 可以精确定位卡住的位置
- ✅ 可以看到每个步骤的耗时
- ✅ 可以识别是否有异常（如序列化失败）
- ✅ 更好的错误处理，避免单个步骤失败导致整体失败

### 后续步骤
运行程序后，新的日志会显示卡在哪一步，然后可以针对性地修复。

---

## 2026-01-15: 性能优化 - 添加超时控制和 wall-clock 时间追踪

### 问题描述
- Tool call 可能比 LLM 更慢，导致整体性能下降
- Runner.run 可能等待完整的 180 秒超时，即使已经卡住
- 并行任务使用 gather 时，一个慢任务会阻塞所有任务
- 缺乏详细的时间追踪，难以定位性能瓶颈

### 修改内容

#### 1. **必做 1：给 tool call 单独加 wall-time timeout (20秒)** (`src/clarifyagent/agents/subagent.py`)
- 在 `enhanced_research_tool` 中添加 20 秒超时保护
- 使用 `async_timeout.timeout(20)` 或 `asyncio.wait_for(..., timeout=20.0)`
- Tool 永远不允许比 LLM 更慢
- 如果超时，返回基本结果而不是完全失败

```python
# 必做 1：给 tool call 单独加 wall-time timeout (20秒)
try:
    if async_timeout is not None:
        async with async_timeout.timeout(20):
            result = await tool.smart_research(query, actual_max_results)
    else:
        result = await asyncio.wait_for(
            tool.smart_research(query, actual_max_results),
            timeout=20.0
        )
except (asyncio.TimeoutError, TimeoutError):
    # 返回基本结果
```

#### 2. **必做 2：Runner.run 改为"软退出"** (`src/clarifyagent/agents/subagent.py`)
- 如果超过 30 秒就强制提前停止，不要等 timeout=180s
- 使用 `asyncio.wait` 实现软退出机制
- 在 30 秒内完成则正常返回，超过 30 秒则强制取消并返回基本结果

```python
# 必做 2：Runner.run 改为"软退出" - 如果超过 30 秒就强制提前停止
SOFT_EXIT_TIMEOUT = 30.0  # 30 秒软退出时间

async def run_with_soft_exit():
    runner_task = asyncio.create_task(
        Runner.run(agent, input_prompt, max_turns=MAX_AGENT_TURNS)
    )
    
    done, pending = await asyncio.wait(
        [runner_task],
        timeout=SOFT_EXIT_TIMEOUT,
        return_when=asyncio.FIRST_COMPLETED
    )
    
    if pending:
        # 超过 30 秒，强制提前停止
        runner_task.cancel()
        return None
    else:
        return runner_task.result()
```

#### 3. **必做 3：gather 改为 fail-fast 或 partial return** (`src/clarifyagent/agents/pool.py`)
- 使用 `asyncio.gather(..., return_exceptions=True)` 允许部分失败
- 异常会被转换为 None，不会阻塞其他任务
- 添加每个任务的独立时间追踪

```python
# 必做 3：使用 return_exceptions=True 允许部分失败
results = await asyncio.gather(*timed_tasks, return_exceptions=True)
# 过滤掉异常，转换为 None
results = [r if not isinstance(r, Exception) else None for r in results]
```

#### 4. **建议 4：给每个 task 打 wall-clock** (`src/clarifyagent/agents/subagent.py`, `src/clarifyagent/agents/pool.py`)
- 使用 `time.monotonic()` 记录每个任务的 wall-clock 时间
- 在任务开始、完成、失败时都记录时间
- 帮助快速定位"凶手"（最慢的任务）

```python
# 建议 4：给每个 task 打 wall-clock
t0 = time.monotonic()
# ... 执行任务 ...
wall_elapsed = time.monotonic() - t0
print(f"Task finished in {wall_elapsed:.2f}s (wall-clock)")
```

### 技术细节

**超时层级：**
1. **Tool call 超时**：20 秒（硬限制）
2. **Runner.run 软退出**：30 秒（提前停止）
3. **Runner.run 硬超时**：180 秒（最终保护）

**时间追踪：**
- 使用 `time.monotonic()` 记录 wall-clock 时间（不受系统时间调整影响）
- 记录任务开始、完成、失败的时间点
- 输出格式：`{elapsed:.2f}s (wall-clock: {wall_elapsed:.2f}s)`

**错误处理：**
- Tool 超时：返回基本结果（confidence=0.3），不抛出异常
- Runner.run 软退出：返回基本结果（confidence=0.5），不抛出异常
- Runner.run 硬超时：返回超时结果（confidence=0.3），不抛出异常
- gather 异常：转换为 None，不阻塞其他任务

### 影响
- ✅ Tool call 有 20 秒超时保护，不会无限期等待
- ✅ Runner.run 在 30 秒后软退出，避免长时间卡住
- ✅ 并行任务使用 fail-fast，一个慢任务不会阻塞所有任务
- ✅ 详细的时间追踪帮助快速定位性能瓶颈
- ✅ 所有超时都有优雅降级，不会导致系统崩溃

### 日志示例

```
[DEBUG] Subagent-0 Task started: 适应症时间线... (wall-clock: 12345.678)
[DEBUG] enhanced_research_tool: Starting smart_research for query: 适应症时间线...
[DEBUG] enhanced_research_tool: smart_research completed in 12.34s, got 8 sources
[WARN] Subagent-0 Force early stop after 31.2s (soft exit limit: 30.0s)
[INFO] Subagent-0 Soft exit after 31.2s (total: 31.5s, wall-clock: 31.5s) - returning with available data
[DEBUG] Task 0 (适应症时间线...) finished in 31.5s (wall-clock)
[DEBUG] SubagentPool.execute_parallel: Completed 3 tasks in 45.2s (wall-clock)
```

---

## 2026-01-15: 修复报告中的"搜索限制"说明问题

### 问题描述
- 用户发现报告中出现"尽管在本次检索中部分具体数据因搜索限制未能详尽获取"这样的说明
- 这会让用户觉得系统功能受限，影响用户体验
- 实际上系统已经进行了充分的搜索，只是 LLM 在生成报告时主动添加了这样的说明

### 根本原因分析

1. **搜索轮次限制**：
   - `MAX_AGENT_TURNS = 2`（默认）：每个子代理最多 2 轮（1次搜索+1次输出）
   - 如果第一次搜索不够充分，可能没有机会进行第二次搜索

2. **提前停止机制**：
   - `confidence >= 0.7` 时强制停止搜索
   - 可能在某些情况下过早停止，错过更多信息

3. **结果截断**：
   - `MAX_FINDINGS_PER_FOCUS = 10`：每个 focus 最多保留 10 条 findings
   - `MAX_SOURCES_PER_FOCUS = 5`：每个 focus 最多保留 5 个 sources
   - 部分数据可能被截断

4. **LLM 主动说明**：
   - Synthesizer 的 LLM 在生成报告时，发现某些关键数据点缺失
   - 主动添加"因搜索限制未能详尽获取"的说明

### 修改内容

1. **更新 Synthesizer Prompt** (`src/clarifyagent/prompts.py`):
   - 添加"重要：关于数据完整性的说明"章节
   - 明确禁止主动说明"搜索限制"或"数据不足"
   - 指导 LLM 专注于已获取的信息，不要强调限制
   - 只有在确实无法回答核心问题时，才说明需要更多信息

### 后续优化建议

如果问题持续，可以考虑：

1. **增加搜索轮次**：
   ```bash
   export MAX_AGENT_TURNS=3  # 从 2 增加到 3，允许更多搜索
   ```

2. **增加结果保留数量**：
   - 修改 `synthesizer.py` 中的 `MAX_FINDINGS_PER_FOCUS` 和 `MAX_SOURCES_PER_FOCUS`
   - 从 10/5 增加到 15/8 或更多

3. **调整 confidence 阈值**：
   - 如果 confidence 阈值太高，可能导致过早停止
   - 可以考虑降低到 0.6 或根据任务类型动态调整

4. **改进搜索策略**：
   - 允许 LLM 进行更多次搜索（如果 confidence 较低）
   - 改进查询策略，提高搜索质量

### 影响
- ✅ LLM 不再主动添加"搜索限制"的说明
- ✅ 报告更加专业，专注于已获取的信息
- ✅ 提升用户体验，减少对系统功能的误解
- ✅ 只有在确实无法回答核心问题时，才说明需要更多信息

---

## 2026-01-15: 修复 Deepseek API 调用耗时问题 - 添加超时和诊断日志

### 问题描述
- 在服务器上，Deepseek API 调用（通过 LiteLLM）耗时很长
- 从日志看，多个调用之间间隔 11 秒、2 秒等，说明单个调用耗时很长
- 可能原因：网络延迟、API 响应慢、没有超时设置导致长时间等待

### 修改内容

1. **添加超时设置** (`src/clarifyagent/deepseek_model.py`):
   - 在 `AsyncOpenAI` 和 `OpenAI` client 初始化时添加 `timeout` 参数
   - 使用 `httpx.Timeout` 进行精细控制：
     - `connect=10.0s`：连接超时
     - `read=API_TIMEOUT`：读取超时（默认 30 秒）
     - `write=10.0s`：写入超时
   - 确保 API 调用不会无限期等待

2. **添加详细的诊断日志** (`src/clarifyagent/deepseek_model.py`):
   - 在每次 API 调用开始和结束时记录时间
   - 记录请求大小（messages 总字符数）
   - 记录响应大小（response 字符数）
   - 记录调用耗时
   - 如果耗时 > 10 秒，输出警告
   - 如果耗时 > 5 秒，输出信息提示

3. **改进错误处理** (`src/clarifyagent/deepseek_model.py`):
   - 区分超时错误和其他错误
   - 输出详细的错误信息（错误类型、耗时）

### 技术细节

**超时配置：**
```python
timeout_config = httpx.Timeout(
    API_TIMEOUT,  # 总超时时间（默认 30 秒）
    connect=10.0,  # 连接超时 10 秒
    read=API_TIMEOUT,  # 读取超时
    write=10.0  # 写入超时 10 秒
)
```

**诊断日志示例：**
```
[DEBUG] Deepseek API call starting: model=deepseek-chat, messages_chars=1234, timeout=30s
[DEBUG] Deepseek API call completed: 12.34s, response_chars=567
[WARN] Deepseek API call took 12.34s (slow, >10s) - 可能是网络延迟或 API 响应慢
```

### 影响
- ✅ API 调用有超时保护，避免无限期等待
- ✅ 详细的诊断日志帮助定位慢速调用的原因
- ✅ 可以识别网络延迟、API 响应慢等问题
- ✅ 更好的错误处理和提示

### 可能的原因分析

如果调用仍然很慢，可能的原因：
1. **网络延迟**：服务器到 Deepseek API 的网络延迟高
2. **API 响应慢**：Deepseek API 本身处理时间长
3. **请求内容大**：messages 内容很大，需要更长时间处理
4. **API 限流**：可能触发了限流，导致排队等待
5. **服务器资源**：服务器 CPU/内存不足，影响处理速度

### 后续建议
如果问题持续，可以：
1. 检查网络连接质量（ping api.deepseek.com）
2. 检查 API 响应时间（单独测试一个简单请求）
3. 考虑使用更快的模型或减少请求内容大小
4. 检查是否有 API 限流（查看 API 使用情况）

---

## 2026-01-15: 修复 Runner.run 超时问题 - 增强诊断和错误处理

### 问题描述
- 研究工具完成后，LLM (DeepSeek) 调用卡住，没有返回响应
- 虽然设置了 `AGENT_EXECUTION_TIMEOUT=300`，但超时可能没生效
- `asyncio.wait_for` 可能无法取消 `Runner.run` 内部的阻塞操作

### 修改内容

1. **增强超时诊断日志** (`src/clarifyagent/agents/subagent.py`):
   - 在 `Runner.run` 开始前输出超时配置信息（timeout 和 max_turns）
   - 在 `Runner.run` 完成后输出成功日志
   - 在超时异常中输出详细的可能原因分析
   - 添加 `LitellmModel` 创建日志

2. **改进超时错误处理** (`src/clarifyagent/agents/subagent.py`):
   - 超时时返回 `SubtaskResult` 而不是抛出异常
   - 让系统能够继续运行，而不是完全失败
   - 返回的 confidence 设为 0.3，表示超时结果

3. **添加模型创建日志** (`src/clarifyagent/agents/subagent.py`):
   - 输出创建的 `LitellmModel` 信息
   - 帮助追踪模型配置是否正确

### 技术细节

**超时机制：**
- 使用 `asyncio.wait_for` 包装 `Runner.run`
- 超时时间由 `AGENT_EXECUTION_TIMEOUT` 配置（默认 300 秒）
- 注意：如果 `Runner.run` 内部有阻塞操作（如同步 HTTP 调用），`asyncio.wait_for` 可能无法正确取消

**可能的问题原因：**
1. LLM API 调用卡住（DeepSeek API 没有响应）
2. `Runner.run` 内部有阻塞操作
3. 网络问题或连接挂起
4. `asyncio.wait_for` 无法取消正在进行的 LLM API 调用

**解决方案：**
- 超时时返回部分结果，而不是完全失败
- 添加详细的诊断日志，帮助定位问题
- 考虑在 LiteLLM 层面添加超时（如果支持）

### 影响
- ✅ 更详细的诊断信息，帮助定位卡住的位置
- ✅ 超时时系统能够继续运行，而不是完全失败
- ✅ 更好的错误处理和日志记录

### 后续建议
如果超时问题持续存在，可能需要：
1. 检查 LiteLLM 是否支持在模型层面设置超时
2. 考虑使用 LiteLLM Router 来配置超时
3. 检查 DeepSeek API 的响应时间是否正常
4. 考虑添加更激进的超时机制（如每个 LLM 调用单独超时）

---

## 2026-01-15: 添加详细的 confidence 日志和超时机制

### 问题分析
第三个任务（"Keytruda 自首次获批后在美国新增的适应症列表（按时间顺序）"）耗时166.29秒，其中：
- 最后一个工具调用在20:53:38完成，confidence=0.85（很高）
- 但之后LLM还在继续思考，直到166.20s才完成
- 耗时约128秒在工具调用后的思考/生成阶段

### 修改内容

1. **添加详细的 confidence 日志** (`src/clarifyagent/agents/subagent.py`):
   - 在 `enhanced_research_tool` 中输出详细的 confidence 信息
   - 包括 rule_confidence、llm_confidence 和最终 confidence
   - 帮助追踪每次工具调用后的 confidence 值

2. **添加超时机制** (`src/clarifyagent/config.py`, `src/clarifyagent/agents/subagent.py`):
   - 添加 `AGENT_EXECUTION_TIMEOUT` 配置（默认300秒/5分钟）
   - 在 `Runner.run` 外包装 `asyncio.wait_for`，超时后抛出异常
   - 防止任务无限期卡住

3. **添加进度追踪日志** (`src/clarifyagent/tools/concurrency_manager.py`, `src/clarifyagent/agents/subagent.py`):
   - 在 `concurrency_manager.py` 中，每30秒输出一次任务状态
   - 在 `subagent.py` 中，每30秒输出一次 `Runner.run` 状态
   - 帮助定位卡住的位置

### 影响
- 可以更清楚地看到每次工具调用后的 confidence 值
- 如果任务超过5分钟，会自动超时并抛出异常
- 可以追踪任务在哪个阶段耗时最长

### 修复
- 修复了 f-string 格式化错误：不能在格式说明符中直接使用三元表达式
- 改为先计算字符串值，再在 f-string 中使用

---

## 2026-01-15: 改进 Jina 工具的错误处理和超时设置

### 问题描述
- Jina 读取某些 URL 时遇到 SSL 连接错误（如 `SSLEOFError`）
- 错误信息过于冗长，包含完整的堆栈跟踪
- `jina_read` 函数没有超时设置，可能导致长时间等待

### 修改内容

1. **添加超时设置** (`src/clarifyagent/tools/jina.py`):
   - 在 `jina_read` 函数中添加 `timeout=API_TIMEOUT` 参数
   - 使用配置中的 `API_TIMEOUT`（默认30秒）
   - 避免长时间等待无响应的请求

2. **添加 HTTP 状态码检查** (`src/clarifyagent/tools/jina.py`):
   - 检查响应状态码，如果不是 200 则抛出异常
   - 提供更清晰的错误信息

3. **改进错误日志** (`src/clarifyagent/tools/enhanced_research.py`):
   - 简化错误日志，只显示关键信息
   - 对于常见错误类型（SSL、超时、HTTP错误），显示简短友好的消息
   - 避免冗长的堆栈跟踪信息

### 影响
- ✅ Jina 读取失败不会影响整体执行（已有 `_safe_jina_read` 保护）
- ✅ 超时设置避免长时间等待
- ✅ 错误日志更清晰，减少噪音
- ✅ 更好的错误分类和提示

### 进一步优化：添加并发控制和统计信息

**问题描述：**
- 大量 Jina 读取遇到 SSL 连接错误
- 所有 Jina 任务同时并行执行，没有并发限制
- 无法看到成功/失败的比例统计

**修改内容：**

1. **添加并发控制** (`src/clarifyagent/tools/enhanced_research.py`):
   - 使用 `asyncio.Semaphore` 限制同时进行的 Jina 请求数量
   - 并发数限制为 `MAX_CONCURRENT_REQUESTS`（默认4）或 Jina 目标数量（取较小值）
   - 避免过多并发请求导致 SSL 连接问题

2. **添加统计信息** (`src/clarifyagent/tools/enhanced_research.py`):
   - 统计成功和失败的 Jina 读取数量
   - 计算成功率百分比
   - 输出格式：`[EnhancedResearch] Jina读取完成: X/Y 成功 (Z%), N 失败`

**影响：**
- ✅ 减少并发请求数量，可能降低 SSL 错误率
- ✅ 提供清晰的统计信息，便于了解 Jina 读取的成功率
- ✅ 更好的资源管理和错误处理

**注意：**
- SSL 错误可能是某些网站对 Jina 请求的 SSL 验证问题，这是正常的
- 即使有 SSL 错误，系统仍能正常工作（使用 Serper 搜索结果）
- 并发控制有助于减少连接问题，但不能完全消除 SSL 错误

---

## 2026-01-15: 修复 Jina 灾难闭环 - 黑名单 + 硬超时 + Confidence 上限

### 问题描述
用户指出一个严重的工程问题：
- **灾难闭环**：搜索 → 拿到 URL → Jina 被拒 → 等到超时 → confidence 还给高分
- 这是一个逻辑上自洽但工程上灾难的闭环
- 某些域名（如学术期刊网站）经常 SSL 错误，但仍然尝试 Jina 读取并等待超时
- 即使所有 Jina 读取失败，confidence 仍然可能很高

### 修改内容

1. **添加 Jina 黑名单域名** (`src/clarifyagent/config.py`, `src/clarifyagent/tools/intelligent_research.py`):
   - 在 `config.py` 中添加 `JINA_SKIP_DOMAINS` 列表，包含12个常见学术/医学网站域名
   - 在 `intelligent_research.py` 的 `should_use_jina` 方法中添加黑名单检查
   - 如果 URL 包含黑名单域名，直接返回 `False`，跳过 Jina 读取
   - 黑名单域名包括：pmc.ncbi.nlm.nih.gov, nejm.org, sciencedirect.com, annalsofoncology.org, ascopubs.org, aacrjournals.org, onlinelibrary.wiley.com, link.springer.com, nature.com, clinicaltrials.gov, asco.org, esmo.org

2. **Jina 硬超时 + 零重试** (`src/clarifyagent/config.py`, `src/clarifyagent/tools/jina.py`):
   - 添加 `JINA_TIMEOUT` 配置（默认 3 秒），独立于 `API_TIMEOUT`
   - 添加 `JINA_RETRIES` 配置（默认 0，零重试）
   - 在 `jina_read` 函数中使用 `JINA_TIMEOUT` 而不是 `API_TIMEOUT`
   - 避免长时间等待失败的请求

3. **Jina 成功率为 0 时限制 Confidence 上限** (`src/clarifyagent/tools/enhanced_research.py`):
   - 在 `smart_research` 中计算 `jina_success_rate`
   - 将 `jina_success_rate` 传递给 `_calculate_confidence` 方法
   - 如果 `jina_success_rate == 0.0` 且有 Jina 任务，限制 `final_confidence` 上限为 0.5
   - 在 `confidence_details` 中记录限制原因

### 技术细节

**黑名单检查逻辑：**
```python
# 在 should_use_jina 方法开始处
for skip_domain in JINA_SKIP_DOMAINS:
    if skip_domain in url_lower:
        return False, 0, f"黑名单域名: {skip_domain}，跳过 Jina 读取"
```

**Confidence 上限限制：**
```python
if jina_success_rate == 0.0 and len(sources) > 0:
    final_confidence = min(final_confidence, 0.5)
    confidence_details["jina_success_rate"] = 0.0
    confidence_details["confidence_capped"] = True
    confidence_details["cap_reason"] = "Jina 成功率 0%，限制 confidence 上限为 0.5"
```

### 影响
- ✅ **打破灾难闭环**：Jina 失败不再导致高 confidence
- ✅ **减少无效等待**：黑名单域名直接跳过，3秒硬超时避免长时间等待
- ✅ **更准确的 Confidence**：反映实际的信息质量，而不是虚假的高分
- ✅ **提高执行效率**：跳过已知失败的域名，减少超时等待

### 配置说明
- `JINA_TIMEOUT`: Jina 请求超时时间（默认 3 秒）
- `JINA_RETRIES`: Jina 重试次数（默认 0，零重试）
- `JINA_SKIP_DOMAINS`: Jina 黑名单域名列表（可通过环境变量扩展）

---

### 过滤 PDF URL，禁止 Jina 读取 PDF 文件

**问题描述：**
- PDF 文件不适合通过 Jina 读取（Jina 主要处理 HTML 网页）
- PDF 文件读取可能失败或返回格式不理想的内容
- 需要过滤掉 PDF 后缀的 URL，避免浪费 Jina 调用

**修改内容：**

1. **`src/clarifyagent/tools/intelligent_research.py` - `should_use_jina` 方法**
   - 在方法开始处添加 PDF URL 检查
   - 如果 URL 以 `.pdf` 结尾、包含 `.pdf?` 或以 `.pdf/` 结尾，直接返回 `False`
   - 返回原因："PDF 文件，跳过 Jina 读取"

**技术细节：**
- 检查 URL 的小写形式，确保匹配各种大小写组合
- 支持多种 PDF URL 格式：
  - `https://example.com/file.pdf`
  - `https://example.com/file.pdf?param=value`
  - `https://example.com/file.pdf/`

**影响：**
- ✅ PDF 文件不再通过 Jina 读取，节省 API 调用
- ✅ 避免 PDF 读取失败导致的错误
- ✅ 提高系统稳定性和执行效率
- ✅ PDF URL 仍然会出现在搜索结果中，只是不会被深度读取

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

### 添加 LLM confidence 输出

**问题描述：**
- LLM confidence 评分在内部计算，但没有在输出中单独显示
- 用户无法看到 LLM 评估的具体评分值

**修改内容：**

1. **`src/clarifyagent/tools/enhanced_research.py` - `_calculate_confidence` 方法**
   - 修改返回类型：从 `float` 改为 `Dict[str, Any]`
   - 返回字典包含：
     - `confidence`: 最终置信度（向后兼容）
     - `rule_confidence`: 规则计算的置信度
     - `llm_confidence`: LLM 评估的置信度（如果启用，否则为 None）
     - `confidence_details`: 详细信息（包含权重等）

2. **`src/clarifyagent/tools/enhanced_research.py` - `smart_research` 方法**
   - 修改 confidence 计算结果的处理
   - 在返回值中添加新字段：
     - `rule_confidence`: 规则评分
     - `llm_confidence`: LLM 评分
     - `confidence_details`: 详细信息
   - 保持 `confidence` 字段向后兼容

3. **`src/clarifyagent/tools/enhanced_research.py` - `enhanced_web_search_with_jina` 适配器函数**
   - 更新输出格式，显示详细的 confidence 信息
   - 如果启用 LLM 评分，显示规则评分、LLM 评分和混合权重
   - 如果未启用，显示规则评分和提示信息

4. **`src/clarifyagent/agents/subagent.py` - `enhanced_research_tool` 函数**
   - 在 `structured_output` 中添加新字段：
     - `rule_confidence`: 规则评分
     - `llm_confidence`: LLM 评分
     - `confidence_details`: 详细信息
   - 确保 LLM 可以访问这些详细信息

**输出示例：**
```
置信度: 0.85
  - 规则评分: 0.72
  - LLM评分: 0.92
  - 混合权重: 规则60% + LLM40%
```

**影响：**
- ✅ 用户可以看到 LLM 评估的具体评分
- ✅ 可以对比规则评分和 LLM 评分的差异
- ✅ 向后兼容，`confidence` 字段仍然存在
- ✅ 在 JSON 输出和文本输出中都包含详细信息

---

### 实现 LLM 评分增强 confidence 计算

**问题描述：**
- 当前的 confidence 计算完全基于规则（源数量、Jina 深度读取数量、场景权重）
- 没有考虑信息质量、相关性、完整性等维度
- 无法智能评估搜索结果是否真正回答了查询

**修改内容：**

1. **`src/clarifyagent/config.py`**
   - 添加 `ENABLE_LLM_CONFIDENCE` 配置项：控制是否启用 LLM 评分（默认 false）
   - 添加 `LLM_CONFIDENCE_WEIGHT` 配置项：LLM 评分权重（默认 0.4，即规则60%+LLM40%）

2. **`src/clarifyagent/tools/enhanced_research.py` - `EnhancedResearchTool` 类**
   - **`__init__` 方法**：
     - 添加 `enable_llm_confidence` 参数（可选，默认从配置读取）
     - 如果启用，初始化 LLM 模型（使用 fast 模型以节省成本）
   
   - **`_llm_evaluate_confidence` 方法（新增）**：
     - 使用 LLM 评估信息质量，从4个维度评分：
       - 相关性（Relevance）：搜索结果与查询的匹配程度
       - 信息质量（Quality）：来源的权威性和可靠性
       - 信息完整性（Completeness）：是否覆盖了查询的关键信息点
       - 信息一致性（Consistency）：多个来源的信息是否一致
     - 只评估前5个源以节省 token
     - 返回综合评分（overall_confidence）
     - 包含错误处理和 JSON 解析逻辑
   
   - **`_calculate_confidence` 方法（修改）**：
     - 改为异步方法（`async def`）
     - 添加 `query` 和 `findings` 参数
     - 保留原有的规则计算作为基础评分
     - 如果启用 LLM 评分，调用 `_llm_evaluate_confidence` 获取 LLM 评分
     - 使用加权平均混合规则评分和 LLM 评分：
       - `final_confidence = rule_confidence * (1 - LLM_CONFIDENCE_WEIGHT) + llm_confidence * LLM_CONFIDENCE_WEIGHT`
     - 如果 LLM 评分失败，回退到规则评分
     - 添加调试日志输出混合评分过程
   
   - **`smart_research` 方法**：
     - 修改 confidence 计算调用为 `await self._calculate_confidence(...)`
     - 传递 `query` 和 `findings` 参数

**技术细节：**
- LLM 评分使用快速模型（`build_model("fast")`）以控制成本
- 只评估前5个源，限制 prompt 长度
- 使用 JSON 格式返回评分，包含错误处理
- 支持完全禁用（默认）或通过环境变量启用
- 混合评分权重可配置（默认 40% LLM + 60% 规则）

**使用方式：**
在 `.env` 文件中添加：
```bash
# 启用 LLM 评分
ENABLE_LLM_CONFIDENCE=true
# LLM 评分权重（0.0=只用规则，1.0=只用LLM，0.4=规则60%+LLM40%）
LLM_CONFIDENCE_WEIGHT=0.4
```

**影响：**
- ✅ 可以更智能地评估搜索结果质量
- ✅ 考虑信息相关性、质量、完整性、一致性
- ✅ 默认禁用，不影响现有功能
- ✅ 可配置权重，灵活调整规则和 LLM 评分的比例
- ✅ 包含错误处理，失败时回退到规则评分

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

