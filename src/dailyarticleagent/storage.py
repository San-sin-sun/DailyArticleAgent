from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

from .models import (
    ClassifiedPaper,
    Digest,
    FeedbackRating,
    Paper,
    PaperFeedback,
    PaperInsight,
    PaperStatus,
    RunAction,
    RunStatus,
    WatchProfile,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    uid TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors_json TEXT NOT NULL,
    abstract TEXT NOT NULL,
    source TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    url TEXT NOT NULL,
    doi TEXT,
    journal TEXT,
    raw_id TEXT
);

CREATE TABLE IF NOT EXISTS classifications (
    paper_uid TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    relevance_score INTEGER NOT NULL,
    novelty_score INTEGER NOT NULL,
    evidence_score INTEGER NOT NULL,
    total_score INTEGER NOT NULL,
    reasons_json TEXT NOT NULL,
    labels_json TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (paper_uid, profile_id),
    FOREIGN KEY (paper_uid) REFERENCES papers(uid)
);

CREATE TABLE IF NOT EXISTS digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL,
    period TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    markdown_path TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    UNIQUE (markdown_path)
);

CREATE TABLE IF NOT EXISTS paper_insights (
    paper_uid TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    chinese_summary TEXT NOT NULL,
    content_analysis TEXT NOT NULL,
    critique TEXT NOT NULL,
    follow_up TEXT NOT NULL,
    evidence_scope TEXT NOT NULL,
    reading_path TEXT,
    source_path TEXT,
    confidence TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (paper_uid, profile_id),
    FOREIGN KEY (paper_uid) REFERENCES papers(uid)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 1,
    parent_run_id INTEGER,
    options_json TEXT NOT NULL DEFAULT '{}',
    result_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (parent_run_id) REFERENCES agent_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_status
ON agent_runs(status, started_at);

CREATE TABLE IF NOT EXISTS paper_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_uid TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    rating TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (paper_uid) REFERENCES papers(uid)
);

