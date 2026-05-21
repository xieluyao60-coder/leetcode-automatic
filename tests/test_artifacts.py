from pathlib import Path

from lc_auto.artifacts import ArtifactWriter
from lc_auto.models import JudgeResult, ProblemSnapshot, Verdict


def test_artifact_writer_saves_problem_and_attempt(tmp_path: Path):
    writer = ArtifactWriter(tmp_path, save_screenshots=False, save_page_html=False)
    problem = ProblemSnapshot(
        slug="two-sum",
        url="https://leetcode.cn/problems/two-sum/",
        title="Two Sum",
        statement="statement",
        code_template="class Solution:\n    pass",
    )

    writer.save_problem(problem)
    writer.save_attempt(
        "two-sum",
        1,
        "run",
        "class Solution:\n    pass",
        JudgeResult(verdict=Verdict.ACCEPTED, raw_text="通过", message="通过"),
        llm_raw="raw",
    )

    assert (tmp_path / "two-sum" / "problem.json").exists()
    assert (tmp_path / "two-sum" / "attempt_001_run.py").exists()
    assert (tmp_path / "two-sum" / "attempt_001_run_result.json").exists()


def test_page_artifact_capture_errors_do_not_abort(tmp_path: Path):
    class FailingPage:
        def save_screenshot(self, path: Path) -> None:
            raise TimeoutError("screenshot timed out")

        def save_html(self, path: Path) -> None:
            raise RuntimeError("html capture failed")

    writer = ArtifactWriter(tmp_path, save_screenshots=True, save_page_html=True)

    writer.save_page_artifacts("two-sum", FailingPage(), "opened")

    assert (tmp_path / "two-sum").exists()
