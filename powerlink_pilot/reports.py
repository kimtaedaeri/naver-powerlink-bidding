"""Naver stat-reports 비동기 보고서 추상화.

흐름: 보고서 생성 요청 → 상태 polling → CSV/TSV 다운로드 → row 파싱.

호출자(CLI 또는 Claude) 가 사용하기 쉽도록 high-level 함수 제공:
  - fetch_search_query_report(client, dates)
      AD_DETAIL 보고서로 검색어별 노출·클릭 데이터
  - fetch_hourly_report(client, dates)
      TIME 보고서로 시간대별 데이터

내부 헬퍼:
  - _wait_for_report(client, report_job_id)
  - _parse_tsv(content) → list[dict]
"""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from .naver import NaverAdsClient, NaverApiError


DEFAULT_POLL_INTERVAL = 5  # 초
DEFAULT_POLL_TIMEOUT = 300  # 5분
SUCCESS_STATUSES = {"BUILT"}
NO_DATA_STATUSES = {"NONE"}  # 보고서 생성됐지만 데이터 없음 (정상 케이스, 광고 노출 0인 날)
FAIL_STATUSES = {"FAILED"}


@dataclass
class StatRow:
    """파싱된 보고서 한 줄."""

    stat_date: str  # "YYYY-MM-DD"
    adgroup_id: Optional[str]
    keyword_id: Optional[str]
    keyword: Optional[str]  # 등록된 키워드
    query: Optional[str]  # 실제 검색어 (검색어 보고서)
    hour: Optional[int]  # 0~23 (시간대 보고서)
    impressions: int
    clicks: int
    cost: int  # 원
    ctr: float  # 0.0~1.0
    cpc: int  # 원
    conversions: Optional[int] = None  # 전환 추적 있을 때만
    conv_value: Optional[int] = None  # 전환 가치 (원)


# ─── 폴링 ────────────────────────────────────────────────────────────────


def _wait_for_report(
    client: NaverAdsClient,
    report_job_id: str,
    *,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_POLL_TIMEOUT,
    progress: Optional[Callable[[str, float], None]] = None,
) -> dict:
    """report 가 BUILT 될 때까지 polling. 반환: 최종 status dict.

    progress callback: (status, elapsed_seconds) 를 받아 진행상황 출력 가능.
    """
    started = time.monotonic()
    while True:
        status_obj = client.get_stat_report(report_job_id)
        status = status_obj.get("status", "")

        elapsed = time.monotonic() - started
        if progress:
            progress(status, elapsed)

        if status in SUCCESS_STATUSES:
            return status_obj
        if status in NO_DATA_STATUSES:
            # 데이터 없음을 정상 종료로 처리 (downloadUrl 없는 dict 반환)
            # 호출자가 빈 downloadUrl 보고 "데이터 없음" 안내
            return status_obj
        if status in FAIL_STATUSES:
            raise NaverApiError(
                0,
                f"보고서 생성 실패 (status={status})",
                hint="다른 날짜·보고서 유형으로 재시도",
            )
        if elapsed > timeout:
            raise NaverApiError(
                0,
                f"보고서 대기 시간 초과 ({timeout}초)",
                hint="잠시 후 재시도. 데이터 양이 많으면 5분 이상 걸릴 수 있음",
            )

        time.sleep(poll_interval)


# ─── 파싱 ────────────────────────────────────────────────────────────────


def _parse_tsv(content: bytes) -> list[dict]:
    """Naver stat-report TSV/CSV 본문을 dict 리스트로 파싱.

    Naver 보고서는 보통 헤더 없는 TSV. 호출자가 컬럼 위치를 알아야 함.
    이 함수는 일반적인 파싱만 — 의미 부여는 specific fetch 함수에서.
    """
    if not content:
        return []
    text = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    rows: list[dict] = []
    for raw in reader:
        if not raw or all(not c.strip() for c in raw):
            continue
        rows.append({"_cols": raw})
    return rows


