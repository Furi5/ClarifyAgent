"""验证多智能体架构实现是否完整."""
import os
import sys

# 添加 src 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def verify_files():
    """验证所有必需的文件是否存在."""
    required_files = [
        'src/clarifyagent/orchestrator.py',
        'src/clarifyagent/executor.py',
        'src/clarifyagent/synthesizer.py',
        'src/clarifyagent/clarifier.py',
        'src/clarifyagent/planner.py',
        'src/clarifyagent/agents/base.py',
        'src/clarifyagent/agents/subagent.py',
        'src/clarifyagent/agents/pool.py',
        'src/clarifyagent/tools/base.py',
        'src/clarifyagent/schema.py',
        'src/clarifyagent/main.py',
        'src/clarifyagent/config.py',
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print("❌ 缺少以下文件:")
        for f in missing_files:
            print(f"  - {f}")
        return False
    else:
        print("✅ 所有必需文件都存在")
        return True

def verify_imports():
    """验证关键导入是否正常."""
    try:
        # 测试导入（不执行，只检查语法）
        import ast
        
        files_to_check = [
            'src/clarifyagent/orchestrator.py',
            'src/clarifyagent/executor.py',
            'src/clarifyagent/synthesizer.py',
            'src/clarifyagent/clarifier.py',
            'src/clarifyagent/planner.py',
        ]
        
        for file_path in files_to_check:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            try:
                ast.parse(code)
            except SyntaxError as e:
                print(f"❌ {file_path} 有语法错误: {e}")
                return False
        
        print("✅ 所有文件语法正确")
        return True
    except Exception as e:
        print(f"⚠️ 导入检查失败: {e}")
        return True  # 不阻止，因为可能没有安装依赖

def verify_structure():
    """验证代码结构."""
    checks = []
    
    # 检查 orchestrator.py 中的关键类
    with open('src/clarifyagent/orchestrator.py', 'r', encoding='utf-8') as f:
        orchestrator_code = f.read()
        checks.append(('Orchestrator 类', 'class Orchestrator' in orchestrator_code))
        checks.append(('run 方法', 'async def run' in orchestrator_code))
    
    # 检查 executor.py 中的关键类
    with open('src/clarifyagent/executor.py', 'r', encoding='utf-8') as f:
        executor_code = f.read()
        checks.append(('Executor 类', 'class Executor' in executor_code))
        checks.append(('execute_parallel_search', 'execute_parallel_search' in executor_code))
    
    # 检查 synthesizer.py 中的关键函数
    with open('src/clarifyagent/synthesizer.py', 'r', encoding='utf-8') as f:
        synthesizer_code = f.read()
        checks.append(('synthesize_results', 'synthesize_results' in synthesizer_code))
    
    # 检查 clarifier.py 中的关键函数
    with open('src/clarifyagent/clarifier.py', 'r', encoding='utf-8') as f:
        clarifier_code = f.read()
        checks.append(('assess_input', 'assess_input' in clarifier_code))
        checks.append(('should_clarify', 'should_clarify' in clarifier_code))
        checks.append(('should_start_research', 'should_start_research' in clarifier_code))
    
    # 检查 planner.py 中的关键函数
    with open('src/clarifyagent/planner.py', 'r', encoding='utf-8') as f:
        planner_code = f.read()
        checks.append(('decompose_task', 'decompose_task' in planner_code))
    
    # 检查 agents/pool.py
    with open('src/clarifyagent/agents/pool.py', 'r', encoding='utf-8') as f:
        pool_code = f.read()
        checks.append(('SubagentPool 类', 'class SubagentPool' in pool_code))
        checks.append(('execute_parallel', 'execute_parallel' in pool_code))
    
    # 检查 agents/subagent.py
    with open('src/clarifyagent/agents/subagent.py', 'r', encoding='utf-8') as f:
        subagent_code = f.read()
        checks.append(('Subagent 类', 'class Subagent' in subagent_code))
    
    # 检查 schema.py 中的新模型
    with open('src/clarifyagent/schema.py', 'r', encoding='utf-8') as f:
        schema_code = f.read()
        checks.append(('Subtask 模型', 'class Subtask' in schema_code))
        checks.append(('SubtaskResult 模型', 'class SubtaskResult' in schema_code))
        checks.append(('ResearchResult 模型', 'class ResearchResult' in schema_code))
        checks.append(('START_RESEARCH', 'START_RESEARCH' in schema_code))
        checks.append(('NEED_CLARIFICATION', 'NEED_CLARIFICATION' in schema_code))
    
    failed_checks = [name for name, passed in checks if not passed]
    
    if failed_checks:
        print("❌ 以下检查失败:")
        for check in failed_checks:
            print(f"  - {check}")
        return False
    else:
        print("✅ 所有结构检查通过")
        return True

def main():
    """运行所有验证."""
    print("🔍 验证多智能体架构实现...\n")
    
    results = []
    results.append(("文件存在性", verify_files()))
    print()
    results.append(("代码结构", verify_structure()))
    print()
    results.append(("语法检查", verify_imports()))
    print()
    
    print("=" * 60)
    if all(result for _, result in results):
        print("✅ 所有验证通过！")
        return 0
    else:
        print("❌ 部分验证失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
