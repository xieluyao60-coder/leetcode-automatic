from __future__ import annotations

import re
from textwrap import dedent
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import ModelConfig
from .exceptions import LLMError
from .models import JudgeResult, LLMResponse, ProblemSnapshot


FENCED_CODE_RE = re.compile(r"```(?:python|py)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def extract_code(text: str) -> str:
    match = FENCED_CODE_RE.search(text)
    code = match.group(1) if match else text
    return code.strip()


class LLMSolver:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.config.validate_for_runtime()

    def solve(self, problem: ProblemSnapshot) -> LLMResponse:
        if self.config.provider == "fake":
            return self._fake_solution(problem, repair=False)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an algorithm engineer. Return only complete Python3 code "
                    "that can be submitted to LeetCode. Do not include Markdown."
                ),
            },
            {
                "role": "user",
                "content": self._build_solve_prompt(problem),
            },
        ]
        raw = self._chat(messages)
        return LLMResponse(code=extract_code(raw), raw_text=raw)

    def repair(self, problem: ProblemSnapshot, previous_code: str, result: JudgeResult) -> LLMResponse:
        if self.config.provider == "fake":
            return self._fake_solution(problem, repair=True)
        messages = [
            {
                "role": "system",
                "content": (
                    "You fix LeetCode Python3 submissions. Return only complete corrected "
                    "Python3 code. Do not include Markdown or explanation."
                ),
            },
            {
                "role": "user",
                "content": self._build_repair_prompt(problem, previous_code, result),
            },
        ]
        raw = self._chat(messages)
        return LLMResponse(code=extract_code(raw), raw_text=raw)

    def _build_solve_prompt(self, problem: ProblemSnapshot) -> str:
        return dedent(
            f"""
            Solve this LeetCode CN problem in Python3.

            Slug: {problem.slug}
            Title: {problem.title}
            URL: {problem.url}

            Problem statement:
            {problem.statement}

            Existing code template, if any:
            ```python
            {problem.code_template}
            ```

            Requirements:
            - Return complete submit-ready Python3 code.
            - Preserve the expected LeetCode class/function signature when present.
            - Do not hardcode sample outputs.
            - Do not include Markdown.
            """
        ).strip()

    def _build_repair_prompt(self, problem: ProblemSnapshot, previous_code: str, result: JudgeResult) -> str:
        return dedent(
            f"""
            The previous Python3 LeetCode submission failed. Fix it.

            Slug: {problem.slug}
            Title: {problem.title}

            Problem statement:
            {problem.statement}

            Previous code:
            ```python
            {previous_code}
            ```

            Judge verdict: {result.verdict.value}
            Message:
            {result.message}

            Failing case:
            {result.failing_case}

            Actual:
            {result.actual}

            Expected:
            {result.expected}

            Raw judge text:
            {result.raw_text}

            Return only complete corrected Python3 code.
            """
        ).strip()

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, LLMError)),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _chat(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        with httpx.Client(timeout=self.config.timeout_seconds) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected model response shape: {data}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Model returned an empty response")
        return content

    def _fake_solution(self, problem: ProblemSnapshot, repair: bool) -> LLMResponse:
        code = dedent(
            """
            class Solution:
                def twoSum(self, nums, target):
                    seen = {}
                    for i, value in enumerate(nums):
                        need = target - value
                        if need in seen:
                            return [seen[need], i]
                        seen[value] = i
                    return []
            """
        ).strip()
        note = "fake repair response" if repair else "fake solve response"
        return LLMResponse(code=code, raw_text=code, notes=note)
