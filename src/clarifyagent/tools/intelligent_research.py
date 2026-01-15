"""
场景驱动的智能研究工具选择器
根据研究场景和数据源智能选择Serper vs Jina
"""
import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

class ResearchScenario(Enum):
    """研究场景类型"""
    RETROSYNTHESIS = "逆合成路线"
    PIPELINE_EVALUATION = "管线立项评估" 
    CLINICAL_PIPELINE = "临床管线调研"
    MARKET_ANALYSIS = "市场分析"
    REGULATORY_REVIEW = "监管审评"
    ACADEMIC_RESEARCH = "学术研究"
    COMPETITIVE_INTELLIGENCE = "竞争情报"

@dataclass
class SourceRule:
    """数据源规则"""
    domains: List[str]
    content_indicators: List[str]  # 内容关键词
    jina_priority: int  # 1-5, 5最高优先级
    reason: str

# 场景驱动的源优先级规则
SCENARIO_RULES = {
    ResearchScenario.RETROSYNTHESIS: [
        SourceRule(
            domains=['reaxys.com', 'scifinder.cas.org', 'organic-chemistry.org'],
            content_indicators=['synthesis', 'reaction', 'yield', 'procedure'],
            jina_priority=5,
            reason="合成路线需要完整的反应步骤和条件"
        ),
        SourceRule(
            domains=['patents.google.com', 'uspto.gov', 'espacenet.ops.epo.org'],
            content_indicators=['patent', 'synthesis', 'preparation', 'example'],
            jina_priority=4,
            reason="专利中包含详细的合成实施例"
        ),
        SourceRule(
            domains=['pubmed.ncbi.nlm.nih.gov', 'acs.org', 'rsc.org'],
            content_indicators=['total synthesis', 'synthetic route', 'methodology'],
            jina_priority=4,
            reason="学术文献提供方法学细节"
        )
    ],
    
    ResearchScenario.PIPELINE_EVALUATION: [
        SourceRule(
            domains=['sec.gov', 'investors.*.com'],
            content_indicators=['10-K', '10-Q', 'pipeline', 'R&D', 'clinical'],
            jina_priority=5,
            reason="财务文件包含管线投资和商业化策略"
        ),
        SourceRule(
            domains=['clinicaltrials.gov'],
            content_indicators=['phase', 'enrollment', 'endpoint', 'status'],
            jina_priority=4,
            reason="临床试验详情反映开发进度和竞争态势"
        ),
        SourceRule(
            domains=['fda.gov', 'ema.europa.eu'],
            content_indicators=['guidance', 'breakthrough', 'designation', 'approval'],
            jina_priority=4,
            reason="监管文件明确开发路径和要求"
        )
    ],
    
    ResearchScenario.CLINICAL_PIPELINE: [
        SourceRule(
            domains=['clinicaltrials.gov'],
            content_indicators=['protocol', 'inclusion', 'exclusion', 'primary endpoint'],
            jina_priority=5,
            reason="完整试验协议包含关键设计信息"
        ),
        SourceRule(
            domains=['nejm.org', 'thelancet.com', 'jco.org'],
            content_indicators=['clinical trial', 'efficacy', 'safety', 'survival'],
            jina_priority=5,
            reason="顶级期刊的临床数据分析最权威"
        ),
        SourceRule(
            domains=['fda.gov'],
            content_indicators=['ODAC', 'advisory committee', 'review', 'approval'],
            jina_priority=4,
            reason="FDA审评文件提供监管视角"
        )
    ]
}

