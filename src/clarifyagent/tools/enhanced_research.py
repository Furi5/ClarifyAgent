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
        
        # 2. Serper快速搜索获取候选源
        serper_start = time.time()
        search_results = await web_search(query, max_results)
        self.performance_stats['serper_calls'] += 1
        serper_time = time.time() - serper_start
        
        if not search_results:
            return {
                'findings': ['搜索未找到相关结果'],
                'sources': [],
                'confidence': 0.0,
                'research_plan': {'strategy': 'failed'}
            }
        
        # 3. 创建智能研究计划
        search_results_list = self._parse_search_results(search_results)
        research_plan = self.selector.create_research_plan(query, search_results_list)
        
        print(f"[EnhancedResearch] 研究计划: {len(research_plan['jina_targets'])} 个深度目标")
        
        # 4. 并行执行深度读取
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
        """解析Serper搜索结果（从格式化文本中提取结构化数据）"""
        results = []
        lines = search_results.split('\n')
        current_result = {}
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 寻找结果条目的开始（通常是序号形式如 "1. Title"）
            if line and (line[0].isdigit() or line.startswith('##')):
                # 提取标题
                if '.' in line and not line.startswith('##'):
                    # 格式: "1. Title text"
                    title_start = line.find('.') + 1
                    title = line[title_start:].strip()
                elif line.startswith('##'):
                    # 格式: "## Title text"
                    title = line[2:].strip()
                else:
                    title = line
                
                # 查找下一行的URL
                url = ""
                snippet = ""
                j = i + 1
                while j < len(lines):
                    next_line = lines[j].strip()
                    if next_line.startswith('http'):
                        url = next_line
                    elif next_line and not next_line.startswith('http') and not (next_line[0].isdigit() if next_line else False):
                        # 这是snippet内容
                        if snippet:
                            snippet += " " + next_line
                        else:
                            snippet = next_line
                    elif next_line and (next_line[0].isdigit() if next_line else False):
                        # 下一个结果开始了
                        break
                    j += 1
                
                if title:  # 只添加有效的结果
                    results.append({
                        'title': title,
                        'url': url,
                        'snippet': snippet[:500] if snippet else ""  # 限制snippet长度
                    })
                
                i = j - 1  # 移动到处理过的位置
            i += 1
        
        # 如果解析失败，尝试简单的行分割方式
        if not results:
            current_result = {}
            for line in lines:
                line = line.strip()
                if line.startswith('Title:'):
                    if current_result:
                        results.append(current_result)
                    current_result = {'title': line[6:].strip()}
                elif line.startswith('URL:'):
                    current_result['url'] = line[4:].strip()
                elif line.startswith('Snippet:'):
                    current_result['snippet'] = line[8:].strip()
            
            if current_result:
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