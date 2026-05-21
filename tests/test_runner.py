from pathlib import Path

from lc_auto.config import AppConfig, ModelConfig
from lc_auto.llm import LLMSolver
from lc_auto.models import JudgeResult, ProblemSnapshot, Verdict
from lc_auto.runner import AutomationRunner
from lc_auto.state import StateStore


class FakePage:
    def __init__(self, verdicts=None, slugs=None, submit_verdicts=None):
        self.verdicts = list(verdicts or [])
        self.submit_verdicts = list(submit_verdicts or [])
        self.slugs = slugs or ["two-sum"]
        self.slug_index = 0
        self.filled = []
        self.submitted = False
        self.run_calls = 0
        self.submit_calls = 0
        self.next_clicks = 0

    def open_problem(self, slug):
        if slug not in self.slugs:
            self.slugs.insert(0, slug)
            self.slug_index = 0
        else:
            self.slug_index = self.slugs.index(slug)

    def current_slug(self):
        return self.slugs[self.slug_index]

    def go_next_problem(self):
        self.next_clicks += 1
        self.slug_index += 1
        return self.current_slug()

    def extract_problem(self, slug):
        return ProblemSnapshot(
            slug=slug,
            url=f"https://leetcode.cn/problems/{slug}/",
            title="Two Sum",
            statement="Example and constraints text " * 10,
        )

    def fill_code(self, code):
        self.filled.append(code)

    def run_code(self):
        self.run_calls += 1
        return self.verdicts.pop(0)

    def submit_code(self):
        self.submitted = True
        self.submit_calls += 1
        if self.submit_verdicts:
            return self.submit_verdicts.pop(0)
        return JudgeResult(Verdict.ACCEPTED, "Accepted", "Accepted")


def test_runner_dry_run_stops_after_run_pass(tmp_path: Path):
    config = AppConfig(
        model=ModelConfig(provider="fake"),
        run_before_submit=True,
        max_repairs_per_problem=1,
        min_delay_seconds=0,
        max_delay_seconds=0,
    )
    store = StateStore(tmp_path / "state.sqlite3")
    page = FakePage([JudgeResult(Verdict.ACCEPTED, "通过", "通过")])
    runner = AutomationRunner(config, page, LLMSolver(config.model), store)

    result = runner.run_problem("two-sum", allow_submit=False)

    assert result.verdict == Verdict.ACCEPTED
    assert result.submitted is False
    assert page.submitted is False
    assert store.get_problem_status("two-sum") == Verdict.ACCEPTED.value


def test_runner_repairs_after_wrong_answer(tmp_path: Path):
    config = AppConfig(
        model=ModelConfig(provider="fake"),
        run_before_submit=True,
        max_repairs_per_problem=1,
        min_delay_seconds=0,
        max_delay_seconds=0,
    )
    store = StateStore(tmp_path / "state.sqlite3")
    page = FakePage(
        [
            JudgeResult(Verdict.WRONG_ANSWER, "解答错误", "解答错误", failing_case="nums=[3,2,4]"),
            JudgeResult(Verdict.ACCEPTED, "通过", "通过"),
        ]
    )
    runner = AutomationRunner(config, page, LLMSolver(config.model), store)

    result = runner.run_problem("two-sum", allow_submit=False)

    assert result.verdict == Verdict.ACCEPTED
    assert len(page.filled) == 2
    attempts = list(store.iter_attempts("two-sum"))
    assert len(attempts) == 2


def test_runner_submits_directly_without_pre_run(tmp_path: Path):
    config = AppConfig(
        model=ModelConfig(provider="fake"),
        allow_real_submit=True,
        max_repairs_per_problem=1,
        min_delay_seconds=0,
        max_delay_seconds=0,
    )
    store = StateStore(tmp_path / "state.sqlite3")
    page = FakePage(submit_verdicts=[JudgeResult(Verdict.ACCEPTED, "Accepted", "Accepted")])
    runner = AutomationRunner(config, page, LLMSolver(config.model), store)

    result = runner.run_problem("two-sum", allow_submit=True)

    assert result.verdict == Verdict.ACCEPTED
    assert result.submitted is True
    assert page.run_calls == 0
    assert page.submit_calls == 1
    attempts = list(store.iter_attempts("two-sum"))
    assert len(attempts) == 1
    assert attempts[0]["phase"] == "submit"


def test_runner_repairs_after_submit_failure_without_pre_run(tmp_path: Path):
    config = AppConfig(
        model=ModelConfig(provider="fake"),
        allow_real_submit=True,
        max_repairs_per_problem=1,
        min_delay_seconds=0,
        max_delay_seconds=0,
    )
    store = StateStore(tmp_path / "state.sqlite3")
    page = FakePage(
        submit_verdicts=[
            JudgeResult(Verdict.RUNTIME_ERROR, "执行出错", "执行出错", failing_case="case"),
            JudgeResult(Verdict.ACCEPTED, "Accepted", "Accepted"),
        ]
    )
    runner = AutomationRunner(config, page, LLMSolver(config.model), store)

    result = runner.run_problem("two-sum", allow_submit=True)

    assert result.verdict == Verdict.ACCEPTED
    assert page.run_calls == 0
    assert page.submit_calls == 2
    assert len(page.filled) == 2


def test_runner_page_chain_clicks_next_after_submitted_ac(tmp_path: Path):
    config = AppConfig(
        model=ModelConfig(provider="fake"),
        max_questions_per_run=2,
        max_repairs_per_problem=0,
        min_delay_seconds=0,
        max_delay_seconds=0,
        allow_real_submit=True,
    )
    store = StateStore(tmp_path / "state.sqlite3")
    page = FakePage(
        [
            JudgeResult(Verdict.ACCEPTED, "通过", "通过"),
            JudgeResult(Verdict.ACCEPTED, "通过", "通过"),
        ],
        slugs=["two-sum", "add-two-numbers"],
    )
    runner = AutomationRunner(config, page, LLMSolver(config.model), store)

    results = runner.run_page_chain(start_slug="two-sum", allow_submit=True)

    assert [result.slug for result in results] == ["two-sum", "add-two-numbers"]
    assert all(result.submitted for result in results)
    assert page.next_clicks == 1


def test_runner_page_chain_dry_run_does_not_click_next(tmp_path: Path):
    config = AppConfig(
        model=ModelConfig(provider="fake"),
        max_questions_per_run=2,
        max_repairs_per_problem=0,
        min_delay_seconds=0,
        max_delay_seconds=0,
    )
    store = StateStore(tmp_path / "state.sqlite3")
    page = FakePage(
        [JudgeResult(Verdict.ACCEPTED, "通过", "通过")],
        slugs=["two-sum", "add-two-numbers"],
    )
    runner = AutomationRunner(config, page, LLMSolver(config.model), store)

    results = runner.run_page_chain(start_slug="two-sum", allow_submit=False)

    assert [result.slug for result in results] == ["two-sum"]
    assert results[0].submitted is False
    assert page.next_clicks == 0
