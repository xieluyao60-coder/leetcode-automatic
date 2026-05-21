from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .artifacts import to_jsonable
from .models import AttemptRecord, ProblemSnapshot, ProblemSummary, Verdict, utc_now_iso


class StateStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if self.db_path.parent and str(self.db_path.parent) != ".":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS problems (
                    slug TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    language TEXT NOT NULL,
                    statement TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    submitted INTEGER NOT NULL DEFAULT 0,
                    last_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL,
                    phase TEXT NOT NULL,
                    code TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    failing_case TEXT NOT NULL DEFAULT '',
                    raw_result TEXT NOT NULL DEFAULT '',
                    llm_raw TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(slug) REFERENCES problems(slug)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_attempts_slug ON attempts(slug)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovered_problems (
                    slug TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    difficulty TEXT NOT NULL DEFAULT '',
                    status_hint TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sequence_progress (
                    name TEXT PRIMARY KEY,
                    next_frontend_id INTEGER NOT NULL,
                    last_frontend_id INTEGER,
                    last_slug TEXT NOT NULL DEFAULT '',
                    last_verdict TEXT NOT NULL DEFAULT '',
                    last_message TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert_problem(self, problem: ProblemSnapshot, status: Verdict = Verdict.UNKNOWN) -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO problems (
                    slug, url, title, language, statement, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    url=excluded.url,
                    title=excluded.title,
                    language=excluded.language,
                    statement=excluded.statement,
                    updated_at=excluded.updated_at
                """,
                (
                    problem.slug,
                    problem.url,
                    problem.title,
                    problem.language,
                    problem.statement,
                    status.value,
                    now,
                    now,
                ),
            )

    def record_attempt(self, record: AttemptRecord) -> None:
        payload = record.as_dict()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO attempts (
                    slug, attempt_index, phase, code, verdict, message,
                    failing_case, raw_result, llm_raw, created_at
                )
                VALUES (
                    :slug, :attempt_index, :phase, :code, :verdict, :message,
                    :failing_case, :raw_result, :llm_raw, :created_at
                )
                """,
                payload,
            )
            conn.execute(
                """
                UPDATE problems
                SET attempts = MAX(attempts, ?),
                    status = ?,
                    last_message = ?,
                    updated_at = ?
                WHERE slug = ?
                """,
                (
                    record.attempt_index,
                    record.verdict.value,
                    record.message,
                    payload["created_at"],
                    record.slug,
                ),
            )

    def mark_final(self, slug: str, verdict: Verdict, submitted: bool, message: str = "") -> None:
        now = utc_now_iso()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE problems
                SET status = ?, submitted = ?, last_message = ?, updated_at = ?
                WHERE slug = ?
                """,
                (verdict.value, int(submitted), message, now, slug),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO problems (
                        slug, url, title, language, statement, status, attempts,
                        submitted, last_message, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                    """,
                    (
                        slug,
                        f"https://leetcode.cn/problems/{slug}/",
                        slug,
                        "python3",
                        "",
                        verdict.value,
                        int(submitted),
                        message,
                        now,
                        now,
                    ),
                )

    def get_problem_status(self, slug: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM problems WHERE slug = ?", (slug,)).fetchone()
        return str(row["status"]) if row else None

    def has_accepted(self, slug: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, submitted FROM problems WHERE slug = ?",
                (slug,),
            ).fetchone()
        if not row:
            return False
        return str(row["status"]) == Verdict.ACCEPTED.value and int(row["submitted"]) == 1

    def list_unfinished(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT slug
                FROM problems
                WHERE NOT (
                    (status = ? AND submitted = 1)
                    OR status IN (?, ?)
                )
                ORDER BY updated_at ASC
                """,
                (Verdict.ACCEPTED.value, Verdict.SECURITY_STOP.value, Verdict.LOGIN_REQUIRED.value),
            ).fetchall()
        return [str(row["slug"]) for row in rows]

    def iter_attempts(self, slug: str) -> Iterable[sqlite3.Row]:
        with self._connect() as conn:
            yield from conn.execute(
                "SELECT * FROM attempts WHERE slug = ? ORDER BY attempt_index ASC, id ASC",
                (slug,),
            ).fetchall()

    def record_discovered(self, problems: Iterable[ProblemSummary]) -> int:
        now = utc_now_iso()
        count = 0
        with self._connect() as conn:
            for problem in problems:
                conn.execute(
                    """
                    INSERT INTO discovered_problems (
                        slug, url, title, difficulty, status_hint, source, first_seen_at, last_seen_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(slug) DO UPDATE SET
                        url=excluded.url,
                        title=excluded.title,
                        difficulty=excluded.difficulty,
                        status_hint=excluded.status_hint,
                        source=excluded.source,
                        last_seen_at=excluded.last_seen_at
                    """,
                    (
                        problem.slug,
                        problem.url,
                        problem.title,
                        problem.difficulty,
                        problem.status_hint,
                        problem.source,
                        now,
                        now,
                    ),
                )
                count += 1
        return count

    def list_discovered(self, limit: int | None = None, skip_accepted: bool = True) -> list[str]:
        query = """
            SELECT d.slug
            FROM discovered_problems d
            LEFT JOIN problems p ON p.slug = d.slug
        """
        params: list[object] = []
        if skip_accepted:
            query += " WHERE NOT (COALESCE(p.status, '') = ? AND COALESCE(p.submitted, 0) = 1)"
            params.append(Verdict.ACCEPTED.value)
        query += " ORDER BY d.last_seen_at DESC, d.slug ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [str(row["slug"]) for row in rows]

    def list_problem_rows(self, limit: int = 50) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT slug, title, status, attempts, submitted, last_message, updated_at
                FROM problems
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sequence_progress(self) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name, next_frontend_id, last_frontend_id, last_slug,
                       last_verdict, last_message, updated_at
                FROM sequence_progress
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def export_state(self) -> dict[str, object]:
        with self._connect() as conn:
            problems = [dict(row) for row in conn.execute("SELECT * FROM problems ORDER BY updated_at DESC")]
            attempts = [dict(row) for row in conn.execute("SELECT * FROM attempts ORDER BY id ASC")]
            discovered = [
                dict(row)
                for row in conn.execute("SELECT * FROM discovered_problems ORDER BY last_seen_at DESC")
            ]
            sequence_progress = [
                dict(row)
                for row in conn.execute("SELECT * FROM sequence_progress ORDER BY updated_at DESC")
            ]
        return to_jsonable(
            {
                "problems": problems,
                "attempts": attempts,
                "discovered_problems": discovered,
                "sequence_progress": sequence_progress,
            }
        )

    def get_sequence_next(self, name: str = "default", default: int = 1) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT next_frontend_id FROM sequence_progress WHERE name = ?",
                (name,),
            ).fetchone()
        return int(row["next_frontend_id"]) if row else default

    def mark_sequence_progress(
        self,
        name: str,
        next_frontend_id: int,
        last_frontend_id: int | None = None,
        last_slug: str = "",
        last_verdict: str = "",
        last_message: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sequence_progress (
                    name, next_frontend_id, last_frontend_id, last_slug,
                    last_verdict, last_message, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    next_frontend_id=excluded.next_frontend_id,
                    last_frontend_id=excluded.last_frontend_id,
                    last_slug=excluded.last_slug,
                    last_verdict=excluded.last_verdict,
                    last_message=excluded.last_message,
                    updated_at=excluded.updated_at
                """,
                (
                    name,
                    next_frontend_id,
                    last_frontend_id,
                    last_slug,
                    last_verdict,
                    last_message,
                    utc_now_iso(),
                ),
            )

    def reset_sequence_progress(self, name: str = "default", start: int = 1) -> None:
        self.mark_sequence_progress(name=name, next_frontend_id=start, last_message="reset")
