from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Verdict(str, Enum):
    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    COMPILE_ERROR = "compile_error"
    RUNTIME_ERROR = "runtime_error"
    TIME_LIMIT = "time_limit"
    MEMORY_LIMIT = "memory_limit"
    SECURITY_STOP = "security_stop"
    LOGIN_REQUIRED = "login_required"
    PAGE_ERROR = "page_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProblemSnapshot:
    slug: str
    url: str
    title: str
    statement: str
    code_template: str = ""
    language: str = "python3"


@dataclass(frozen=True)
class ProblemSummary:
    slug: str
    url: str
    title: str = ""
    difficulty: str = ""
    status_hint: str = ""
    source: str = "problemset"


@dataclass(frozen=True)
class JudgeResult:
    verdict: Verdict
    raw_text: str
    message: str = ""
    failing_case: str = ""
    expected: str = ""
    actual: str = ""

    @property
    def is_success(self) -> bool:
        return self.verdict == Verdict.ACCEPTED


@dataclass(frozen=True)
class LLMResponse:
    code: str
    raw_text: str
    notes: str = ""


@dataclass(frozen=True)
class AttemptRecord:
    slug: str
    attempt_index: int
    phase: str
    code: str
    verdict: Verdict
    message: str = ""
    failing_case: str = ""
    raw_result: str = ""
    llm_raw: str = ""
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "attempt_index": self.attempt_index,
            "phase": self.phase,
            "code": self.code,
            "verdict": self.verdict.value,
            "message": self.message,
            "failing_case": self.failing_case,
            "raw_result": self.raw_result,
            "llm_raw": self.llm_raw,
            "created_at": self.created_at or utc_now_iso(),
        }


@dataclass(frozen=True)
class ProblemRunResult:
    slug: str
    verdict: Verdict
    attempts: int
    submitted: bool
    message: str = ""
