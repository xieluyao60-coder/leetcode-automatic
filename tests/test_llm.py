from lc_auto.config import ModelConfig
from lc_auto.llm import LLMSolver, extract_code
from lc_auto.models import ProblemSnapshot


def test_extract_code_from_fence():
    text = "```python\nclass Solution:\n    pass\n```"
    assert extract_code(text) == "class Solution:\n    pass"


def test_fake_solver_returns_submit_ready_code():
    solver = LLMSolver(ModelConfig(provider="fake"))
    result = solver.solve(
        ProblemSnapshot(
            slug="two-sum",
            url="https://leetcode.cn/problems/two-sum/",
            title="1. 两数之和",
            statement="给定一个整数数组 nums 和一个整数目标值 target。",
        )
    )
    assert "class Solution" in result.code
    assert "twoSum" in result.code