def _safe_int(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except (ValueError, TypeError):
        return 0


def _normalize_date(s: str) -> Optional[str]:
    """Naver 의 다양한 일자 형식을 ISO 'YYYY-MM-DD' 로 정규화. 실패 시 None.

    헤더 행 감지에도 사용 — 일자 형식이 아니면 None 반환되어 호출자가 skip.
    지원 형식:
      - 'YYYYMMDD' (8자리 숫자)
      - 'YYYY-MM-DD'
      - 'YYYY-MM-DD HH:MM:SS'
      - 'YYYY/MM/DD'
    """
    if not s:
        return None
    raw = str(s).strip()
    # YYYYMMDD
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    # YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS
    head = raw.split()[0] if " " in raw else raw
    head = head.replace("/", "-")
    parts = head.split("-")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            pass
    return None


# ─── 검색어 보고서 (AD_DETAIL) ──────────────────────────────────────────


def fetch_search_query_report(
    client: NaverAdsClient,
    dates: list[date],
    *,
    progress: Optional[Callable[[str], None]] = None,
) -> list[StatRow]:
    """주어진 일자들의 검색어 보고서를 받아 StatRow 리스트로 반환.

    Naver AD_DETAIL 보고서는 단일 일자 단위로 생성됨. 여러 날 합치려면 반복 호출.

    AD_DETAIL TSV 컬럼 (Naver 공식, 일반적 순서):
        [0] 일자, [1] 광고주ID, [2] 캠페인ID, [3] 광고그룹ID,
        [4] 광고그룹명, [5] 키워드ID, [6] 키워드, [7] 검색어(소재),
        [8] 노출수, [9] 클릭수, [10] 광고비(VAT포함, 원),
        [11] 평균노출순위, ...
    """
    all_rows: list[StatRow] = []

    for d in dates:
        date_str = d.isoformat()
        if progress:
            progress(f"📅 {date_str} 검색어 보고서 요청 중...")

        try:
            job = client.create_stat_report("AD_DETAIL", date_str)
        except NaverApiError as e:
            if progress:
                progress(f"   ⚠️  {date_str} 요청 실패: {e}")
            continue

        job_id = job.get("reportJobId")
        if not job_id:
            continue

        def _p(status: str, elapsed: float) -> None:
            if progress:
                progress(f"   ⏳ {date_str} 생성 중 (status={status}, {int(elapsed)}s)")

        try:
            done = _wait_for_report(client, job_id, progress=_p)
        except NaverApiError as e:
            if progress:
                progress(f"   ⚠️  {date_str} polling 실패: {e}")
            continue

        url = done.get("downloadUrl")
        if not url:
            if progress:
                progress(f"   ⚠️  {date_str} 데이터 없음")
            continue

        try:
            content = client.download_stat_report(url)
        except NaverApiError as e:
            if progress:
                progress(f"   ⚠️  {date_str} 다운로드 실패: {e}")
            continue

        parsed = _parse_tsv(content)
        valid_rows = 0
        for r in parsed:
            cols = r.get("_cols") or []
            if len(cols) < 11:
                continue
            # 헤더 행 감지: cols[0] 이 일자 형식이 아니면 skip
            normalized_date = _normalize_date(cols[0])
            if not normalized_date:
                continue
            try:
                clicks = _safe_int(cols[9])
                impressions = _safe_int(cols[8])
                cost = _safe_int(cols[10])
                ctr = clicks / impressions if impressions > 0 else 0.0
                cpc = cost // clicks if clicks > 0 else 0
                all_rows.append(
                    StatRow(
                        stat_date=normalized_date,
                        adgroup_id=cols[3] or None,
                        keyword_id=cols[5] or None,
                        keyword=cols[6] or None,
                        query=cols[7] or None,
                        hour=None,
                        impressions=impressions,
                        clicks=clicks,
                        cost=cost,
                        ctr=ctr,
                        cpc=cpc,
                    )
                )
                valid_rows += 1
            except (IndexError, ValueError):
                continue

        if progress:
            progress(f"   ✅ {date_str}: {valid_rows}행 파싱 완료")

    return all_rows


# ─── 시간대 보고서 (TIME) ────────────────────────────────────────────────


def fetch_hourly_report(
    client: NaverAdsClient,
    dates: list[date],
    *,
    progress: Optional[Callable[[str], None]] = None,
) -> list[StatRow]:
    """주어진 일자들의 시간대별 보고서를 받아 StatRow 리스트로 반환.

    Naver TIME 보고서 TSV 컬럼 (일반적 순서):
        [0] 일자, [1] 시간(0~23), [2] 광고그룹ID, ...
        [-3] 노출수, [-2] 클릭수, [-1] 광고비

    Naver 의 TIME report 정확한 컬럼은 계정·연도에 따라 다를 수 있어
    숫자 컬럼은 끝에서부터 안전하게 파싱.
    """
    all_rows: list[StatRow] = []

    for d in dates:
        date_str = d.isoformat()
        if progress:
            progress(f"📅 {date_str} 시간대 보고서 요청 중...")

        try:
            job = client.create_stat_report("TIME", date_str)
        except NaverApiError as e:
            if progress:
                progress(f"   ⚠️  {date_str} 요청 실패: {e}")
            continue

        job_id = job.get("reportJobId")
        if not job_id:
            continue

        def _p(status: str, elapsed: float) -> None:
            if progress:
                progress(f"   ⏳ {date_str} 생성 중 (status={status}, {int(elapsed)}s)")

        try:
            done = _wait_for_report(client, job_id, progress=_p)
        except NaverApiError as e:
            if progress:
                progress(f"   ⚠️  {date_str} polling 실패: {e}")
            continue

        url = done.get("downloadUrl")
        if not url:
            continue

        try:
            content = client.download_stat_report(url)
        except NaverApiError as e:
            if progress:
                progress(f"   ⚠️  {date_str} 다운로드 실패: {e}")
            continue

        parsed = _parse_tsv(content)
        valid_rows = 0
        for r in parsed:
            cols = r.get("_cols") or []
            if len(cols) < 5:
                continue
            # 헤더 행 감지: cols[0] 이 일자 형식이 아니면 skip
            normalized_date = _normalize_date(cols[0])
            if not normalized_date:
                continue
            try:
                hour = _safe_int(cols[1])
                if not 0 <= hour <= 23:
                    continue
                # 끝에서부터 노출/클릭/광고비 추정 (열 수 변동 대응)
                cost = _safe_int(cols[-1])
                clicks = _safe_int(cols[-2])
                impressions = _safe_int(cols[-3])
                ctr = clicks / impressions if impressions > 0 else 0.0
                cpc = cost // clicks if clicks > 0 else 0
                all_rows.append(
                    StatRow(
                        stat_date=normalized_date,
                        adgroup_id=cols[2] if len(cols) > 2 else None,
                        keyword_id=None,
                        keyword=None,
                        query=None,
                        hour=hour,
                        impressions=impressions,
                        clicks=clicks,
                        cost=cost,
                        ctr=ctr,
                        cpc=cpc,
                    )
                )
                valid_rows += 1
            except (IndexError, ValueError):
                continue

        if progress:
            progress(f"   ✅ {date_str}: {valid_rows}행")

    return all_rows


# ─── 기간 헬퍼 ─────────────────────────────────────────────────────────


def last_n_days(n: int) -> list[date]:
    """오늘 기준 지난 n 일치 일자 리스트 (오늘 제외 — 어제부터 거꾸로)."""
    today = date.today()
    return [today - timedelta(days=i) for i in range(1, n + 1)]
