from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .exceptions import PageStructureError, SafetyStop
from .logging_utils import logger
from .models import JudgeResult, ProblemSnapshot, ProblemSummary, Verdict


SECURITY_MARKERS = ("验证码", "安全验证", "行为异常", "访问过于频繁", "captcha", "verify you are human")


class ProblemPage(Protocol):
    def open_problem(self, slug: str) -> None: ...

    def current_slug(self) -> str: ...

    def go_next_problem(self) -> str: ...

    def extract_problem(self, slug: str) -> ProblemSnapshot: ...

    def ensure_language(self, language: str) -> bool: ...

    def fill_code(self, code: str) -> None: ...

    def run_code(self) -> JudgeResult: ...

    def submit_code(self) -> JudgeResult: ...


@dataclass
class LeetCodePage:
    page: object
    judge_timeout_ms: int = 120000
    navigation_timeout_ms: int = 45000
    stop_on_security_challenge: bool = True

    def open_problem(self, slug: str) -> None:
        url = f"https://leetcode.cn/problems/{slug}/"
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
        except Exception as exc:
            raise PageStructureError(f"打开题目页面失败或超时：{url}") from exc
        self._wait_for_load_state_soft("networkidle")
        self.assert_no_security_challenge()
        self._wait_for_problem_shell()

    def current_slug(self) -> str:
        path = str(self.page.evaluate("() => location.pathname") or "")
        match = re.search(r"/problems/([^/?#]+)/?", path)
        if not match:
            raise PageStructureError("当前页面不是力扣题目页，无法读取题目 slug。")
        return match.group(1)

    def go_next_problem(self) -> str:
        old_slug = self.current_slug()
        clicked = self._click_next_problem_button()
        if not clicked:
            raise PageStructureError("未找到页面顶部的下一题按钮。")
        try:
            self.page.wait_for_function(
                """
                (oldSlug) => {
                  const match = location.pathname.match(/\\/problems\\/([^\\/?#]+)\\/?/);
                  return match && match[1] !== oldSlug;
                }
                """,
                old_slug,
                timeout=self.navigation_timeout_ms,
            )
        except Exception as exc:
            raise PageStructureError("点击下一题后页面没有切换到新题目。") from exc
        self._wait_for_load_state_soft("networkidle")
        self.assert_no_security_challenge()
        self._wait_for_problem_shell()
        return self.current_slug()

    def extract_problem(self, slug: str) -> ProblemSnapshot:
        self.assert_no_security_challenge()
        data = self.page.evaluate(
            """
            () => {
              const visibleText = (el) => {
                const style = window.getComputedStyle(el);
                if (style && (style.display === 'none' || style.visibility === 'hidden')) return '';
                return (el.innerText || '').trim();
              };

              const titleSelectors = [
                '[data-cy="question-title"]',
                'div[class*="text-title"]',
                'h1',
                'title'
              ];
              let title = '';
              for (const selector of titleSelectors) {
                const el = document.querySelector(selector);
                if (el) {
                  title = (el.innerText || el.textContent || '').trim();
                  if (title) break;
                }
              }
              if (!title) title = document.title.replace(/ - 力扣.*$/, '').trim();

              const directSelectors = [
                '[data-track-load="description_content"]',
                '[data-cy="question-content"]',
                'article'
              ];
              let statement = '';
              for (const selector of directSelectors) {
                const el = document.querySelector(selector);
                if (el) {
                  const text = visibleText(el);
                  if (text.length > 80) {
                    statement = text;
                    break;
                  }
                }
              }

              if (!statement) {
                const candidates = Array.from(document.querySelectorAll('main div, section, article'))
                  .map((el) => ({ text: visibleText(el), len: visibleText(el).length }))
                  .filter((item) => item.len > 120 && item.len < 50000)
                  .filter((item) => /示例|Example/.test(item.text) || /约束|提示|Constraints/.test(item.text))
                  .sort((a, b) => a.len - b.len);
                if (candidates.length) statement = candidates[0].text;
              }

              let codeTemplate = '';
              const models = window.monaco && window.monaco.editor ? window.monaco.editor.getModels() : [];
              if (models && models.length) {
                codeTemplate = models[0].getValue();
              }
              if (!codeTemplate) {
                const lines = Array.from(document.querySelectorAll('.monaco-editor .view-line'))
                  .map((line) => (line.innerText || '').replace(/\\u00a0/g, ' '))
                  .filter(Boolean);
                codeTemplate = lines.join('\\n');
              }

              return { title, statement, codeTemplate, url: location.href };
            }
            """
        )
        title = _clean_text(data.get("title", ""))
        statement = _clean_text(data.get("statement", ""))
        if not statement or len(statement) < 80:
            raise PageStructureError("未能稳定提取题面内容。")
        return ProblemSnapshot(
            slug=slug,
            url=str(data.get("url") or f"https://leetcode.cn/problems/{slug}/"),
            title=title or slug,
            statement=statement,
            code_template=str(data.get("codeTemplate") or "").strip(),
            language="python3",
        )

    def ensure_language(self, language: str) -> bool:
        self.assert_no_security_challenge()
        if language.lower() not in {"python", "python3"}:
            raise PageStructureError("当前版本只支持 Python3。")

        language_id = self.page.evaluate(
            """
            () => {
              const models = window.monaco && window.monaco.editor ? window.monaco.editor.getModels() : [];
              if (models && models.length && models[0].getLanguageId) return models[0].getLanguageId();
              return '';
            }
            """
        )
        if str(language_id).lower() in {"python", "python3"}:
            return True

        if "Python3" in self._body_text():
            return True

        patterns = (r"Python3|Python|C\+\+|Java|JavaScript", r"选择语言|语言|Language")
        last_error: Exception | None = None
        for pattern in patterns:
            try:
                candidate = self.page.get_by_role("button", name=re.compile(pattern, re.I)).last
                if candidate.count() > 0:
                    candidate.click(timeout=5000)
                    option = self.page.get_by_text(re.compile(r"^Python3$", re.I)).last
                    if option.count() > 0:
                        option.click(timeout=5000)
                        time.sleep(1)
                        return True
            except Exception as exc:
                last_error = exc

        if last_error:
            raise PageStructureError("无法确认或切换到 Python3 语言。") from last_error
        raise PageStructureError("无法确认或切换到 Python3 语言。")

    def fill_code(self, code: str) -> None:
        self.assert_no_security_challenge()
        changed = self.page.evaluate(
            """
            (code) => {
              if (window.monaco && window.monaco.editor) {
                const models = window.monaco.editor.getModels();
                if (models && models.length) {
                  models[0].setValue(code);
                  return true;
                }
              }
              return false;
            }
            """,
            code,
        )
        if changed:
            return

        editor = self.page.locator(".monaco-editor textarea").first
        if editor.count() == 0:
            raise PageStructureError("未找到 Monaco 编辑器。")
        editor.click()
        self.page.keyboard.press("Control+A")
        self.page.keyboard.insert_text(code)

    def run_code(self) -> JudgeResult:
        self._click_button(("运行", "Run"))
        return self._wait_for_judge_result(action="run")

    def submit_code(self) -> JudgeResult:
        self._click_button(("提交", "Submit"))
        return self._wait_for_judge_result(action="submit")

    def discover_problem_slugs(self, limit: int = 20, scroll_rounds: int = 12) -> list[ProblemSummary]:
        url = "https://leetcode.cn/problemset/algorithms/"
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=self.navigation_timeout_ms)
        except Exception as exc:
            raise PageStructureError(f"打开题库页面失败或超时：{url}") from exc
        self._wait_for_load_state_soft("networkidle")
        self.assert_no_security_challenge()

        collected: dict[str, ProblemSummary] = {}
        stale_rounds = 0
        for _ in range(scroll_rounds):
            before = len(collected)
            for item in self._extract_problem_links():
                if item.slug not in collected:
                    collected[item.slug] = item
                if len(collected) >= limit:
                    return list(collected.values())[:limit]
            if len(collected) == before:
                stale_rounds += 1
            else:
                stale_rounds = 0
            if stale_rounds >= 3:
                break
            self.page.mouse.wheel(0, 1800)
            time.sleep(0.8)
        return list(collected.values())[:limit]

    def save_screenshot(self, path: str | Path) -> None:
        self.page.screenshot(path=str(path), full_page=False, timeout=10000)

    def save_html(self, path: str | Path) -> None:
        Path(path).write_text(self.page.content(), encoding="utf-8")

    def assert_no_security_challenge(self) -> None:
        if not self.stop_on_security_challenge:
            return
        text = self._body_text()
        lower_text = text.lower()
        for marker in SECURITY_MARKERS:
            if marker.lower() in lower_text:
                raise SafetyStop(f"检测到安全/风控提示：{marker}")

    def _wait_for_problem_shell(self) -> None:
        deadline = time.monotonic() + self.navigation_timeout_ms / 1000
        while time.monotonic() < deadline:
            self.assert_no_security_challenge()
            text = self._body_text()
            if ("示例" in text or "Example" in text) and ("提交" in text or "Submit" in text):
                return
            time.sleep(0.5)
        raise PageStructureError("题目页面加载超时或结构无法识别。")

    def _wait_for_load_state_soft(self, state: str) -> None:
        timeout_ms = min(12000, max(3000, self.navigation_timeout_ms // 3))
        try:
            self.page.wait_for_load_state(state, timeout=timeout_ms)
        except Exception as exc:
            text = str(exc)
            if exc.__class__.__name__ == "TimeoutError" or "Timeout" in text:
                logger.debug("Ignoring {} wait timeout after {}ms", state, timeout_ms)
                return
            raise PageStructureError(f"等待页面状态失败：{state}") from exc

    def _click_button(self, names: tuple[str, ...]) -> None:
        self.assert_no_security_challenge()
        patterns = "|".join(re.escape(name) for name in names)
        candidates = [
            self.page.get_by_role("button", name=re.compile(patterns, re.I)).last,
            self.page.locator("button").filter(has_text=re.compile(patterns, re.I)).last,
            self.page.locator("[role=button]").filter(has_text=re.compile(patterns, re.I)).last,
        ]
        last_error: Exception | None = None
        for locator in candidates:
            try:
                if locator.count() > 0:
                    locator.click(timeout=5000)
                    return
            except Exception as exc:
                last_error = exc
        raise PageStructureError(f"未找到按钮：{names}") from last_error

    def _click_next_problem_button(self) -> bool:
        label_pattern = re.compile(r"下一题|下一个|Next", re.I)
        candidates = [
            self.page.get_by_label(label_pattern).first,
            self.page.get_by_role("button", name=label_pattern).first,
            self.page.locator("button").filter(has_text=label_pattern).first,
            self.page.locator("[role=button]").filter(has_text=label_pattern).first,
        ]
        for locator in candidates:
            try:
                if locator.count() > 0:
                    locator.click(timeout=5000)
                    return True
            except Exception:
                pass

        return bool(
            self.page.evaluate(
                """
                () => {
                  const textRe = /下一题|下一个|Next/i;
                  const clickable = Array.from(document.querySelectorAll('button,a,[role="button"]'));
                  const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                      style.visibility !== 'hidden' && style.display !== 'none';
                  };
                  const byLabel = clickable.find((el) => {
                    const label = [
                      el.getAttribute('aria-label'),
                      el.getAttribute('title'),
                      el.textContent
                    ].filter(Boolean).join(' ');
                    return visible(el) && textRe.test(label);
                  });
                  if (byLabel) {
                    byLabel.click();
                    return true;
                  }

                  const topButtons = clickable
                    .map((el) => ({ el, rect: el.getBoundingClientRect() }))
                    .filter((item) => visible(item.el) && item.rect.top >= 0 && item.rect.top < 90)
                    .sort((a, b) => a.rect.left - b.rect.left);
                  const previousIndex = topButtons.findIndex((item) => {
                    const label = [
                      item.el.getAttribute('aria-label'),
                      item.el.getAttribute('title'),
                      item.el.textContent
                    ].filter(Boolean).join(' ');
                    return /上一题|Previous/i.test(label);
                  });
                  if (previousIndex >= 0 && topButtons[previousIndex + 1]) {
                    topButtons[previousIndex + 1].el.click();
                    return true;
                  }
                  return false;
                }
                """
            )
        )

    def _wait_for_judge_result(self, action: str) -> JudgeResult:
        start = time.monotonic()
        last_text = ""
        while (time.monotonic() - start) * 1000 < self.judge_timeout_ms:
            self.assert_no_security_challenge()
            text = self._body_text()
            last_text = text
            result = parse_judge_text(text, action=action)
            if result.verdict != Verdict.UNKNOWN:
                return result
            time.sleep(1)
        return JudgeResult(
            verdict=Verdict.UNKNOWN,
            raw_text=last_text,
            message=f"{action} judge result timed out after {self.judge_timeout_ms}ms",
        )

    def _body_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=3000)
        except Exception:
            return ""

    def _extract_problem_links(self) -> list[ProblemSummary]:
        rows = self.page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href*="/problems/"]'))
              .map((a) => {
                const href = a.href || '';
                const match = href.match(/\\/problems\\/([^\\/?#]+)\\/?/);
                if (!match) return null;
                const row = a.closest('[role="row"], tr, li, div');
                const text = ((row && row.innerText) || a.innerText || '').trim();
                return {
                  slug: match[1],
                  url: new URL(`/problems/${match[1]}/`, location.origin).href,
                  title: (a.innerText || text.split('\\n')[0] || match[1]).trim(),
                  rowText: text
                };
              })
              .filter(Boolean)
            """
        )
        summaries: list[ProblemSummary] = []
        for row in rows:
            slug = str(row.get("slug", "")).strip()
            if not slug or slug in {"problemset", "tag"}:
                continue
            row_text = str(row.get("rowText", ""))
            summaries.append(
                ProblemSummary(
                    slug=slug,
                    url=str(row.get("url") or f"https://leetcode.cn/problems/{slug}/"),
                    title=_clean_text(str(row.get("title") or slug)),
                    difficulty=_detect_difficulty(row_text),
                    status_hint=_detect_status(row_text),
                    source="problemset",
                )
            )
        return summaries


def parse_judge_text(text: str, action: str = "run") -> JudgeResult:
    normalized = _clean_text(text)
    verdict = Verdict.UNKNOWN
    message = ""

    error_markers: list[tuple[Verdict, tuple[str, ...]]] = [
        (Verdict.WRONG_ANSWER, ("解答错误", "答案错误", "Wrong Answer")),
        (Verdict.COMPILE_ERROR, ("编译出错", "Compile Error", "SyntaxError")),
        (Verdict.RUNTIME_ERROR, ("执行出错", "Runtime Error", "TypeError", "ValueError", "NameError", "Exception:")),
        (Verdict.TIME_LIMIT, ("超出时间限制", "Time Limit Exceeded")),
        (Verdict.MEMORY_LIMIT, ("超出内存限制", "Memory Limit Exceeded")),
    ]
    for candidate, markers in error_markers:
        if any(marker in normalized for marker in markers):
            verdict = candidate
            message = next(marker for marker in markers if marker in normalized)
            break

    failing_case = _extract_labeled_block(normalized, ("输入", "Input"), ("输出", "Output", "预期结果", "Expected"))
    actual = _extract_labeled_block(normalized, ("输出", "Output"), ("预期结果", "Expected", "标准输出", "Stdout"))
    expected = _extract_labeled_block(normalized, ("预期结果", "Expected"), ("标准输出", "Stdout", "通过", "Accepted"))

    if verdict == Verdict.UNKNOWN and _has_accepted_result(normalized):
        verdict = Verdict.ACCEPTED
        message = "accepted"

    if verdict == Verdict.UNKNOWN and action == "run":
        running_markers = ("执行中", "运行中", "Pending", "Running")
        if not any(marker in normalized for marker in running_markers):
            concise = normalized[-2000:] if normalized else ""
            message = "judge result not found"
            return JudgeResult(verdict=Verdict.UNKNOWN, raw_text=concise, message=message)

    return JudgeResult(
        verdict=verdict,
        raw_text=normalized[-5000:],
        message=message,
        failing_case=failing_case,
        actual=actual,
        expected=expected,
    )


def _extract_labeled_block(text: str, labels: tuple[str, ...], stop_labels: tuple[str, ...]) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    stop_pattern = "|".join(re.escape(label) for label in stop_labels)
    match = re.search(rf"(?:{label_pattern})\s*[:：]?\s*(.*?)(?=(?:{stop_pattern})\s*[:：]?|$)", text, re.S)
    return match.group(1).strip()[:4000] if match else ""


def _clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.replace("\r\n", "\n")).strip()


def _has_accepted_result(text: str) -> bool:
    accepted_patterns = (
        r"执行结果\s*通过\b",
        r"测试结果[\s\S]{0,300}?通过[\s\S]{0,120}?执行用时",
        r"通过\s*执行用时\s*:",
        r"执行通过\b",
        r"通过\s*\d+\s*/\s*\d+\s*个?通过的测试用例",
        r"\bAccepted\b",
    )
    return any(re.search(pattern, text, re.I) for pattern in accepted_patterns)


def _detect_difficulty(text: str) -> str:
    if any(marker in text for marker in ("简单", "Easy")):
        return "easy"
    if any(marker in text for marker in ("中等", "Medium")):
        return "medium"
    if any(marker in text for marker in ("困难", "Hard")):
        return "hard"
    return ""


def _detect_status(text: str) -> str:
    if any(marker in text for marker in ("已解答", "已通过", "Solved", "Accepted")):
        return "solved"
    if any(marker in text for marker in ("尝试过", "Attempted")):
        return "attempted"
    return ""
