"""Tests for the clarifier module."""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from clarifyagent.clarifier import (
    assess_input,
    should_clarify,
    should_start_research,
    build_clarifier
)
from clarifyagent.schema import Plan, Task
from clarifyagent.agent import build_model


@pytest.fixture
def mock_model():
    """Create a mock model for testing."""
    model = Mock()
    return model


@pytest.fixture
def real_model():
    """Create a real model for integration tests (requires API key)."""
    try:
        return build_model()
    except Exception:
        pytest.skip("API key not configured")


class TestClarifierDecisionLogic:
    """Test clarification decision logic."""
    
    def test_should_clarify_low_confidence(self):
        """Test that low confidence triggers clarification."""
        plan = Plan(
            next_action="NEED_CLARIFICATION",
            confidence=0.4,
            task=Task(goal="", research_focus=[])
        )
        assert should_clarify(plan) is True
    
    def test_should_clarify_missing_focus(self):
        """Test that missing research focus triggers clarification."""
        plan = Plan(
            next_action="CONFIRM_PLAN",
            confidence=0.65,
            task=Task(goal="test", research_focus=[])
        )
        assert should_clarify(plan) is True
    
    def test_should_not_clarify_high_confidence(self):
        """Test that high confidence doesn't trigger clarification."""
        plan = Plan(
            next_action="START_RESEARCH",
            confidence=0.9,
            task=Task(goal="test", research_focus=["focus1", "focus2", "focus3"])
        )
        assert should_clarify(plan) is False
    
    def test_should_start_research_high_confidence(self):
        """Test that high confidence triggers start research."""
        plan = Plan(
            next_action="START_RESEARCH",
            confidence=0.9,
            task=Task(
                goal="KRAS G12C 靶点",
                research_focus=["验证证据", "已上市药物", "临床进展", "耐药机制"]
            )
        )
        assert should_start_research(plan) is True
    
    def test_should_not_start_research_low_confidence(self):
        """Test that low confidence doesn't trigger start research."""
        plan = Plan(
            next_action="NEED_CLARIFICATION",
            confidence=0.5,
            task=Task(goal="test", research_focus=["focus1"])
        )
        assert should_start_research(plan) is False
    
    def test_should_not_start_research_insufficient_focus(self):
        """Test that insufficient research focus doesn't trigger start research."""
        plan = Plan(
            next_action="START_RESEARCH",
            confidence=0.9,
            task=Task(goal="test", research_focus=["focus1"])  # Only 1 focus
        )
        assert should_start_research(plan) is False


class TestClarifierIntegration:
    """Integration tests for clarifier (requires API key)."""
    
    @pytest.mark.asyncio
    async def test_assess_sufficient_input(self, real_model):
        """Test assessment of sufficient input."""
        messages = [
            {"role": "user", "content": "KRAS G12C 靶点"}
        ]
        task_draft = {}
        
        plan = await assess_input(real_model, messages, task_draft)
        
        assert plan.next_action in ["START_RESEARCH", "CONFIRM_PLAN"]
        assert plan.confidence >= 0.7
        assert plan.task.goal
        assert len(plan.task.research_focus) >= 2
    
    @pytest.mark.asyncio
    async def test_assess_insufficient_input(self, real_model):
        """Test assessment of insufficient input."""
        messages = [
            {"role": "user", "content": "帮我研究一下"}
        ]
        task_draft = {}
        
        plan = await assess_input(real_model, messages, task_draft)
        
        assert plan.next_action == "NEED_CLARIFICATION"
        assert plan.confidence < 0.7
        assert plan.clarification is not None
        assert "question" in plan.clarification
        assert "options" in plan.clarification
    
    @pytest.mark.asyncio
    async def test_assess_vague_input(self, real_model):
        """Test assessment of vague input."""
        messages = [
            {"role": "user", "content": "那个新药"}
        ]
        task_draft = {}
        
        plan = await assess_input(real_model, messages, task_draft)
        
        # Should need clarification or have low confidence
        assert plan.next_action in ["NEED_CLARIFICATION", "VERIFY_TOPIC"]
        assert plan.confidence < 0.85
    
    @pytest.mark.asyncio
    async def test_assess_with_context(self, real_model):
        """Test assessment with conversation context."""
        messages = [
            {"role": "user", "content": "我想研究 GLP-1"},
            {"role": "assistant", "content": "您想研究 GLP-1 的哪个方面？"},
            {"role": "user", "content": "最新进展"}
        ]
        task_draft = {}
        
        plan = await assess_input(real_model, messages, task_draft)
        
        # With context, should have higher confidence
        assert plan.task.goal
        assert "GLP-1" in plan.task.goal or "最新进展" in plan.task.goal


class TestClarifierExamples:
    """Test clarifier with example inputs from design doc."""
    
    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text,expected_action,min_confidence", [
        ("KRAS G12C 靶点", "START_RESEARCH", 0.85),
        ("GLP-1 激动剂最新进展", "START_RESEARCH", 0.85),
        ("帮我研究一下", "NEED_CLARIFICATION", 0.0),
        ("那个新药", "NEED_CLARIFICATION", 0.0),
        ("GLP-1 激动剂", "CONFIRM_PLAN", 0.7),
    ])
    async def test_example_inputs(self, real_model, input_text, expected_action, min_confidence):
        """Test clarifier with example inputs."""
        messages = [{"role": "user", "content": input_text}]
        task_draft = {}
        
        plan = await assess_input(real_model, messages, task_draft)
        
        # Check action matches expected or is reasonable alternative
        if expected_action == "START_RESEARCH":
            assert plan.next_action in ["START_RESEARCH", "CONFIRM_PLAN"]
        elif expected_action == "NEED_CLARIFICATION":
            assert plan.next_action == "NEED_CLARIFICATION"
        elif expected_action == "CONFIRM_PLAN":
            assert plan.next_action in ["CONFIRM_PLAN", "START_RESEARCH"]
        
        assert plan.confidence >= min_confidence
        
        if plan.next_action == "NEED_CLARIFICATION":
            assert plan.clarification is not None
            assert plan.clarification.get("question")
            assert plan.clarification.get("options")


def run_clarifier_test_interactive():
    """Interactive test function for manual testing."""
    import asyncio
    from clarifyagent.clarifier import assess_input
    from clarifyagent.agent import build_model
    
    async def test():
        model = build_model()
        
        test_cases = [
            "KRAS G12C 靶点",
            "帮我研究一下",
            "GLP-1 激动剂最新进展",
            "那个新药",
            "ADC 药物的 linker 设计",
        ]
        
        for user_input in test_cases:
            print(f"\n{'='*60}")
            print(f"测试输入: {user_input}")
            print('='*60)
            
            messages = [{"role": "user", "content": user_input}]
            task_draft = {}
            
            plan = await assess_input(model, messages, task_draft)
            
            print(f"\n结果:")
            print(f"  next_action: {plan.next_action}")
            print(f"  confidence: {plan.confidence:.2f}")
            print(f"  goal: {plan.task.goal}")
            print(f"  research_focus: {plan.task.research_focus}")
            print(f"  why: {plan.why}")
            
            if plan.clarification:
                print(f"\n澄清问题:")
                print(f"  question: {plan.clarification.get('question')}")
                print(f"  options: {plan.clarification.get('options')}")
                print(f"  missing_info: {plan.clarification.get('missing_info')}")
            
            print()
    
    asyncio.run(test())


if __name__ == "__main__":
    # Run interactive test
    run_clarifier_test_interactive()
