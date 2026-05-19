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

CREATE TABLE IF NOT EXISTS search_queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stat_date TEXT NOT NULL,
    adgroup_id TEXT,
    keyword_id TEXT,
    keyword TEXT,
    query TEXT NOT NULL,
    impressions INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    cost INTEGER DEFAULT 0,
    ctr REAL DEFAULT 0,
    cpc INTEGER DEFAULT 0,
    conversions INTEGER,
    conv_value INTEGER,
    fetched_at TEXT NOT NULL,
    UNIQUE (stat_date, adgroup_id, keyword_id, query)
);

CREATE INDEX IF NOT EXISTS idx_sq_date ON search_queries(stat_date);
CREATE INDEX IF NOT EXISTS idx_sq_adgroup ON search_queries(adgroup_id);
CREATE INDEX IF NOT EXISTS idx_sq_query ON search_queries(query);

CREATE TABLE IF NOT EXISTS hourly_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stat_date TEXT NOT NULL,
    hour INTEGER NOT NULL CHECK(hour >= 0 AND hour <= 23),
    adgroup_id TEXT,
    impressions INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    cost INTEGER DEFAULT 0,
    ctr REAL DEFAULT 0,
    cpc INTEGER DEFAULT 0,
    fetched_at TEXT NOT NULL,
    UNIQUE (stat_date, hour, adgroup_id)
);

CREATE INDEX IF NOT EXISTS idx_hs_date ON hourly_stats(stat_date);
CREATE INDEX IF NOT EXISTS idx_hs_hour ON hourly_stats(hour);
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


# ─── stat report storage (search_queries / hourly_stats) ───────────────────


def save_search_queries(rows: list, db_path: Path = DB_PATH) -> int:
    """검색어 보고서 row 들을 search_queries 테이블에 저장 (UPSERT).

    rows: list[StatRow] (reports.py 의 StatRow 인스턴스)
    동일 (stat_date, adgroup_id, keyword_id, query) 는 덮어쓰기.
    """
    if not rows:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    payload = [
        (
            r.stat_date,
            r.adgroup_id,
            r.keyword_id,
            r.keyword,
            r.query or "",
            r.impressions,
            r.clicks,
            r.cost,
            r.ctr,
            r.cpc,
            r.conversions,
            r.conv_value,
            now,
        )
        for r in rows
        if r.query
    ]
    if not payload:
        return 0
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO search_queries
            (stat_date, adgroup_id, keyword_id, keyword, query,
             impressions, clicks, cost, ctr, cpc, conversions, conv_value, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (stat_date, adgroup_id, keyword_id, query) DO UPDATE SET
              impressions = excluded.impressions,
              clicks = excluded.clicks,
              cost = excluded.cost,
              ctr = excluded.ctr,
              cpc = excluded.cpc,
              conversions = excluded.conversions,
              conv_value = excluded.conv_value,
              fetched_at = excluded.fetched_at
            """,
            payload,
        )
    return len(payload)


def save_hourly_stats(rows: list, db_path: Path = DB_PATH) -> int:
    """시간대 보고서 row 들을 hourly_stats 테이블에 저장 (UPSERT)."""
    if not rows:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    payload = [
        (
            r.stat_date,
            r.hour,
            r.adgroup_id,
            r.impressions,
            r.clicks,
            r.cost,
            r.ctr,
            r.cpc,
            now,
        )
        for r in rows
        if r.hour is not None
    ]
    if not payload:
        return 0
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO hourly_stats
            (stat_date, hour, adgroup_id, impressions, clicks, cost, ctr, cpc, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (stat_date, hour, adgroup_id) DO UPDATE SET
              impressions = excluded.impressions,
              clicks = excluded.clicks,
              cost = excluded.cost,
              ctr = excluded.ctr,
              cpc = excluded.cpc,
              fetched_at = excluded.fetched_at
            """,
            payload,
        )
    return len(payload)


def get_search_queries(
    since_date: Optional[str] = None,
    until_date: Optional[str] = None,
    adgroup_id: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """저장된 검색어 데이터 조회. since/until은 'YYYY-MM-DD' inclusive."""
    q = "SELECT * FROM search_queries WHERE 1=1"
    params: list = []
    if since_date:
        q += " AND stat_date >= ?"
        params.append(since_date)
    if until_date:
        q += " AND stat_date <= ?"
        params.append(until_date)
    if adgroup_id:
        q += " AND adgroup_id = ?"
        params.append(adgroup_id)
    q += " ORDER BY stat_date DESC, impressions DESC"
    with connect(db_path) as conn:
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def get_hourly_stats(
    since_date: Optional[str] = None,
    until_date: Optional[str] = None,
    adgroup_id: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """저장된 시간대 데이터 조회."""
    q = "SELECT * FROM hourly_stats WHERE 1=1"
    params: list = []
    if since_date:
        q += " AND stat_date >= ?"
        params.append(since_date)
    if until_date:
        q += " AND stat_date <= ?"
        params.append(until_date)
    if adgroup_id:
        q += " AND adgroup_id = ?"
        params.append(adgroup_id)
    q += " ORDER BY stat_date DESC, hour ASC"
    with connect(db_path) as conn:
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def last_fetched_at(table: str, db_path: Path = DB_PATH) -> Optional[str]:
    """주어진 테이블에서 가장 최근 fetched_at 타임스탬프 반환.

    table: 'search_queries' 또는 'hourly_stats'
    """
    if table not in ("search_queries", "hourly_stats"):
        raise ValueError(f"지원하지 않는 테이블: {table}")
    with connect(db_path) as conn:
        row = conn.execute(
            f"SELECT MAX(fetched_at) AS t FROM {table}"
        ).fetchone()
        return row["t"] if row and row["t"] else None


def clear_stat_tables(db_path: Path = DB_PATH) -> None:
    """광고 데이터 테이블 비우기 (decisions 는 보존)."""
    with connect(db_path) as conn:
        conn.execute("DELETE FROM search_queries")
        conn.execute("DELETE FROM hourly_stats")
