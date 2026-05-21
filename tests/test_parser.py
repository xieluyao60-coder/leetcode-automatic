from lc_auto.leetcode_page import parse_judge_text
from lc_auto.models import Verdict


def test_parse_accepted_text():
    result = parse_judge_text("执行结果\n通过\n显示详情\n添加备注", action="run")
    assert result.verdict == Verdict.ACCEPTED
    assert result.is_success


def test_parse_new_test_result_pass_panel():
    text = """
    题目描述
    通过次数
    测试用例
    测试结果
    通过
    执行用时: 0 ms
    Case 1
    """
    result = parse_judge_text(text, action="run")

    assert result.verdict == Verdict.ACCEPTED


def test_parse_compact_pass_runtime_text():
    result = parse_judge_text("已存储\n行 1，列 1\n通过\n执行用时: 0 ms\nCase 1", action="run")

    assert result.verdict == Verdict.ACCEPTED


def test_parse_wrong_answer_case():
    text = """
    解答错误
    输入：
    nums = [3,2,4]
    target = 6
    输出：
    [0,1]
    预期结果：
    [1,2]
    """
    result = parse_judge_text(text, action="submit")
    assert result.verdict == Verdict.WRONG_ANSWER
    assert "nums" in result.failing_case
    assert "[0,1]" in result.actual
    assert "[1,2]" in result.expected


def test_parse_runtime_error_takes_priority_over_page_pass_text():
    text = """
    题目描述
    通过
    提交记录
    执行出错
    TypeError: <__main__.ListNode object at 0x123> is not valid value for the expected return type ListNode
    """
    result = parse_judge_text(text, action="submit")

    assert result.verdict == Verdict.RUNTIME_ERROR


def test_plain_pass_tab_text_is_not_accepted():
    text = """
    题目描述
    通过
    题解
    提交记录
    """
    result = parse_judge_text(text, action="submit")

    assert result.verdict == Verdict.UNKNOWN