# 高价值域名模式（总是优先使用Jina）
HIGH_VALUE_DOMAINS = {
    # 学术出版社
    'pubmed.ncbi.nlm.nih.gov': 'PubMed全文',
    'nejm.org': '新英格兰医学杂志', 
    'thelancet.com': '柳叶刀',
    'nature.com': 'Nature系列',
    'science.org': 'Science',
    'cell.com': 'Cell系列',
    
    # 监管机构
    'fda.gov': 'FDA官方文件',
    'ema.europa.eu': 'EMA文件',
    'ich.org': 'ICH指导原则',
    
    # 商业情报
    'sec.gov': 'SEC财务文件',
    'investors.*.com': '投资者关系页面',
    
    # 专业数据库
    'clinicaltrials.gov': '临床试验注册信息',
    'patents.google.com': '专利全文',
    'reaxys.com': '化学数据库',
    'scifinder.cas.org': 'CAS数据库'
}

class IntelligentResearchSelector:
    """智能研究工具选择器"""
    
    def __init__(self):
        self.scenario = None
        self.query_analysis = None
    
    def detect_scenario(self, query: str, task_context: Dict) -> ResearchScenario:
        """检测研究场景"""
        query_lower = query.lower()
        context_text = str(task_context).lower()
        combined_text = f"{query_lower} {context_text}"
        
        # 场景关键词匹配
        scenario_keywords = {
            ResearchScenario.RETROSYNTHESIS: [
                '合成路线', '逆合成', 'synthesis', 'retrosynthesis', 
                '反应条件', '制备方法', 'preparation', 'synthetic route'
            ],
            ResearchScenario.PIPELINE_EVALUATION: [
                '管线', 'pipeline', '立项', '投资', '商业化', 
                'R&D', '研发投入', '市场潜力', 'valuation'
            ],
            ResearchScenario.CLINICAL_PIPELINE: [
                '临床试验', 'clinical trial', '临床数据', 'efficacy',
                '安全性', 'safety', '疗效', 'endpoint'
            ],
            ResearchScenario.REGULATORY_REVIEW: [
                'FDA', 'EMA', '监管', '审评', 'approval', 
                '获批', '指导原则', 'guidance'
            ]
        }
        
        max_score = 0
        detected_scenario = ResearchScenario.ACADEMIC_RESEARCH  # 默认
        
        for scenario, keywords in scenario_keywords.items():
            score = sum(1 for kw in keywords if kw in combined_text)
            if score > max_score:
                max_score = score
                detected_scenario = scenario
        
        self.scenario = detected_scenario
        return detected_scenario
    
    def should_use_jina(self, url: str, title: str = "", snippet: str = "") -> Tuple[bool, int, str]:
        """
        判断是否应该使用Jina深度读取
        
        Returns:
            (should_use, priority, reason)
        """
        # 检查高价值域名
        for domain_pattern, description in HIGH_VALUE_DOMAINS.items():
            if '*' in domain_pattern:
                # 处理通配符模式，如 investors.*.com
                regex_pattern = domain_pattern.replace('*', r'[^.]+')
                if re.search(regex_pattern, url):
                    return True, 5, f"高价值域名: {description}"
            elif domain_pattern in url:
                return True, 5, f"高价值域名: {description}"
        
        # 基于场景的规则匹配
        if self.scenario and self.scenario in SCENARIO_RULES:
            rules = SCENARIO_RULES[self.scenario]
            content_text = f"{title} {snippet}".lower()
            
            for rule in rules:
                # 检查域名匹配
                domain_match = any(domain in url for domain in rule.domains)
                # 检查内容指标
                content_match = any(indicator in content_text 
                                  for indicator in rule.content_indicators)
                
                if domain_match or content_match:
                    return True, rule.jina_priority, rule.reason
        
        # 默认情况：短snippet可能信息不足
        # 但对于简单任务，即使 snippet 短，也可能不需要深度读取
        # 这个判断会在 create_research_plan 中根据 max_results 进一步筛选
        if len(snippet) < 300:
            return True, 2, "信息片段较短，需要完整内容以获取更多细节"

        return False, 0, "Serper信息充足"
    
    def create_research_plan(self, query: str, search_results: List[Dict], max_results: int = 10) -> Dict:
        """
        创建智能研究计划
        
        Args:
            query: 研究查询
            search_results: Serper搜索结果
            max_results: 搜索结果总数（用于动态调整Jina目标数量）
            
        Returns:
            研究计划字典
        """
        scenario = self.detect_scenario(query, {})
        
        plan = {
            'scenario': scenario.value,
            'strategy': 'hybrid',  # serper + selective jina
            'serper_results': [],
            'jina_targets': [],
            'reasoning': []
        }
        
        # 根据 max_results 动态调整分析范围
        # 简单任务（max_results <= 8）只分析所有结果
        # 复杂任务（max_results > 15）分析前 15 个
        analysis_limit = min(len(search_results), max(max_results, 15))
        
        for i, result in enumerate(search_results[:analysis_limit]):
            url = result.get('url', '')
            title = result.get('title', '')
            snippet = result.get('snippet', '')
            
            should_use, priority, reason = self.should_use_jina(url, title, snippet)
            
            if should_use and priority >= 2:  # 中等及以上优先级使用Jina（降低阈值以获取更多深度信息）
                plan['jina_targets'].append({
                    'url': url,
                    'title': title,
                    'priority': priority,
                    'reason': reason,
                    'rank': i + 1
                })
            else:
                plan['serper_results'].append({
                    'url': url,
                    'title': title,
                    'snippet': snippet,
                    'rank': i + 1
                })
        
        # 根据 max_results 动态调整 Jina 目标数量
        # 简单任务（max_results <= 8）: 最多 1-2 个 Jina 目标
        # 标准任务（8 < max_results <= 15）: 最多 8 个
        # 复杂任务（max_results > 15）: 最多 15 个
        if max_results <= 8:
            max_jina_targets = min(0, len(plan['jina_targets']))  # 简单任务最多3个
        elif max_results <= 15:
            max_jina_targets = min(0, len(plan['jina_targets']))  # 标准任务最多3个
        else:
            max_jina_targets = min(0, len(plan['jina_targets']))  # 复杂任务最多5个
        
        # 限制Jina调用数量以控制成本和时间
        plan['jina_targets'] = sorted(
            plan['jina_targets'],
            key=lambda x: (x['priority'], -x['rank'])
        )[:max_jina_targets]
        
        plan['reasoning'].append(f"检测到研究场景: {scenario.value}")
        plan['reasoning'].append(f"根据 max_results={max_results}，计划深度读取 {len(plan['jina_targets'])} 个高价值源（上限: {max_jina_targets}）")
        
        # #region agent log
        import json as json_mod
        import time
        try:
            with open('/Users/fl/Desktop/my_code/clarifyagent/.cursor/debug.log', 'a') as f:
                f.write(json_mod.dumps({'sessionId': 'debug-session', 'runId': 'run1', 'hypothesisId': 'JINA_TARGETS', 'location': 'intelligent_research.py:create_research_plan', 'message': 'Jina targets determined', 'data': {'max_results': max_results, 'total_candidates': len([t for t in plan['jina_targets'] if t.get('priority', 0) >= 2]), 'max_jina_targets': max_jina_targets, 'final_count': len(plan['jina_targets']), 'scenario': scenario.value}, 'timestamp': time.time() * 1000}) + '\n')
        except: pass
        # #endregion
        
        return plan

# 使用示例
def example_usage():
    selector = IntelligentResearchSelector()
    
    # 示例1：逆合成路线研究
    query1 = "阿托伐他汀的工业化合成路线和关键中间体制备"
    scenario1 = selector.detect_scenario(query1, {})
    print(f"场景1: {scenario1.value}")
    
    # 示例2：管线评估
    query2 = "罗氏PD-L1抗体管线的商业价值和竞争优势分析"  
    scenario2 = selector.detect_scenario(query2, {})
    print(f"场景2: {scenario2.value}")

if __name__ == "__main__":
    example_usage()