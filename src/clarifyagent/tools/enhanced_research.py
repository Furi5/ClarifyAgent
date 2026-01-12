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
    
    def __init__(self):
        self.selector = IntelligentResearchSelector()
        self.performance_stats = {
            'serper_calls': 0,
            'jina_calls': 0,
            'total_time': 0,
            'scenarios_detected': {}
        }
    
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

        # 4. 创建智能研究计划
        research_plan = self.selector.create_research_plan(query, search_results_list)


        print(f"[EnhancedResearch] 研究计划: {len(research_plan['jina_targets'])} 个深度目标")

        # 5. 并行执行深度读取
        enhanced_sources = []
        if research_plan['jina_targets']:
            jina_tasks = []
            for target in research_plan['jina_targets']:
                jina_tasks.append(self._safe_jina_read(target))
            
            jina_start = time.time()
            jina_results = await asyncio.gather(*jina_tasks, return_exceptions=True)
            jina_time = time.time() - jina_start
            self.performance_stats['jina_calls'] += len(jina_tasks)
            
            # 处理Jina结果
            for i, result in enumerate(jina_results):
                if isinstance(result, Exception):
                    print(f"[EnhancedResearch] Jina读取失败: {result}")
                    continue
                if result:
                    enhanced_sources.append(result)
        
        # 5. 合并Serper和Jina结果
        all_sources = self._merge_sources(search_results_list, enhanced_sources)
        
        # 6. 基于场景提取关键发现
        findings = self._extract_scenario_findings(scenario, all_sources, query)
        
        # 7. 计算置信度
        confidence = self._calculate_confidence(scenario, all_sources, len(enhanced_sources))
        
        total_time = time.time() - start_time
        self.performance_stats['total_time'] += total_time
        
        print(f"[EnhancedResearch] 完成: {total_time:.2f}s (Serper: {serper_time:.2f}s, Jina: {jina_time if 'jina_time' in locals() else 0:.2f}s)")
        
        return {
            'findings': findings,
            'sources': all_sources[:8],  # 限制源数量
            'confidence': confidence,
            'research_plan': research_plan,
            'performance': {
                'total_time': total_time,
                'serper_time': serper_time,
                'jina_time': jina_time if 'jina_time' in locals() else 0,
                'enhanced_sources': len(enhanced_sources)
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
        """安全的Jina读取"""
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
            print(f"[EnhancedResearch] Jina读取失败 {target['url']}: {e}")
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
    
    def _calculate_confidence(self, scenario: ResearchScenario, 
                            sources: List[Source], enhanced_count: int) -> float:
        """计算置信度"""
        base_confidence = 0.5
        
        # 基于源的数量
        source_boost = min(len(sources) * 0.1, 0.3)
        
        # 基于深度内容的数量
        enhanced_boost = min(enhanced_count * 0.15, 0.3)
        
        # 基于场景的权重
        scenario_weights = {
            ResearchScenario.RETROSYNTHESIS: 0.8,  # 技术内容相对确定
            ResearchScenario.PIPELINE_EVALUATION: 0.7,  # 商业分析有主观性
            ResearchScenario.CLINICAL_PIPELINE: 0.9,  # 临床数据相对客观
        }
        
        scenario_weight = scenario_weights.get(scenario, 0.6)
        
        confidence = (base_confidence + source_boost + enhanced_boost) * scenario_weight
        return min(confidence, 0.95)  # 最大0.95
    
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