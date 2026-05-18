"""SQLite 헬퍼 — 결정 이력을 단일 테이블에 기록한다."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path("powerlink_pilot.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    mode TEXT NOT NULL,
    keyword_id TEXT,
    keyword_name TEXT NOT NULL,
    adgroup_id TEXT,
    current_bid INTEGER,
    target_rank INTEGER,
    estimated_bid INTEGER,
    new_bid INTEGER,
    action TEXT NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE INDEX IF NOT EXISTS idx_decisions_keyword ON decisions(keyword_name, ts);
"""


@contextmanager
def connect(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path = DB_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def log_decision(
    *,
    mode: str,
    keyword_name: str,
    current_bid: Optional[int],
    target_rank: int,
    new_bid: int,
    action: str,
    reason: str = "",
    keyword_id: Optional[str] = None,
    adgroup_id: Optional[str] = None,
    estimated_bid: Optional[int] = None,
    db_path: Path = DB_PATH,
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO decisions
            (ts, mode, keyword_id, keyword_name, adgroup_id,
             current_bid, target_rank, estimated_bid, new_bid, action, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                mode,
                keyword_id,
                keyword_name,
                adgroup_id,
                current_bid,
                target_rank,
                estimated_bid,
                new_bid,
                action,
                reason,
            ),
        )


def recent_decisions(
    limit: int = 20,
    mode: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    with connect(db_path) as conn:
        if mode:
            cursor = conn.execute(
                "SELECT * FROM decisions WHERE mode = ? ORDER BY ts DESC LIMIT ?",
                (mode, limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM decisions ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]


def get_last_bid(keyword_name: str, db_path: Path = DB_PATH) -> Optional[int]:
    """가장 최근 결정에서 해당 키워드의 new_bid를 반환. 샘플 모드 상태 영속화에 사용."""
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT new_bid FROM decisions
            WHERE keyword_name = ?
            ORDER BY ts DESC LIMIT 1
            """,
            (keyword_name,),
        ).fetchone()
        return row["new_bid"] if row else None


def reset_db(db_path: Path = DB_PATH) -> None:
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)
