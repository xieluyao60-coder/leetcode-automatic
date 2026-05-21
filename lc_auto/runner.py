from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Iterable

from .artifacts import ArtifactWriter
from .config import AppConfig
from .exceptions import LCAutoError, LoginRequired, SafetyStop
from .llm import LLMSolver
from .logging_utils import logger
from .models import AttemptRecord, JudgeResult, ProblemRunResult, Verdict
from .state import StateStore


@dataclass
class AutomationRunner:
    config: AppConfig
    page: object
    solver: LLMSolver
    store: StateStore
    artifacts: ArtifactWriter | None = None

    def run_many(self, slugs: Iterable[str], allow_submit: bool | None = None) -> list[ProblemRunResult]:
        results: list[ProblemRunResult] = []
        candidates = _dedupe_slugs(slugs)
        attempted_count = 0
        for index, slug in enumerate(candidates, start=1):
            if self.config.skip_accepted and self.store.has_accepted(slug):
                logger.info("Skipping already accepted problem: {}", slug)
                continue
            if attempted_count >= self.config.max_questions_per_run:
                break
            try:
                result = self.run_problem(slug, allow_submit=allow_submit)
                results.append(result)
            except (LoginRequired, SafetyStop):
                raise
            except LCAutoError as exc:
                if not self.config.continue_on_problem_error:
                    raise
                logger.error("Problem {} failed and will be skipped: {}", slug, exc)
                results.append(
                    ProblemRunResult(
                        slug=slug,
                        verdict=Verdict.PAGE_ERROR,
                        attempts=0,
                        submitted=False,
                        message=str(exc),
                    )
                )
            attempted_count += 1
            if attempted_count < self.config.max_questions_per_run and index < len(candidates):
                self._delay_between_questions()
        return results

    def run_page_chain(
        self,
        start_slug: str | None = None,
        allow_submit: bool | None = None,
    ) -> list[ProblemRunResult]:
        submit_enabled = self.config.allow_real_submit if allow_submit is None else allow_submit
        if start_slug:
            logger.info("Opening problem: {}", start_slug)
            self.page.open_problem(start_slug)
        elif not hasattr(self.page, "current_slug"):
            raise LCAutoError("Page object does not support current_slug().")

        results: list[ProblemRunResult] = []
        attempted_count = 0
        while attempted_count < self.config.max_questions_per_run:
            slug = self.page.current_slug()
            if self.config.skip_accepted and self.store.has_accepted(slug):
                logger.info("Skipping already submitted accepted problem: {}", slug)
            else:
                result = self.run_current_problem(slug, allow_submit=allow_submit)
                results.append(result)
                attempted_count += 1
                if not (submit_enabled and result.submitted and result.verdict == Verdict.ACCEPTED):
                    break

            if attempted_count >= self.config.max_questions_per_run:
                break
            if not submit_enabled:
                logger.info("Real submit is disabled; page-next mode stops after dry-run.")
                break
            logger.info("Clicking next problem from page")
            self.page.go_next_problem()
            self._delay_between_questions()
        return results

    def run_problem(self, slug: str, allow_submit: bool | None = None) -> ProblemRunResult:
        logger.info("Opening problem: {}", slug)
        self.page.open_problem(slug)
        return self.run_current_problem(slug, allow_submit=allow_submit)

    def run_current_problem(self, slug: str | None = None, allow_submit: bool | None = None) -> ProblemRunResult:
        submit_enabled = self.config.allow_real_submit if allow_submit is None else allow_submit
        submitted = False
        attempt_index = 0
        current_slug = slug or self.page.current_slug()
        try:
            if hasattr(self.page, "ensure_language"):
                self.page.ensure_language(self.config.language)
            problem = self.page.extract_problem(current_slug)
            self.store.upsert_problem(problem)
            if self.artifacts:
                self.artifacts.save_problem(problem)
                self.artifacts.save_page_artifacts(current_slug, self.page, "opened")

            llm_response = self.solver.solve(problem)
            code = llm_response.code
            llm_raw = llm_response.raw_text

            for attempt_index in range(1, self.config.max_repairs_per_problem + 2):
                self.page.fill_code(code)
                if self.config.run_before_submit:
                    logger.info("Running {} check {}", current_slug, attempt_index)
                    run_result = self.page.run_code()
                    self.store.record_attempt(
                        AttemptRecord(
                            slug=current_slug,
                            attempt_index=attempt_index,
                            phase="run",
                            code=code,
                            verdict=run_result.verdict,
                            message=run_result.message,
                            failing_case=run_result.failing_case,
                            raw_result=run_result.raw_text,
                            llm_raw=llm_raw,
                        )
                    )
                    if self.artifacts:
                        self.artifacts.save_attempt(current_slug, attempt_index, "run", code, run_result, llm_raw)
                        if not run_result.is_success:
                            self.artifacts.save_page_artifacts(
                                current_slug,
                                self.page,
                                f"attempt_{attempt_index:03d}_run_failed",
                            )

                    if not run_result.is_success:
                        if attempt_index > self.config.max_repairs_per_problem:
                            return self._finish(
                                current_slug,
                                run_result.verdict,
                                submitted,
                                attempt_index,
                                run_result.message,
                            )
                        repair = self.solver.repair(problem, code, run_result)
                        code = repair.code
                        llm_raw = repair.raw_text
                        continue

                    if not submit_enabled:
                        return self._finish(
                            current_slug,
                            Verdict.ACCEPTED,
                            submitted=False,
                            attempts=attempt_index,
                            message="dry-run passed; real submit disabled",
                        )

                if not submit_enabled:
                    return self._finish(
                        current_slug,
                        Verdict.UNKNOWN,
                        submitted=False,
                        attempts=attempt_index,
                        message="real submit disabled; code filled without running",
                    )

                logger.info("Submitting {} try {}", current_slug, attempt_index)
                submit_result = self.page.submit_code()
                submitted = True
                self.store.record_attempt(
                    AttemptRecord(
                        slug=current_slug,
                        attempt_index=attempt_index,
                        phase="submit",
                        code=code,
                        verdict=submit_result.verdict,
                        message=submit_result.message,
                        failing_case=submit_result.failing_case,
                        raw_result=submit_result.raw_text,
                        llm_raw=llm_raw,
                    )
                )
                if self.artifacts:
                    self.artifacts.save_attempt(current_slug, attempt_index, "submit", code, submit_result, llm_raw)
                    if not submit_result.is_success:
                        self.artifacts.save_page_artifacts(
                            current_slug,
                            self.page,
                            f"attempt_{attempt_index:03d}_submit_failed",
                        )
                if submit_result.is_success:
                    return self._finish(current_slug, Verdict.ACCEPTED, submitted, attempt_index, "accepted")
                if attempt_index > self.config.max_repairs_per_problem:
                    return self._finish(
                        current_slug,
                        submit_result.verdict,
                        submitted,
                        attempt_index,
                        submit_result.message,
                    )
                repair = self.solver.repair(problem, code, submit_result)
                code = repair.code
                llm_raw = repair.raw_text

            return self._finish(current_slug, Verdict.UNKNOWN, submitted, attempt_index, "unexpected loop exit")
        except LoginRequired as exc:
            self.store.mark_final(current_slug, Verdict.LOGIN_REQUIRED, submitted=False, message=str(exc))
            raise
        except SafetyStop as exc:
            self.store.mark_final(current_slug, Verdict.SECURITY_STOP, submitted=False, message=str(exc))
            raise
        except LCAutoError as exc:
            self.store.mark_final(current_slug, Verdict.PAGE_ERROR, submitted=False, message=str(exc))
            raise

    def _finish(
        self,
        slug: str,
        verdict: Verdict,
        submitted: bool,
        attempts: int,
        message: str = "",
    ) -> ProblemRunResult:
        self.store.mark_final(slug, verdict, submitted=submitted, message=message)
        if self.artifacts:
            self.artifacts.save_final(
                slug,
                {
                    "slug": slug,
                    "verdict": verdict.value,
                    "submitted": submitted,
                    "attempts": attempts,
                    "message": message,
                },
            )
        logger.info("Finished {}: {} ({})", slug, verdict.value, message)
        return ProblemRunResult(slug=slug, verdict=verdict, attempts=attempts, submitted=submitted, message=message)

    def _delay_between_questions(self) -> None:
        if self.config.max_delay_seconds <= 0:
            return
        delay = random.randint(self.config.min_delay_seconds, self.config.max_delay_seconds)
        logger.info("Waiting {}s before next problem", delay)
        time.sleep(delay)


def _dedupe_slugs(slugs: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in slugs:
        slug = raw.strip()
        if not slug or slug.startswith("#") or slug in seen:
            continue
        seen.add(slug)
        result.append(slug)
    return result


def read_problem_file(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return _dedupe_slugs(f.readlines())
