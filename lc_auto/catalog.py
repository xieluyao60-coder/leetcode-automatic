from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .exceptions import LCAutoError


CATALOG_URL = "https://leetcode.cn/api/problems/all/"


@dataclass(frozen=True)
class CatalogProblem:
    frontend_id: int
    slug: str
    title: str
    paid_only: bool = False
    difficulty: str = ""


class ProblemCatalog:
    def __init__(self, problems: dict[int, CatalogProblem]):
        self.problems = problems

    @classmethod
    def fetch(cls, timeout_seconds: int = 30) -> "ProblemCatalog":
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(CATALOG_URL)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LCAutoError(f"获取力扣题库列表失败：{exc}") from exc
        return cls.from_api_payload(payload)

    @classmethod
    def from_api_payload(cls, payload: dict[str, Any]) -> "ProblemCatalog":
        problems: dict[int, CatalogProblem] = {}
        for item in payload.get("stat_status_pairs", []):
            stat = item.get("stat") or {}
            frontend_raw = str(stat.get("frontend_question_id") or "").strip()
            if not frontend_raw.isdigit():
                continue
            frontend_id = int(frontend_raw)
            if bool(stat.get("question__hide")):
                continue
            slug = str(stat.get("question__title_slug") or "").strip()
            if not slug:
                continue
            problems[frontend_id] = CatalogProblem(
                frontend_id=frontend_id,
                slug=slug,
                title=str(stat.get("question__title") or slug),
                paid_only=bool(item.get("paid_only")),
                difficulty=_difficulty_name(item.get("difficulty", {}).get("level")),
            )
        if not problems:
            raise LCAutoError("题库列表为空，无法按题号顺序运行。")
        return cls(problems)

    def get(self, frontend_id: int) -> CatalogProblem | None:
        return self.problems.get(frontend_id)


def _difficulty_name(level: object) -> str:
    return {1: "easy", 2: "medium", 3: "hard"}.get(level, "")
