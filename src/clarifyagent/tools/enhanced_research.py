"""
增强研究工具 - 结合Serper快速搜索和Jina深度读取
专为药物研发场景优化
"""
import asyncio
import time
from typing import List, Dict, Any, Optional
from ..schema import Source
from .serperapi import web_search
from .jina import jina_read
from .intelligent_research import IntelligentResearchSelector, ResearchScenario

class EnhancedResearchTool:
    """增强研究工具"""
    
    def __init__(self, enable_llm_confidence: bool = None):
        self.selector = IntelligentResearchSelector()
        self.performance_stats = {
            'serper_calls': 0,
            'jina_calls': 0,
            'total_time': 0,
            'scenarios_detected': {}
        }
        
        # LLM 评分支持
        from ..config import ENABLE_LLM_CONFIDENCE
        self.enable_llm_confidence = enable_llm_confidence if enable_llm_confidence is not None else ENABLE_LLM_CONFIDENCE
        self.llm_model = None
        if self.enable_llm_confidence:
            from ..agent import build_model
            self.llm_model = build_model("fast")  # 使用快速模型进行评分
            print(f"[EnhancedResearch] LLM confidence evaluation enabled")
    
    async def smart_research(self, query: str, max_results: int = 10,
                           task_context: Dict = None) -> Dict[str, Any]:
        """
        智能研究：根据场景自动选择工具组合

        Args:
            query: 研究查询
            max_results: 最大结果数
            task_context: 任务上下文

        Returns:
            包含findings, sources, confidence的结果
        """
        start_time = time.time()
        task_context = task_context or {}

        # 1. 场景检测
        scenario = self.selector.detect_scenario(query, task_context)
        self.performance_stats['scenarios_detected'][scenario.value] = \
            self.performance_stats['scenarios_detected'].get(scenario.value, 0) + 1

        print(f"[EnhancedResearch] 检测场景: {scenario.value}")

        # 2. Serper快速搜索获取候选源 - 直接获取 JSON
        serper_start = time.time()
        search_results_json = await self._get_serper_json(query, max_results)
        self.performance_stats['serper_calls'] += 1
        serper_time = time.time() - serper_start

        if not search_results_json:
            return {
                'findings': ['搜索未找到相关结果'],
                'sources': [],
                'confidence': 0.0,
                'research_plan': {'strategy': 'failed'}
            }

        # 3. 从 JSON 中提取结构化数据（真实 URLs）
        search_results_list = self._extract_sources_from_json(search_results_json, max_results)

        if not search_results_list:
            return {
                'findings': ['搜索结果解析失败'],
                'sources': [],
                'confidence': 0.0,
                'research_plan': {'strategy': 'failed'}
            }

        # 4. 创建智能研究计划（传递 max_results 以动态调整 Jina 目标数量）
        research_plan = self.selector.create_research_plan(query, search_results_list, max_results)


        print(f"[EnhancedResearch] 研究计划: {len(research_plan['jina_targets'])} 个深度目标")

        # 5. 并行执行深度读取（带并发控制）
        enhanced_sources = []
        if research_plan['jina_targets']:
            from ..config import MAX_CONCURRENT_REQUESTS
            # 使用信号量控制并发，避免过多并发请求导致 SSL 错误
            semaphore = asyncio.Semaphore(min(MAX_CONCURRENT_REQUESTS, len(research_plan['jina_targets'])))
            
            async def jina_read_with_semaphore(target):
                async with semaphore:
                    return await self._safe_jina_read(target)
            
            jina_tasks = [jina_read_with_semaphore(target) for target in research_plan['jina_targets']]
            
            jina_start = time.time()
            jina_results = await asyncio.gather(*jina_tasks, return_exceptions=True)
            jina_time = time.time() - jina_start
            self.performance_stats['jina_calls'] += len(jina_tasks)
            
            # 处理Jina结果并统计
            success_count = 0
            error_count = 0
            for i, result in enumerate(jina_results):
                if isinstance(result, Exception):
                    error_count += 1
                    continue
                if result:
                    enhanced_sources.append(result)
                    success_count += 1
            
            # 输出统计信息
            # 注意：jina_success_rate 使用 0-1 比例，不是百分比
            jina_success_rate = 0.0
            if len(jina_tasks) > 0:
                jina_success_rate = success_count / len(jina_tasks)  # 0-1 比例
                jina_success_percent = jina_success_rate * 100  # 用于显示的百分比
                print(f"[EnhancedResearch] Jina读取完成: {success_count}/{len(jina_tasks)} 成功 ({jina_success_percent:.1f}%), {error_count} 失败")
        else:
            jina_success_rate = 1.0  # 如果没有 Jina 任务，认为成功率为 100%（0-1 比例）
        
        # 5. 合并Serper和Jina结果
        all_sources = self._merge_sources(search_results_list, enhanced_sources)
        
        # 6. 基于场景提取关键发现
        findings = self._extract_scenario_findings(scenario, all_sources, query)
        
        # 7. 计算置信度（支持 LLM 评分）
        confidence_start = time.time()
        confidence_result = await self._calculate_confidence(scenario, all_sources, len(enhanced_sources), 
                                                             query=query, findings=findings,
                                                             jina_success_rate=jina_success_rate)
        confidence_time = time.time() - confidence_start
        llm_confidence_time = confidence_result.get('llm_confidence_time', 0)
        
        total_time = time.time() - start_time
        self.performance_stats['total_time'] += total_time
        
        # 构建耗时信息字符串
        time_parts = [f"Serper: {serper_time:.2f}s", f"Jina: {jina_time if 'jina_time' in locals() else 0:.2f}s"]
        if llm_confidence_time > 0:
            time_parts.append(f"LLM评分: {llm_confidence_time:.2f}s")
        time_parts.append(f"其他: {total_time - serper_time - (jina_time if 'jina_time' in locals() else 0) - llm_confidence_time:.2f}s")
        
        print(f"[EnhancedResearch] 完成: {total_time:.2f}s ({', '.join(time_parts)})")
        
        return {
            'findings': findings,
            'sources': all_sources,  # Return all sources, let LLM decide what to use
            'confidence': confidence_result['confidence'],  # 向后兼容：最终置信度
            'rule_confidence': confidence_result['rule_confidence'],  # 规则计算的置信度
            'llm_confidence': confidence_result['llm_confidence'],  # LLM 评估的置信度（如果启用）
            'confidence_details': confidence_result['confidence_details'],  # 详细信息
            'research_plan': research_plan,
            'performance': {
                'total_time': total_time,
                'serper_time': serper_time,
                'jina_time': jina_time if 'jina_time' in locals() else 0,
                'llm_confidence_time': llm_confidence_time,
                'confidence_time': confidence_time,
                'enhanced_sources': len(enhanced_sources),
                'total_sources': len(all_sources)
            },
            'search_metadata': {
                'num_search_results': len(search_results_list),
                'num_jina_reads': len(enhanced_sources),
                'scenario': scenario.value
            }
        }
    
    async def _get_serper_json(self, query: str, num_results: int) -> Optional[Dict]:
        """
        直接获取 SerpAPI 的 JSON 响应，避免文本解析
        """
        try:
            import os
            from .http_pool import optimized_http_get

            SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
            if not SERPAPI_API_KEY:
                print("[ERROR] SERPAPI_API_KEY not found")
                return None

            params = {
                'q': query,
                'api_key': SERPAPI_API_KEY,
                'num': num_results,
                'engine': 'google'
            }

            url = "https://serpapi.com/search.json"
            async with await optimized_http_get(url, params=params) as response:
                result = await response.json()

            return result

        except Exception as e:
            print(f"[ERROR] _get_serper_json failed: {e}")
            return None

    def _extract_sources_from_json(self, serper_json: Dict, max_results: int) -> List[Dict]:
        """
        从 SerpAPI 的 JSON 响应中提取真实的 URLs
        这样可以确保 URLs 100% 准确，不需要从文本中解析
        """
        sources = []

        # 提取 organic_results
        organic_results = serper_json.get('organic_results', [])

        for item in organic_results[:max_results]:
            title = item.get('title', '')
            link = item.get('link', '')
            snippet = item.get('snippet', '')

            # 只添加有效的 URL
            if link and link.startswith('http'):
                sources.append({
                    'title': title[:200],  # 限制标题长度
                    'url': link,  # 真实 URL，直接从 SerpAPI JSON 获取
                    'snippet': snippet[:500] if snippet else ""
                })

        print(f"[DEBUG] _extract_sources_from_json: Extracted {len(sources)} sources with real URLs")

        return sources

    async def _safe_jina_read(self, target: Dict) -> Optional[Source]:
        """安全的Jina读取，捕获所有异常避免影响整体执行"""
        try:
            content = await jina_read(target['url'], max_chars=3000)  # 限制内容长度
            if content and len(content.strip()) > 100:  # 确保有意义的内容
                return Source(
                    title=target['title'],
                    url=target['url'],
                    snippet=content[:500] + "..." if len(content) > 500 else content,
                    source_type="detailed_content",
                    metadata={
                        'jina_priority': target['priority'],
                        'jina_reason': target['reason'],
                        'content_length': len(content)
                    }
                )
        except Exception as e:
            # 简化错误日志，只显示关键信息，避免冗长的堆栈跟踪
            error_msg = str(e)
            # 对于常见错误，只显示简短信息
            if "SSLError" in error_msg or "SSL" in error_msg:
                print(f"[EnhancedResearch] Jina读取失败 {target['url']}: SSL连接错误（已跳过）")
            elif "timeout" in error_msg.lower() or "Timeout" in error_msg:
                print(f"[EnhancedResearch] Jina读取失败 {target['url']}: 超时（已跳过）")
            elif "HTTP" in error_msg or "status" in error_msg.lower():
                print(f"[EnhancedResearch] Jina读取失败 {target['url']}: {error_msg[:100]}")
            else:
                print(f"[EnhancedResearch] Jina读取失败 {target['url']}: {error_msg[:100]}")
        return None
    
    def _parse_search_results(self, search_results: str) -> List[Dict]:
        """
        解析Serper搜索结果（从格式化文本中提取结构化数据）

        CRITICAL: 这个方法从 serperapi.format_search_result 的输出中提取真实 URLs
        必须确保提取到的 URL 是完整的、真实的
        """
        results = []
        lines = search_results.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 寻找结果条目的开始（通常是序号形式如 "1. **Title**"）
            if line and line[0].isdigit() and '. ' in line:
                # 提取标题 - 格式: "1. **Title text**"
                title_start = line.find('.') + 1
                title = line[title_start:].strip()
                # 移除 markdown 格式
                title = title.replace('**', '').strip()

                # 查找后续行的 snippet 和 URL
                url = ""
                snippet = ""
                j = i + 1

                while j < len(lines) and j < i + 10:  # 限制查找范围
                    next_line = lines[j].strip()

                    # 检查是否是 URL 行（格式: "   链接: https://..."）
                    if '链接:' in next_line or 'URL:' in next_line or next_line.startswith('http'):
                        # 提取 URL
                        if '链接:' in next_line:
                            url = next_line.split('链接:', 1)[1].strip()
                        elif 'URL:' in next_line:
                            url = next_line.split('URL:', 1)[1].strip()
                        elif next_line.startswith('http'):
                            url = next_line
                    # 如果不是 URL，不是空行，不是下一个结果，就是 snippet
                    elif next_line and not next_line[0].isdigit():
                        if not snippet:
                            snippet = next_line
                        else:
                            snippet += " " + next_line
                    # 如果是下一个结果的开始，停止
                    elif next_line and next_line[0].isdigit() and '. ' in next_line:
                        break

                    j += 1

                # 只添加有 URL 的结果（确保有真实链接）
                if title and url and url.startswith('http'):
                    results.append({
                        'title': title[:200],  # 限制标题长度
                        'url': url,  # 真实 URL
                        'snippet': snippet[:500] if snippet else ""  # 限制snippet长度
                    })
                elif title:
                    # 记录没有 URL 的条目（用于调试）
                    print(f"[WARN] _parse_search_results: Entry without URL: {title[:50]}")

                i = j  # 移动到处理过的位置
            else:
                i += 1

        print(f"[DEBUG] _parse_search_results: Extracted {len(results)} results from search output")

        # 如果上述方法失败，尝试更简单的模式匹配
        if not results:
            print(f"[WARN] _parse_search_results: Primary parsing failed, trying fallback")
            current_result = {}
            for line in lines:
                line = line.strip()
                if line.startswith('Title:'):
                    if current_result and current_result.get('url'):
                        results.append(current_result)
                    current_result = {'title': line[6:].strip()}
                elif line.startswith('URL:') or line.startswith('链接:'):
                    url = line.split(':', 1)[1].strip()
                    if url.startswith('http'):
                        current_result['url'] = url
                elif line.startswith('http') and 'url' not in current_result:
                    current_result['url'] = line
                elif line and not line.startswith('http') and 'title' in current_result:
                    current_result['snippet'] = current_result.get('snippet', '') + ' ' + line

            if current_result and current_result.get('url'):
                results.append(current_result)

        return results[:10]  # 最多返回10个结果
    
    def _merge_sources(self, serper_results: List[Dict], jina_sources: List[Source]) -> List[Source]:
        """合并不同来源的结果"""
        all_sources = []
        
        # 添加Jina增强的源（优先级高）
        all_sources.extend(jina_sources)
        
        # 添加Serper源（避免重复）
        jina_urls = {src.url for src in jina_sources}
        for result in serper_results:
            if result.get('url') not in jina_urls:
                all_sources.append(Source(
                    title=result.get('title', ''),
                    url=result.get('url', ''),
                    snippet=result.get('snippet', ''),
                    source_type="search_result"
                ))
        
        return all_sources
    
    def _extract_scenario_findings(self, scenario: ResearchScenario, 
                                 sources: List[Source], query: str) -> List[str]:
        """基于场景提取关键发现"""
        findings = []
        
        if scenario == ResearchScenario.RETROSYNTHESIS:
            # 逆合成路线关键信息
            for source in sources:
                content = source.snippet.lower()
                if any(kw in content for kw in ['synthesis', 'yield', 'reaction', 'procedure']):
                    # 提取合成相关信息
                    if 'yield' in content:
                        findings.append(f"发现收率数据: {source.title}")
                    if 'procedure' in content or 'synthesis' in content:
                        findings.append(f"找到合成步骤: {source.title}")
        
        elif scenario == ResearchScenario.PIPELINE_EVALUATION:
            # 管线评估关键信息
            for source in sources:
                content = source.snippet.lower()
                if any(kw in content for kw in ['phase', 'clinical', 'market', 'revenue']):
                    if 'phase' in content:
                        findings.append(f"管线进展信息: {source.title}")
                    if 'market' in content or 'revenue' in content:
                        findings.append(f"商业价值数据: {source.title}")
        
        elif scenario == ResearchScenario.CLINICAL_PIPELINE:
            # 临床管线关键信息
            for source in sources:
                content = source.snippet.lower()
                if any(kw in content for kw in ['efficacy', 'safety', 'endpoint', 'survival']):
                    findings.append(f"临床数据: {source.title}")
        
        # 确保至少有一些发现
        if not findings:
            findings = [f"从{len(sources)}个来源收集了相关信息"]
            if any(src.source_type == "detailed_content" for src in sources):
                findings.append("包含深度内容分析")
        
        return findings[:5]  # 限制发现数量
    
    async def _calculate_confidence(self, scenario: ResearchScenario,
                                  sources: List[Source], enhanced_count: int,
                                  query: str = "", findings: List[str] = None,
                                  jina_success_rate: float = 1.0) -> Dict[str, Any]:
        """计算置信度（支持规则+LLM混合评分）
        
        Returns:
            Dict containing:
            - confidence: 最终置信度（向后兼容）
            - rule_confidence: 规则计算的置信度
            - llm_confidence: LLM 评估的置信度（如果启用）
            - confidence_details: 详细信息
        """
        findings = findings or []
        
        # 1. 规则计算（基础评分）
        base_confidence = 0.5
        
        # 基于源的数量
        source_boost = min(len(sources) * 0.1, 0.3)
        
        # 基于深度内容的数量
        enhanced_boost = min(enhanced_count * 0.15, 0.3)
        
        # 基于场景的权重（覆盖所有 ResearchScenario 枚举值）
        scenario_weights = {
            ResearchScenario.RETROSYNTHESIS: 0.85,      # 技术内容相对确定，合成路线有明确答案
            ResearchScenario.PIPELINE_EVALUATION: 0.75, # 商业分析有主观性，需要更多验证
            ResearchScenario.CLINICAL_PIPELINE: 0.9,    # 临床数据相对客观，有明确的试验结果
            ResearchScenario.MARKET_ANALYSIS: 0.7,      # 市场分析主观性强，数据时效性要求高
            ResearchScenario.REGULATORY_REVIEW: 0.85,   # 监管信息相对确定，官方来源可靠
            ResearchScenario.ACADEMIC_RESEARCH: 0.8,    # 学术研究有同行评审，相对可靠
            ResearchScenario.COMPETITIVE_INTELLIGENCE: 0.7,  # 竞争情报时效性强，信息不完整
        }

        scenario_weight = scenario_weights.get(scenario, 0.75)  # 默认值提高到 0.75
        
        rule_confidence = (base_confidence + source_boost + enhanced_boost) * scenario_weight
        
        # 2. LLM 评分（如果启用）
        llm_confidence = None
        llm_confidence_time = 0.0
        # 初始化 confidence_details，确保所有字段都有默认值（避免下游 None 引用问题）
        confidence_details = {
            "rule_confidence": rule_confidence,
            "llm_enabled": self.enable_llm_confidence,
            "llm_confidence": 0.0,           # 默认 0.0 而非 None
            "confidence_weight": 0.0,        # 默认 0.0 而非 None
            "llm_failed": False,             # 标记 LLM 是否失败
            "jina_success_rate": 1.0,        # 默认 100%
            "jina_failed": False,            # 标记 Jina 是否失败
            "note": "",                      # 备注信息
        }

        if self.enable_llm_confidence and query and sources:
            try:
                llm_start = time.time()
                llm_confidence = await self._llm_evaluate_confidence(query, sources, findings, scenario)
                llm_confidence_time = time.time() - llm_start
                from ..config import LLM_CONFIDENCE_WEIGHT
                # 混合评分
                final_confidence = rule_confidence * (1 - LLM_CONFIDENCE_WEIGHT) + llm_confidence * LLM_CONFIDENCE_WEIGHT
                confidence_details["llm_confidence"] = llm_confidence
                confidence_details["confidence_weight"] = LLM_CONFIDENCE_WEIGHT
                print(f"[EnhancedResearch] Confidence: rule={rule_confidence:.2f}, llm={llm_confidence:.2f}, final={final_confidence:.2f} (LLM耗时: {llm_confidence_time:.2f}s)")
            except Exception as e:
                print(f"[WARN] LLM confidence evaluation failed: {e}, using rule-based only")
                final_confidence = rule_confidence
                confidence_details["llm_failed"] = True
                confidence_details["note"] = f"LLM 评分失败: {str(e)[:100]}"
        else:
            final_confidence = rule_confidence

        # Jina 失败处理策略：
        # - Jina 是"加分项"而非"必需项"，失败时不惩罚 confidence
        # - Jina 失败已通过 enhanced_boost = 0 自然体现（没有深度内容就没有加分）
        # - 只要 Serper 结果数量足够，confidence 仍可达到退出阈值
        #
        # 计算示例（假设 scenario_weight = 0.9）：
        # - Serper 3 个结果 + Jina 全失败: (0.5 + 0.3 + 0) * 0.9 = 0.72 ✓ 可退出
        # - Serper 2 个结果 + Jina 全失败: (0.5 + 0.2 + 0) * 0.9 = 0.63 → 继续搜索
        if jina_success_rate == 0.0 and len(sources) > 0:
            # 标记 Jina 失败，但不惩罚 confidence
            confidence_details["jina_success_rate"] = 0.0
            confidence_details["jina_failed"] = True
            confidence_details["note"] = "Jina 深度读取失败，但 Serper 结果可用，不惩罚 confidence"
            print(f"[EnhancedResearch] Jina 成功率 0%，但不惩罚 confidence（当前值: {final_confidence:.2f}）")

        final_confidence = min(final_confidence, 0.95)  # 最大0.95

        return {
            "confidence": final_confidence,  # 向后兼容
            "rule_confidence": rule_confidence,
            "llm_confidence": llm_confidence,
            "llm_confidence_time": llm_confidence_time,  # LLM 评估耗时
            "confidence_details": confidence_details
        }
    
    async def _llm_evaluate_confidence(self, query: str, sources: List[Source], 
                                      findings: List[str], scenario: ResearchScenario) -> float:
        """使用 LLM 评估信息质量和相关性"""
        if not self.llm_model or not sources:
            return 0.5  # 默认值
        
        # 构建评估 prompt（只评估前5个源以节省token）
        sources_summary = "\n".join([
            f"- {src.title}: {src.snippet[:200]}..." 
            for src in sources[:5]
        ])
        
        findings_summary = "\n".join(findings[:3]) if findings else "无明确发现"
        
        prompt = f"""评估以下搜索结果的信息质量和相关性。

查询: {query}

搜索结果摘要:
{sources_summary}

关键发现:
{findings_summary}

请从以下维度评估（每个维度0-1分）:
## 评分标准（严格按此打分）

### relevance（相关性）
- 0.9-1.0: 所有结果直接回答查询，高度相关
- 0.7-0.8: 大部分结果相关，少数偏题
- 0.5-0.6: 部分相关，但有明显遗漏
- 0.3-0.4: 结果较少相关，多数偏题
- 0.0-0.2: 几乎不相关或无结果

### quality（来源质量）
- 0.9-1.0: 权威来源（Nature/Science/政府/顶级机构）
- 0.7-0.8: 可靠来源（知名媒体/学术期刊/企业官网）
- 0.5-0.6: 一般来源（行业网站/新闻）
- 0.3-0.4: 低质量来源（论坛/博客）
- 0.0-0.2: 无来源或不可靠

### completeness（完整性）
- 0.9-1.0: 完整覆盖查询所有关键点
- 0.7-0.8: 覆盖主要点，少数细节缺失
- 0.5-0.6: 覆盖部分要点，有明显遗漏
- 0.3-0.4: 只覆盖少数点
- 0.0-0.2: 几乎没有有效信息

### consistency（一致性）
- 0.9-1.0: 所有结果信息一致，无矛盾
- 0.7-0.8: 大部分结果信息一致，少数矛盾
- 0.5-0.6: 部分结果信息一致，但有明显矛盾
- 0.3-0.4: 结果信息不一致，多数矛盾
- 0.0-0.2: 几乎不一致或无结果

请以JSON格式返回评分，格式如下:
{{
    "relevance": 0.0-1.0,
    "quality": 0.0-1.0,
    "completeness": 0.0-1.0,
    "consistency": 0.0-1.0,
    "overall_confidence": 0.0-1.0
}}"""

        try:
            response = await self.llm_model.acompletion(
                messages=[
                    {"role": "system", "content": "你是一个信息质量评估专家。请客观评估搜索结果的质量，返回有效的JSON格式。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
            )

            import json
            import re
            content = response.choices[0].message.content

            # 方法1：尝试用平衡括号匹配提取完整 JSON
            # 这个方法可以正确处理嵌套的 JSON 对象
            def extract_json_with_balanced_braces(text: str) -> str:
                """提取第一个完整的 JSON 对象（支持嵌套）"""
                start = text.find('{')
                if start == -1:
                    return None
                depth = 0
                for i, char in enumerate(text[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            return text[start:i+1]
                return None

            json_str = extract_json_with_balanced_braces(content)
            if json_str:
                try:
                    result = json.loads(json_str)
                    overall = float(result.get("overall_confidence", 0.5))
                    return max(0.0, min(1.0, overall))
                except json.JSONDecodeError:
                    pass  # 继续尝试其他方法

            # 方法2：尝试直接解析整个内容（如果 LLM 只返回了 JSON）
            try:
                result = json.loads(content.strip())
                overall = float(result.get("overall_confidence", 0.5))
                return max(0.0, min(1.0, overall))
            except json.JSONDecodeError:
                pass

            # 方法3：后备方案 - 提取 "overall_confidence": 0.x 格式
            # 比通用数字匹配更精确，避免误匹配其他数字
            confidence_match = re.search(r'"overall_confidence"\s*:\s*(0\.\d+|1\.0|0|1)', content)
            if confidence_match:
                return max(0.0, min(1.0, float(confidence_match.group(1))))

            print(f"[WARN] Could not parse LLM confidence response: {content[:200]}")

        except Exception as e:
            print(f"[WARN] LLM confidence evaluation failed: {e}")

        return 0.5  # 默认值
    
    def get_performance_stats(self) -> Dict:
        """获取性能统计"""
        return self.performance_stats.copy()

# 集成到现有系统的适配器
async def enhanced_web_search_with_jina(query: str, max_results: int = 10, 
                                      task_context: Dict = None) -> str:
    """
    增强搜索的适配器函数，用于替换现有的web_search
    """
    tool = EnhancedResearchTool()
    result = await tool.smart_research(query, max_results, task_context)
    
    # 格式化为字符串输出（兼容现有接口）
    output_lines = []
    output_lines.append(f"研究场景: {result['research_plan'].get('strategy', 'unknown')}")
    output_lines.append(f"置信度: {result['confidence']:.2f}")
    
    # 输出详细的 confidence 信息
    if result.get('llm_confidence') is not None:
        output_lines.append(f"  - 规则评分: {result.get('rule_confidence', 0):.2f}")
        output_lines.append(f"  - LLM评分: {result.get('llm_confidence', 0):.2f}")
        weight = result.get('confidence_details', {}).get('confidence_weight', 0)
        output_lines.append(f"  - 混合权重: 规则{(1-weight)*100:.0f}% + LLM{weight*100:.0f}%")
    else:
        output_lines.append(f"  - 规则评分: {result.get('rule_confidence', result['confidence']):.2f}")
        output_lines.append(f"  - LLM评分: 未启用")
    
    output_lines.append("")
    
    for i, finding in enumerate(result['findings'], 1):
        output_lines.append(f"{i}. {finding}")
    
    output_lines.append("\n来源:")
    for i, source in enumerate(result['sources'], 1):
        output_lines.append(f"[{i}] {source.title}")
        output_lines.append(f"    {source.url}")
        output_lines.append(f"    {source.snippet[:200]}...")
        output_lines.append("")
    
    return "\n".join(output_lines)