CREATE INDEX IF NOT EXISTS idx_paper_feedback_profile
ON paper_feedback(profile_id, paper_uid);
"""


class Repository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        self.conn.execute(
            """
            DROP INDEX IF EXISTS idx_digests_unique_run
            """
        )
        self.conn.execute(
            """
            DROP INDEX IF EXISTS idx_digests_unique_period
            """
        )
        self.conn.execute(
            """
            UPDATE digests
            SET markdown_path = replace(markdown_path, '\\', '/')
            """
        )
        self.conn.execute(
            """
            DELETE FROM digests
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM digests
                GROUP BY markdown_path
            )
            """
        )
        self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_digests_unique_period
            ON digests(markdown_path)
            """
        )

    def save_papers(self, papers: Iterable[Paper]) -> None:
        self.conn.executemany(
            """
            INSERT INTO papers (
                uid, title, authors_json, abstract, source, source_kind, published_at,
                discovered_at, url, doi, journal, raw_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET
                title = excluded.title,
                authors_json = excluded.authors_json,
                abstract = excluded.abstract,
                source = excluded.source,
                source_kind = excluded.source_kind,
                published_at = excluded.published_at,
                url = excluded.url,
                doi = excluded.doi,
                journal = excluded.journal,
                raw_id = excluded.raw_id
            """,
            [
                (
                    paper.uid,
                    paper.title,
                    json.dumps(list(paper.authors), ensure_ascii=False),
                    paper.abstract,
                    paper.source,
                    paper.source_kind,
                    _date(paper.published_at),
                    paper.discovered_at.isoformat(),
                    paper.url,
                    paper.doi,
                    paper.journal,
                    paper.raw_id,
                )
                for paper in papers
            ],
        )
        self.conn.commit()

    def seen_profile_uids(self, profile_id: str, uids: Iterable[str]) -> set[str]:
        uid_list = list(uids)
        if not uid_list:
            return set()
        placeholders = ",".join("?" for _ in uid_list)
        rows = self.conn.execute(
            f"""
            SELECT paper_uid
            FROM classifications
            WHERE profile_id = ? AND paper_uid IN ({placeholders})
            """,
            [profile_id, *uid_list],
        ).fetchall()
        return {row["paper_uid"] for row in rows}

    def save_classifications(self, papers: Iterable[ClassifiedPaper]) -> None:
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO classifications (
                paper_uid, profile_id, relevance_score, novelty_score, evidence_score,
                total_score, reasons_json, labels_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.paper.uid,
                    item.profile_id,
                    item.relevance_score,
                    item.novelty_score,
                    item.evidence_score,
                    item.total_score,
                    json.dumps(list(item.reasons), ensure_ascii=False),
                    json.dumps(list(item.labels), ensure_ascii=False),
                    item.status.value,
                )
                for item in papers
            ],
        )
        self.conn.commit()

    def save_digest(self, digest: Digest) -> None:
        self.conn.execute(
            """
            INSERT INTO digests (
                profile_id, period, start_date, end_date, generated_at,
                markdown_path, title, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(markdown_path)
            DO UPDATE SET
                start_date = excluded.start_date,
                generated_at = excluded.generated_at,
                title = excluded.title,
                summary = excluded.summary
            """,
            (
                digest.profile.id,
                digest.period.value,
                digest.start_date.isoformat(),
                digest.end_date.isoformat(),
                digest.generated_at.isoformat(),
                _path_key(digest.markdown_path),
                digest.title,
                digest.summary,
            ),
        )
        self.save_paper_insights(digest.paper_insights)
        self.conn.commit()

    def start_run(
        self,
        action: RunAction,
        profile_id: str,
        options: dict | None = None,
        parent_run_id: int | None = None,
        attempts: int = 1,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO agent_runs (
                action, profile_id, status, started_at, attempts,
                parent_run_id, options_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.value,
                profile_id,
                RunStatus.RUNNING.value,
                datetime.now(UTC).isoformat(),
                attempts,
                parent_run_id,
                json.dumps(options or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        status: RunStatus,
        result_count: int = 0,
        error: str = "",
    ) -> None:
        self.conn.execute(
            """
            UPDATE agent_runs
            SET status = ?, finished_at = ?, result_count = ?, error = ?
            WHERE id = ?
            """,
            (
                status.value,
                datetime.now(UTC).isoformat(),
                result_count,
                error[:4000],
                run_id,
            ),
        )
        self.conn.commit()

    def list_runs(
        self,
        status: RunStatus | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = """
            SELECT id, action, profile_id, status, started_at, finished_at,
                   attempts, parent_run_id, options_json, result_count, error
            FROM agent_runs
        """
        params: list[object] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [_run_row(row) for row in rows]

    def get_run(self, run_id: int) -> dict | None:
        row = self.conn.execute(
            """
            SELECT id, action, profile_id, status, started_at, finished_at,
                   attempts, parent_run_id, options_json, result_count, error
            FROM agent_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        return _run_row(row) if row else None

    def save_paper_insights(self, insights: Iterable[PaperInsight]) -> None:
        self.conn.executemany(
            """
            INSERT INTO paper_insights (
                paper_uid, profile_id, chinese_summary, content_analysis, critique,
                follow_up, evidence_scope, reading_path, source_path, confidence, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_uid, profile_id)
            DO UPDATE SET
                chinese_summary = excluded.chinese_summary,
                content_analysis = excluded.content_analysis,
                critique = excluded.critique,
                follow_up = excluded.follow_up,
                evidence_scope = excluded.evidence_scope,
                reading_path = excluded.reading_path,
                source_path = excluded.source_path,
                confidence = excluded.confidence,
                updated_at = excluded.updated_at
            """,
            [
                (
                    insight.paper_uid,
                    insight.profile_id,
                    insight.chinese_summary,
                    insight.content_analysis,
                    insight.critique,
                    insight.follow_up,
                    insight.evidence_scope,
                    insight.reading_path,
                    insight.source_path,
                    insight.confidence,
                    datetime.now(UTC).isoformat(),
                )
                for insight in insights
            ],
        )
        self.conn.commit()

    def list_digests(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT id, profile_id, period, start_date, end_date, generated_at,
                   markdown_path, title, summary
            FROM digests
            ORDER BY generated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def paper_insights_for_profile(self, profile_id: str, paper_uids: Iterable[str]) -> list[PaperInsight]:
        uid_list = list(paper_uids)
        if not uid_list:
            return []
        placeholders = ",".join("?" for _ in uid_list)
        rows = self.conn.execute(
            f"""
            SELECT paper_uid, profile_id, chinese_summary, content_analysis,
                   critique, follow_up, evidence_scope, reading_path,
                   source_path, confidence
            FROM paper_insights
            WHERE profile_id = ? AND paper_uid IN ({placeholders})
            """,
            [profile_id, *uid_list],
        ).fetchall()
        return [_insight_row(row) for row in rows]

    def list_papers(self, profile_id: str | None = None, limit: int = 200) -> list[dict]:
        sql = """
        SELECT p.*, c.profile_id, c.total_score, c.labels_json, c.reasons_json,
               i.chinese_summary, i.content_analysis, i.critique,
               i.follow_up, i.evidence_scope, i.reading_path,
               i.source_path, i.confidence,
               (
                   SELECT pf.rating
                   FROM paper_feedback pf
                   WHERE pf.paper_uid = p.uid AND pf.profile_id = c.profile_id
                   ORDER BY pf.created_at DESC
                   LIMIT 1
               ) AS feedback_rating
        FROM papers p
        LEFT JOIN classifications c ON c.paper_uid = p.uid
        LEFT JOIN paper_insights i ON i.paper_uid = p.uid AND i.profile_id = c.profile_id
        WHERE c.status IS NULL OR c.status = ?
        """
        params: list[object] = [PaperStatus.SELECTED.value]
        if profile_id:
            sql += " AND c.profile_id = ?"
            params.append(profile_id)
        sql += " ORDER BY COALESCE(p.published_at, p.discovered_at) DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [_paper_row(row) for row in rows]

    def save_feedback(self, feedback: PaperFeedback) -> None:
        self.conn.execute(
            """
            INSERT INTO paper_feedback (
                paper_uid, profile_id, rating, note, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                feedback.paper_uid,
                feedback.profile_id,
                feedback.rating.value,
                feedback.note,
                (feedback.created_at or datetime.now(UTC)).isoformat(),
            ),
        )
        self.conn.commit()

    def feedback_adjustments(self, profile_id: str) -> dict[str, int]:
        rows = self.conn.execute(
            """
            SELECT paper_uid, rating, COUNT(*) AS count
            FROM paper_feedback
            WHERE profile_id = ?
            GROUP BY paper_uid, rating
            """,
            (profile_id,),
        ).fetchall()
        adjustments: dict[str, int] = {}
        weights = {
            FeedbackRating.UP.value: 8,
            FeedbackRating.DOWN.value: -8,
            FeedbackRating.SAVE.value: 15,
            FeedbackRating.SKIP.value: -15,
        }
        for row in rows:
            adjustments[row["paper_uid"]] = adjustments.get(row["paper_uid"], 0) + weights[row["rating"]] * int(
                row["count"]
            )
        return adjustments

    def latest_daily_classifications(
        self,
        profile: WatchProfile,
        start: date,
        end: date,
        limit: int,
    ) -> list[ClassifiedPaper]:
        rows = self.conn.execute(
            """
            SELECT p.*, c.profile_id, c.relevance_score, c.novelty_score,
                   c.evidence_score, c.total_score, c.reasons_json,
                   c.labels_json, c.status
            FROM papers p
            JOIN classifications c ON c.paper_uid = p.uid
            WHERE c.profile_id = ?
              AND c.status = ?
              AND (
                  p.published_at BETWEEN ? AND ?
                  OR date(p.discovered_at) BETWEEN ? AND ?
              )
            ORDER BY c.total_score DESC
            LIMIT ?
            """,
            (
                profile.id,
                PaperStatus.SELECTED.value,
                start.isoformat(),
                end.isoformat(),
                start.isoformat(),
                end.isoformat(),
                limit,
            ),
        ).fetchall()
        return [_classified_row(row) for row in rows]

    def selected_classifications(
        self,
        profile: WatchProfile,
        limit: int,
        missing_insights_only: bool = False,
    ) -> list[ClassifiedPaper]:
        sql = """
            SELECT p.*, c.profile_id, c.relevance_score, c.novelty_score,
                   c.evidence_score, c.total_score, c.reasons_json,
                   c.labels_json, c.status
            FROM papers p
            JOIN classifications c ON c.paper_uid = p.uid
            LEFT JOIN paper_insights i ON i.paper_uid = p.uid AND i.profile_id = c.profile_id
            WHERE c.profile_id = ?
              AND c.status = ?
        """
        params: list[object] = [profile.id, PaperStatus.SELECTED.value]
        if missing_insights_only:
            sql += " AND i.paper_uid IS NULL"
        sql += " ORDER BY c.total_score DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [_classified_row(row) for row in rows]

    def classified_paper(self, paper_uid: str, profile_id: str) -> ClassifiedPaper | None:
        row = self.conn.execute(
            """
            SELECT p.*, c.profile_id, c.relevance_score, c.novelty_score,
                   c.evidence_score, c.total_score, c.reasons_json,
                   c.labels_json, c.status
            FROM papers p
            JOIN classifications c ON c.paper_uid = p.uid
            WHERE c.paper_uid = ? AND c.profile_id = ?
            """,
            (paper_uid, profile_id),
        ).fetchone()
        return _classified_row(row) if row else None

    def daily_classifications(
        self,
        profile: WatchProfile,
        target: date,
        limit: int,
    ) -> list[ClassifiedPaper]:
        rows = self.conn.execute(
            """
            SELECT p.*, c.profile_id, c.relevance_score, c.novelty_score,
                   c.evidence_score, c.total_score, c.reasons_json,
                   c.labels_json, c.status
            FROM papers p
            JOIN classifications c ON c.paper_uid = p.uid
            WHERE c.profile_id = ?
              AND c.status = ?
              AND (
                  p.published_at = ?
                  OR date(p.discovered_at) = ?
              )
            ORDER BY c.total_score DESC
            LIMIT ?
            """,
            (
                profile.id,
                PaperStatus.SELECTED.value,
                target.isoformat(),
                target.isoformat(),
                limit,
            ),
        ).fetchall()
        return [_classified_row(row) for row in rows]


def _date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _path_key(value: str) -> str:
    return value.replace("\\", "/")


def _paper_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["authors"] = json.loads(data.pop("authors_json") or "[]")
    if "labels_json" in data and data["labels_json"]:
        data["labels"] = json.loads(data.pop("labels_json"))
    if "reasons_json" in data and data["reasons_json"]:
        data["reasons"] = json.loads(data.pop("reasons_json"))
    insight_keys = (
        "chinese_summary",
        "content_analysis",
        "critique",
        "follow_up",
        "evidence_scope",
        "reading_path",
        "source_path",
        "confidence",
    )
    insight = {key: data.pop(key, None) for key in insight_keys}
    data["insight"] = insight if insight["chinese_summary"] else None
    return data


def _insight_row(row: sqlite3.Row) -> PaperInsight:
    return PaperInsight(
        paper_uid=row["paper_uid"],
        profile_id=row["profile_id"],
        chinese_summary=row["chinese_summary"],
        content_analysis=row["content_analysis"],
        critique=row["critique"],
        follow_up=row["follow_up"],
        evidence_scope=row["evidence_scope"],
        reading_path=row["reading_path"],
        source_path=row["source_path"],
        confidence=row["confidence"],
    )


def _classified_row(row: sqlite3.Row) -> ClassifiedPaper:
    paper = Paper(
        uid=row["uid"],
        title=row["title"],
        authors=tuple(json.loads(row["authors_json"] or "[]")),
        abstract=row["abstract"],
        source=row["source"],
        source_kind=row["source_kind"],
        published_at=date.fromisoformat(row["published_at"]) if row["published_at"] else None,
        discovered_at=datetime.fromisoformat(row["discovered_at"]),
        url=row["url"],
        doi=row["doi"],
        journal=row["journal"],
        raw_id=row["raw_id"],
    )
    return ClassifiedPaper(
        paper=paper,
        profile_id=row["profile_id"],
        relevance_score=row["relevance_score"],
        novelty_score=row["novelty_score"],
        evidence_score=row["evidence_score"],
        total_score=row["total_score"],
        reasons=tuple(json.loads(row["reasons_json"] or "[]")),
        labels=tuple(json.loads(row["labels_json"] or "[]")),
        status=PaperStatus(row["status"]),
    )


def _run_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["options"] = json.loads(data.pop("options_json") or "{}")
    return data
