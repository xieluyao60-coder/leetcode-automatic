from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from urllib.error import URLError
from urllib.request import urlopen
from pathlib import Path

from .artifacts import ArtifactWriter
from .browser import BrowserSession
from .catalog import ProblemCatalog
from .config import AppConfig, load_config
from .exceptions import ConfigError, LCAutoError, LoginRequired
from .leetcode_page import LeetCodePage
from .llm import LLMSolver
from .logging_utils import logger
from .models import Verdict
from .runner import AutomationRunner, read_problem_file
from .state import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lc-auto", description="LeetCode CN automation tool")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--cdp-url", help="Connect to an existing Chrome via DevTools, e.g. http://127.0.0.1:9222")

    late_common = argparse.ArgumentParser(add_help=False)
    late_common.add_argument("--config", default=argparse.SUPPRESS, help="Path to config YAML")
    late_common.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS, help="Enable debug logging")
    late_common.add_argument(
        "--cdp-url",
        default=argparse.SUPPRESS,
        help="Connect to an existing Chrome via DevTools, e.g. http://127.0.0.1:9222",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", parents=[late_common], help="Create config.yaml and .env from examples")
    init.add_argument("--force", action="store_true", help="Overwrite existing local config files")

    subparsers.add_parser("doctor", parents=[late_common], help="Check local dependencies and configuration")

    subparsers.add_parser(
        "login",
        parents=[late_common],
        help="Open browser and wait for manual LeetCode CN login",
    )

    dry_run = subparsers.add_parser(
        "dry-run",
        parents=[late_common],
        help="Run one problem without submitting",
    )
    dry_run.add_argument("--problem", required=True, help="Problem slug, e.g. two-sum")

    run = subparsers.add_parser(
        "run",
        parents=[late_common],
        help="Run problems from a slug list",
    )
    run.add_argument("--problems", default="problems.txt", help="Path to problem slug list")
    run.add_argument("--problem", help="Run one problem slug")
    run.add_argument("--from-discovered", action="store_true", help="Run slugs saved by discover")
    run.add_argument("--current", action="store_true", help="Start from the current browser problem page")
    run.add_argument("--next-in-page", action="store_true", help="After submitted AC, click the page next-problem button")
    run.add_argument("--limit", type=int, help="Limit this command run, overriding config max_questions_per_run")

    run_seq = subparsers.add_parser(
        "run-seq",
        parents=[late_common],
        help="Run LeetCode problems by frontend id order: 1, 2, 3...",
    )
    run_seq.add_argument("--start", type=int, help="Start frontend problem id, e.g. 1")
    run_seq.add_argument("--limit", type=int, help="Limit this command run, overriding config max_questions_per_run")
    run_seq.add_argument("--progress-name", default="default", help="Named sequence progress slot")
    run_seq.add_argument("--reset-progress", action="store_true", help="Reset named progress to --start or 1")
    run_seq.add_argument("--rerun-accepted", action="store_true", help="Do not skip records previously marked accepted")

    discover = subparsers.add_parser(
        "discover",
        parents=[late_common],
        help="Collect visible problem slugs from the LeetCode CN problemset page",
    )
    discover.add_argument("--limit", type=int, default=20, help="Maximum slugs to collect")
    discover.add_argument("--output", default="problems.txt", help="Write discovered slugs to this file")
    discover.add_argument("--append", action="store_true", help="Append to output instead of replacing it")

    subparsers.add_parser(
        "resume",
        parents=[late_common],
        help="Resume unfinished problems from the state database",
    )

    status = subparsers.add_parser("status", parents=[late_common], help="Print recent problem run status")
    status.add_argument("--limit", type=int, default=20, help="Maximum rows to print")

    export = subparsers.add_parser("export", parents=[late_common], help="Export SQLite state to JSON")
    export.add_argument("--output", default="state_export.json", help="Output JSON path")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        if args.command == "init":
            return _cmd_init(force=args.force)
        if args.command == "doctor":
            return _cmd_doctor(args.config, cdp_url=args.cdp_url)

        config = load_config(args.config)
        _apply_cli_overrides(config, args)
        if args.command == "login":
            return _cmd_login(config)
        if args.command == "dry-run":
            return _cmd_dry_run(config, args.problem)
        if args.command == "run":
            if args.limit:
                config.max_questions_per_run = args.limit
            if args.current or args.next_in_page:
                return _cmd_run_page_chain(
                    config,
                    start_slug=None if args.current else args.problem,
                    allow_submit=config.allow_real_submit,
                )
            slugs = _resolve_run_slugs(config, args)
            return _cmd_run(config, slugs, allow_submit=config.allow_real_submit)
        if args.command == "run-seq":
            if args.limit:
                config.max_questions_per_run = args.limit
            if args.rerun_accepted:
                config.skip_accepted = False
            return _cmd_run_sequence(
                config,
                start=args.start,
                progress_name=args.progress_name,
                reset_progress=args.reset_progress,
                allow_submit=config.allow_real_submit,
            )
        if args.command == "discover":
            return _cmd_discover(config, limit=args.limit, output=args.output, append=args.append)
        if args.command == "resume":
            store = StateStore(config.state_db_path)
            slugs = store.list_unfinished()
            if not slugs:
                print("没有未完成题目。")
                return 0
            return _cmd_run(config, slugs, allow_submit=config.allow_real_submit)
        if args.command == "status":
            return _cmd_status(config, limit=args.limit)
        if args.command == "export":
            return _cmd_export(config, output=args.output)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except LCAutoError as exc:
        print(f"运行停止：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("已手动中断。", file=sys.stderr)
        return 130
    return 0


def _cmd_login(config: AppConfig) -> int:
    with BrowserSession(config) as browser:
        browser.wait_for_manual_login()
    return 0


def _cmd_dry_run(config: AppConfig, slug: str) -> int:
    return _cmd_run(config, [slug], allow_submit=False)


def _cmd_run(config: AppConfig, slugs: list[str], allow_submit: bool) -> int:
    if not slugs:
        print("没有可运行的题目 slug。")
        return 0
    if not allow_submit:
        logger.info("Real submit is disabled. The runner will stop after run-code passes.")
    config.model.validate_for_runtime()
    solver = LLMSolver(config.model)
    store = StateStore(config.state_db_path)
    artifacts = ArtifactWriter(
        config.artifact_dir,
        save_screenshots=config.save_screenshots,
        save_page_html=config.save_page_html,
    )
    with BrowserSession(config) as browser:
        browser.require_login()
        page = LeetCodePage(
            browser.page,
            judge_timeout_ms=config.judge_timeout_ms,
            navigation_timeout_ms=config.navigation_timeout_ms,
            stop_on_security_challenge=config.stop_on_security_challenge,
        )
        runner = AutomationRunner(config=config, page=page, solver=solver, store=store, artifacts=artifacts)
        results = runner.run_many(slugs, allow_submit=allow_submit)
    for result in results:
        print(
            f"{result.slug}: {result.verdict.value}, attempts={result.attempts}, "
            f"submitted={result.submitted}, message={result.message}"
        )
    return 0


def _cmd_run_sequence(
    config: AppConfig,
    start: int | None,
    progress_name: str,
    reset_progress: bool,
    allow_submit: bool,
) -> int:
    if not allow_submit:
        logger.info("Real submit is disabled. Sequence progress advances only after real submitted AC.")
    config.model.validate_for_runtime()
    store = StateStore(config.state_db_path)
    if reset_progress:
        store.reset_sequence_progress(progress_name, start=start or 1)
    frontend_id = start or store.get_sequence_next(progress_name, default=1)
    logger.info("Fetching LeetCode CN problem catalog")
    catalog = ProblemCatalog.fetch()

    solver = LLMSolver(config.model)
    artifacts = ArtifactWriter(
        config.artifact_dir,
        save_screenshots=config.save_screenshots,
        save_page_html=config.save_page_html,
    )
    results = []
    attempted_count = 0
    skipped_count = 0
    with BrowserSession(config) as browser:
        browser.require_login()
        page = LeetCodePage(
            browser.page,
            judge_timeout_ms=config.judge_timeout_ms,
            navigation_timeout_ms=config.navigation_timeout_ms,
            stop_on_security_challenge=config.stop_on_security_challenge,
        )
        runner = AutomationRunner(config=config, page=page, solver=solver, store=store, artifacts=artifacts)
        while attempted_count < config.max_questions_per_run:
            problem = catalog.get(frontend_id)
            if not problem:
                logger.info("Skipping missing frontend id: {}", frontend_id)
                store.mark_sequence_progress(
                    progress_name,
                    next_frontend_id=frontend_id + 1,
                    last_frontend_id=frontend_id,
                    last_verdict="missing",
                    last_message="not found in catalog",
                )
                frontend_id += 1
                skipped_count += 1
                _guard_sequence_skips(skipped_count)
                continue
            if problem.paid_only:
                logger.info("Skipping paid-only problem {}: {}", frontend_id, problem.slug)
                store.mark_sequence_progress(
                    progress_name,
                    next_frontend_id=frontend_id + 1,
                    last_frontend_id=frontend_id,
                    last_slug=problem.slug,
                    last_verdict="skipped",
                    last_message="paid-only problem",
                )
                frontend_id += 1
                skipped_count += 1
                _guard_sequence_skips(skipped_count)
                continue
            if config.skip_accepted and store.has_accepted(problem.slug):
                logger.info("Skipping already submitted accepted problem {}: {}", frontend_id, problem.slug)
                store.mark_sequence_progress(
                    progress_name,
                    next_frontend_id=frontend_id + 1,
                    last_frontend_id=frontend_id,
                    last_slug=problem.slug,
                    last_verdict="accepted",
                    last_message="already submitted accepted",
                )
                frontend_id += 1
                skipped_count += 1
                _guard_sequence_skips(skipped_count)
                continue

            logger.info("Sequence problem #{} -> {}", frontend_id, problem.slug)
            result = runner.run_problem(problem.slug, allow_submit=allow_submit)
            results.append(result)
            attempted_count += 1
            if result.verdict == Verdict.ACCEPTED and result.submitted:
                store.mark_sequence_progress(
                    progress_name,
                    next_frontend_id=frontend_id + 1,
                    last_frontend_id=frontend_id,
                    last_slug=problem.slug,
                    last_verdict=result.verdict.value,
                    last_message=result.message,
                )
                frontend_id += 1
            else:
                store.mark_sequence_progress(
                    progress_name,
                    next_frontend_id=frontend_id,
                    last_frontend_id=frontend_id,
                    last_slug=problem.slug,
                    last_verdict=result.verdict.value,
                    last_message=result.message,
                )
                break
            if attempted_count < config.max_questions_per_run:
                runner._delay_between_questions()

    for result in results:
        print(
            f"{result.slug}: {result.verdict.value}, attempts={result.attempts}, "
            f"submitted={result.submitted}, message={result.message}"
        )
    print(f"顺序进度：下次从第 {store.get_sequence_next(progress_name, default=1)} 题开始。")
    return 0


def _guard_sequence_skips(skipped_count: int) -> None:
    if skipped_count > 5000:
        raise LCAutoError("连续跳过过多题目，顺序运行已停止。")


def _cmd_run_page_chain(config: AppConfig, start_slug: str | None, allow_submit: bool) -> int:
    if not allow_submit:
        logger.info("Real submit is disabled. Page-next mode will stop after the first run-code pass.")
    config.model.validate_for_runtime()
    solver = LLMSolver(config.model)
    store = StateStore(config.state_db_path)
    artifacts = ArtifactWriter(
        config.artifact_dir,
        save_screenshots=config.save_screenshots,
        save_page_html=config.save_page_html,
    )
    with BrowserSession(config) as browser:
        browser.require_login()
        page = LeetCodePage(
            browser.page,
            judge_timeout_ms=config.judge_timeout_ms,
            navigation_timeout_ms=config.navigation_timeout_ms,
            stop_on_security_challenge=config.stop_on_security_challenge,
        )
        runner = AutomationRunner(config=config, page=page, solver=solver, store=store, artifacts=artifacts)
        results = runner.run_page_chain(start_slug=start_slug, allow_submit=allow_submit)
    for result in results:
        print(
            f"{result.slug}: {result.verdict.value}, attempts={result.attempts}, "
            f"submitted={result.submitted}, message={result.message}"
        )
    return 0


def _cmd_init(force: bool = False) -> int:
    copied = []
    for source, target in (
        ("config.example.yaml", "config.yaml"),
        (".env.example", ".env"),
        ("problems.txt", "problems.txt"),
    ):
        source_path = Path(source)
        target_path = Path(target)
        if not source_path.exists():
            continue
        if target_path.exists() and not force:
            continue
        if source_path.resolve() == target_path.resolve():
            continue
        shutil.copyfile(source_path, target_path)
        copied.append(str(target_path))
    if copied:
        print("已创建：" + ", ".join(copied))
    else:
        print("本地配置文件已存在，无需创建。")
    return 0


def _cmd_doctor(config_path: str, cdp_url: str | None = None) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python", sys.version_info >= (3, 10), sys.version.split()[0]))
    for module in ("yaml", "pydantic", "httpx", "dotenv", "tenacity"):
        checks.append((module, importlib.util.find_spec(module) is not None, "importable"))
    checks.append(("playwright", importlib.util.find_spec("playwright") is not None, "required for browser commands"))

    try:
        config = load_config(config_path)
        if cdp_url:
            config.browser_cdp_url = cdp_url
        checks.append(("config", True, str(config_path)))
        try:
            config.model.validate_for_runtime()
            model_detail = config.model.provider
            if config.model.provider == "fake":
                model_detail = "fake (.env model settings are ignored)"
            elif config.model.model:
                model_detail = f"{config.model.provider}:{config.model.model}"
            checks.append(("model", True, model_detail))
        except ConfigError as exc:
            checks.append(("model", False, str(exc)))
        profile_parent = Path(config.browser_profile_dir).parent
        checks.append(("browser_profile_parent", profile_parent.exists(), str(profile_parent)))
        if config.browser_cdp_url:
            ok, detail = _check_cdp_endpoint(config.browser_cdp_url)
            checks.append(("browser_cdp_url", ok, detail))
        state_parent = Path(config.state_db_path).parent
        checks.append(("state_db_parent", state_parent.exists(), str(state_parent)))
    except ConfigError as exc:
        checks.append(("config", False, str(exc)))

    failed = False
    for name, ok, detail in checks:
        mark = "OK" if ok else "FAIL"
        print(f"{mark:4} {name}: {detail}")
        failed = failed or not ok
    return 1 if failed else 0


def _apply_cli_overrides(config: AppConfig, args: argparse.Namespace) -> None:
    cdp_url = getattr(args, "cdp_url", None)
    if cdp_url:
        config.browser_cdp_url = cdp_url


def _check_cdp_endpoint(cdp_url: str) -> tuple[bool, str]:
    endpoint = cdp_url.rstrip("/") + "/json/version"
    try:
        with urlopen(endpoint, timeout=2) as response:
            if response.status == 200:
                return True, cdp_url
            return False, f"{endpoint} returned HTTP {response.status}"
    except (OSError, URLError) as exc:
        return False, f"{endpoint} unreachable: {exc}"


def _cmd_discover(config: AppConfig, limit: int, output: str, append: bool) -> int:
    store = StateStore(config.state_db_path)
    with BrowserSession(config) as browser:
        browser.require_login()
        page = LeetCodePage(
            browser.page,
            judge_timeout_ms=config.judge_timeout_ms,
            navigation_timeout_ms=config.navigation_timeout_ms,
            stop_on_security_challenge=config.stop_on_security_challenge,
        )
        problems = page.discover_problem_slugs(limit=limit, scroll_rounds=config.problemset_scroll_rounds)
    store.record_discovered(problems)

    discovered_slugs = [problem.slug for problem in problems]
    output_path = Path(output)
    if append and output_path.exists():
        existing = read_problem_file(str(output_path))
        slugs = _dedupe_for_cli([*existing, *discovered_slugs])
    else:
        slugs = _dedupe_for_cli(discovered_slugs)
    output_path.write_text("\n".join(slugs) + ("\n" if slugs else ""), encoding="utf-8")

    print(f"发现 {len(problems)} 个题目，已写入 {output_path}。")
    for problem in problems[:10]:
        title = f" - {problem.title}" if problem.title else ""
        print(f"{problem.slug}{title}")
    return 0


def _cmd_status(config: AppConfig, limit: int) -> int:
    store = StateStore(config.state_db_path)
    progress_rows = store.list_sequence_progress()
    if progress_rows:
        print("顺序进度：")
        for row in progress_rows:
            print(
                f"  {row['name']}: next=#{row['next_frontend_id']}, "
                f"last=#{row['last_frontend_id']} {row['last_slug']} "
                f"{row['last_verdict']}, updated={row['updated_at']}"
            )
    rows = store.list_problem_rows(limit=limit)
    if not rows:
        if not progress_rows:
            print("暂无运行记录。")
        return 0
    print("最近题目：")
    for row in rows:
        submitted = "submitted" if row["submitted"] else "not-submitted"
        print(
            f"{row['slug']}: {row['status']}, attempts={row['attempts']}, "
            f"{submitted}, updated={row['updated_at']}, message={row['last_message']}"
        )
    return 0


def _cmd_export(config: AppConfig, output: str) -> int:
    store = StateStore(config.state_db_path)
    output_path = Path(output)
    output_path.write_text(json.dumps(store.export_state(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出到 {output_path}。")
    return 0


def _resolve_run_slugs(config: AppConfig, args: argparse.Namespace) -> list[str]:
    if args.problem:
        return [args.problem]
    if args.from_discovered:
        store = StateStore(config.state_db_path)
        return store.list_discovered(limit=args.limit or config.max_questions_per_run, skip_accepted=config.skip_accepted)
    return read_problem_file(args.problems)


def _dedupe_for_cli(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        slug = value.strip()
        if not slug or slug.startswith("#") or slug in seen:
            continue
        seen.add(slug)
        result.append(slug)
    return result


def _setup_logging(verbose: bool) -> None:
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if verbose else "INFO", format="<level>{level}</level> {message}")


if __name__ == "__main__":
    raise SystemExit(main())
