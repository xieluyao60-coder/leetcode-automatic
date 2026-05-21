from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .models import JudgeResult, ProblemSnapshot, utc_now_iso


class ArtifactWriter:
    def __init__(self, root: str | Path, save_screenshots: bool = True, save_page_html: bool = False):
        self.root = Path(root)
        self.save_screenshots = save_screenshots
        self.save_page_html = save_page_html
        self.root.mkdir(parents=True, exist_ok=True)

    def problem_dir(self, slug: str) -> Path:
        path = self.root / safe_path_part(slug)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_problem(self, problem: ProblemSnapshot) -> None:
        directory = self.problem_dir(problem.slug)
        self.write_json(directory / "problem.json", problem)
        self.write_text(directory / "statement.txt", problem.statement)
        if problem.code_template:
            self.write_text(directory / "initial_template.py", problem.code_template)

    def save_attempt(
        self,
        slug: str,
        attempt_index: int,
        phase: str,
        code: str,
        result: JudgeResult,
        llm_raw: str = "",
    ) -> None:
        directory = self.problem_dir(slug)
        stem = f"attempt_{attempt_index:03d}_{safe_path_part(phase)}"
        self.write_text(directory / f"{stem}.py", code)
        self.write_json(directory / f"{stem}_result.json", result)
        if llm_raw:
            self.write_text(directory / f"{stem}_llm.txt", llm_raw)

    def save_final(self, slug: str, payload: dict[str, Any]) -> None:
        directory = self.problem_dir(slug)
        data = {"finished_at": utc_now_iso(), **payload}
        self.write_json(directory / "final.json", data)

    def save_page_artifacts(self, slug: str, page: object, label: str) -> None:
        directory = self.problem_dir(slug)
        safe_label = safe_path_part(label)
        if self.save_screenshots and hasattr(page, "save_screenshot"):
            page.save_screenshot(directory / f"{safe_label}.png")
        if self.save_page_html and hasattr(page, "save_html"):
            page.save_html(directory / f"{safe_label}.html")

    @staticmethod
    def write_text(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def safe_path_part(value: str) -> str:
    value = value.strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)[:120]


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Path):
        return str(value)
    return value
