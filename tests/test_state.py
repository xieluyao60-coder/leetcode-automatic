from pathlib import Path

from lc_auto.models import ProblemSummary, Verdict
from lc_auto.state import StateStore


def test_mark_final_creates_placeholder_problem(tmp_path: Path):
    store = StateStore(tmp_path / "state.sqlite3")

    store.mark_final("missing-problem", Verdict.PAGE_ERROR, submitted=False, message="failed early")

    rows = store.list_problem_rows()
    assert rows[0]["slug"] == "missing-problem"
    assert rows[0]["status"] == Verdict.PAGE_ERROR.value


def test_dry_run_accepted_is_not_treated_as_submitted_ac(tmp_path: Path):
    store = StateStore(tmp_path / "state.sqlite3")

    store.mark_final("two-sum", Verdict.ACCEPTED, submitted=False, message="dry-run passed")

    assert store.has_accepted("two-sum") is False
    assert store.list_unfinished() == ["two-sum"]

    store.mark_final("two-sum", Verdict.ACCEPTED, submitted=True, message="accepted")

    assert store.has_accepted("two-sum") is True
    assert store.list_unfinished() == []


def test_unsupported_language_is_not_resumed(tmp_path: Path):
    store = StateStore(tmp_path / "state.sqlite3")

    store.mark_final(
        "combine-two-tables",
        Verdict.UNSUPPORTED_LANGUAGE,
        submitted=False,
        message="cannot switch to Python3",
    )

    assert store.list_unfinished() == []


def test_discovered_problems_are_deduped_and_exported(tmp_path: Path):
    store = StateStore(tmp_path / "state.sqlite3")

    count = store.record_discovered(
        [
            ProblemSummary(slug="two-sum", url="https://leetcode.cn/problems/two-sum/", title="Two Sum"),
            ProblemSummary(slug="two-sum", url="https://leetcode.cn/problems/two-sum/", title="Two Sum"),
        ]
    )

    assert count == 2
    assert store.list_discovered() == ["two-sum"]
    exported = store.export_state()
    assert exported["discovered_problems"][0]["slug"] == "two-sum"


def test_sequence_progress_tracks_next_frontend_id(tmp_path: Path):
    store = StateStore(tmp_path / "state.sqlite3")

    assert store.get_sequence_next("default") == 1

    store.mark_sequence_progress(
        name="default",
        next_frontend_id=2,
        last_frontend_id=1,
        last_slug="two-sum",
        last_verdict=Verdict.ACCEPTED.value,
        last_message="accepted",
    )

    assert store.get_sequence_next("default") == 2
    assert store.list_sequence_progress()[0]["last_slug"] == "two-sum"
    exported = store.export_state()
    assert exported["sequence_progress"][0]["next_frontend_id"] == 2

    store.reset_sequence_progress("default", start=10)

    assert store.get_sequence_next("default") == 10
