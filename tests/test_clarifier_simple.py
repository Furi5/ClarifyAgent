"""Simple test script for clarifier - can run without pytest."""
import asyncio
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from clarifyagent.clarifier import assess_input, should_clarify, should_start_research
from clarifyagent.agent import build_model
from clarifyagent.schema import Plan, Task


async def test_clarifier():
    """Simple test function."""
    print("🧪 澄清模块测试\n")
    
    try:
        model = build_model()
    except Exception as e:
        print(f"❌ 无法创建模型: {e}")
        print("请确保设置了 DEEPSEEK_API_KEY 环境变量")
        return
    
    test_cases = [
        {
            "input": "KRAS G12C 靶点",
            "description": "明确主题，应该可以直接开始研究"
        },
        {
            "input": "帮我研究一下",
            "description": "主题缺失，应该需要澄清"
        },
        {
            "input": "GLP-1 激动剂最新进展",
            "description": "主题和目标明确，应该可以直接开始"
        },
        {
            "input": "那个新药",
            "description": "主题不明确，应该需要澄清"
        },
        {
            "input": "ADC 药物的 linker 设计",
            "description": "主题明确，应该可以推断研究重点"
        },
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"测试 {i}/{len(test_cases)}: {test_case['description']}")
        print(f"输入: {test_case['input']}")
        print('='*70)
        
        try:
            messages = [{"role": "user", "content": test_case['input']}]
            task_draft = {}
            
            plan = await assess_input(model, messages, task_draft)
            
            print(f"\n✅ 评估结果:")
            print(f"  Action: {plan.next_action}")
            print(f"  Confidence: {plan.confidence:.2f}")
            print(f"  Goal: {plan.task.goal}")
            print(f"  Research Focus: {plan.task.research_focus}")
            print(f"  Why: {plan.why}")
            
            # Test decision functions
            needs_clarify = should_clarify(plan)
            can_start = should_start_research(plan)
            
            print(f"\n📊 决策函数结果:")
            print(f"  should_clarify(): {needs_clarify}")
            print(f"  should_start_research(): {can_start}")
            
            if plan.clarification:
                print(f"\n❓ 澄清问题:")
                print(f"  Question: {plan.clarification.get('question')}")
                print(f"  Options:")
                for j, opt in enumerate(plan.clarification.get('options', []), 1):
                    print(f"    {j}) {opt}")
                print(f"  Missing Info: {plan.clarification.get('missing_info')}")
            
            if plan.assumptions:
                print(f"\n💭 假设:")
                for assumption in plan.assumptions:
                    print(f"  - {assumption}")
            
        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*70}")
    print("测试完成！")
    print('='*70)


if __name__ == "__main__":
    asyncio.run(test_clarifier())
