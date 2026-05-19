"""네이버 검색광고 API 클라이언트.

공식 문서: https://naver.github.io/searchad-apidoc/
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

BASE_URL = "https://api.searchad.naver.com"
DEFAULT_TIMEOUT = 30


class NaverApiError(Exception):
    """네이버 API 응답 오류."""

    def __init__(self, status_code: int, body: str, hint: str = ""):
        self.status_code = status_code
        self.body = body
        self.hint = hint
        msg = f"[{status_code}] {body[:200]}"
        if hint:
            msg += f"\n   힌트: {hint}"
        super().__init__(msg)


class NaverAuthError(NaverApiError):
    """인증 실패 (401, 403)."""


@dataclass
class NaverCredentials:
    api_key: str
    secret_key: str
    customer_id: str

    def is_complete(self) -> bool:
        return bool(self.api_key and self.secret_key and self.customer_id)


def _signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


class NaverAdsClient:
    """네이버 검색광고 API 호출을 담당하는 가벼운 클라이언트."""

    def __init__(self, credentials: NaverCredentials, timeout: int = DEFAULT_TIMEOUT):
        if not credentials.is_complete():
            raise ValueError("자격증명 누락 (API_KEY/SECRET_KEY/CUSTOMER_ID 필요)")
        self.creds = credentials
        self.timeout = timeout

    # ─── core HTTP ───────────────────────────────────────────────────────

    def _headers(self, method: str, uri: str) -> dict[str, str]:
        timestamp = str(round(time.time() * 1000))
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": timestamp,
            "X-API-KEY": self.creds.api_key,
            "X-Customer": str(self.creds.customer_id),
            "X-Signature": _signature(timestamp, method, uri, self.creds.secret_key),
        }

    def _request(
        self,
        method: str,
        uri: str,
        params: Optional[dict] = None,
        json_body: Any = None,
    ) -> Any:
        headers = self._headers(method, uri)
        try:
            response = requests.request(
                method=method,
                url=BASE_URL + uri,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise NaverApiError(0, str(e), hint="네트워크 연결 확인") from e

        if response.status_code in (401, 403):
            raise NaverAuthError(
                response.status_code,
                response.text,
                hint="API 키 재발급 후 `setup` 재실행",
            )
        if response.status_code == 429:
            raise NaverApiError(
                429,
                response.text,
                hint="호출 빈도 초과. 잠시 후 재시도",
            )
        if not 200 <= response.status_code < 300:
            raise NaverApiError(response.status_code, response.text)

        return response.json() if response.text else None

    # ─── verify auth (cheap call) ─────────────────────────────────────────

    def verify(self) -> bool:
        """자격증명이 유효한지 확인. campaigns 조회를 인증 검증용으로 사용."""
        self._request("GET", "/ncc/campaigns")
        return True

    # ─── discovery ───────────────────────────────────────────────────────

    def list_campaigns(self) -> list[dict]:
        return self._request("GET", "/ncc/campaigns") or []

    def list_adgroups(self, campaign_id: Optional[str] = None) -> list[dict]:
        params = {"nccCampaignId": campaign_id} if campaign_id else None
        return self._request("GET", "/ncc/adgroups", params=params) or []

    def list_all_adgroups(self) -> list[dict]:
        """모든 캠페인의 광고그룹을 발견. campaign 정보를 group dict 에 추가."""
        campaigns = self.list_campaigns()
        all_groups: list[dict] = []
        for camp in campaigns:
            cid = camp.get("nccCampaignId")
            cname = camp.get("name", "")
            if not cid:
                continue
            try:
                groups = self.list_adgroups(cid)
            except NaverApiError:
                continue
            for g in groups:
                g["_campaign_name"] = cname
                all_groups.append(g)
        return all_groups

    def list_keywords(self, adgroup_id: str) -> list[dict]:
        """광고그룹의 ELIGIBLE & APPROVED 키워드만 반환."""
        result = self._request(
            "GET",
            "/ncc/keywords",
            params={"nccAdgroupId": adgroup_id},
        )
        if not result:
            return []
        return [
            kw
            for kw in result
            if kw.get("status") == "ELIGIBLE"
            and kw.get("inspectStatus") == "APPROVED"
            and not kw.get("delFlag", False)
        ]

    # ─── estimate ────────────────────────────────────────────────────────

    def estimate_position_bids(
        self,
        items: list[dict],
        device: str = "PC",
        period: str = "P1M",
    ) -> list[dict]:
        """
        target rank 도달에 필요한 입찰가를 추정.

        입력 items: [{"keyword": "토지담보대출", "position": 3}, ...]
            (이 함수 안에서 네이버 API 가 요구하는 'key' 필드로 변환)
        반환: API 가 돌려준 estimate 배열. 각 항목 형식 예시:
            {"key": "토지담보대출", "position": 3, "bid": 770}
        """
        body_items = [
            {"key": it["keyword"], "position": it["position"]}
            for it in items
        ]
        body = {"device": device, "period": period, "items": body_items}
        result = self._request(
            "POST",
            "/estimate/average-position-bid/keyword",
            json_body=body,
        )
        if isinstance(result, dict):
            return result.get("estimate") or result.get("estimates") or []
        return result or []

    # ─── restricted keywords (부정 키워드) ───────────────────────────────

    def list_restricted_keywords(self, adgroup_id: str) -> list[dict]:
        """광고그룹의 부정 키워드 목록.

        Naver 응답 항목 예시:
            {"nccAdgroupId": "...", "keyword": "사기", "type": "KEYWORD_PLUS_RESTRICT"}

        type 의미:
          - KEYWORD: 일반 부정 키워드
          - KEYWORD_PLUS_RESTRICT: 확장 검색 제외 키워드
        """
        result = self._request(
            "GET",
            f"/ncc/adgroups/{adgroup_id}/restricted-keywords",
        )
        return result if isinstance(result, list) else []

    def add_restricted_keywords(
        self,
        adgroup_id: str,
        keywords: list[str],
        *,
        keyword_type: str = "KEYWORD_PLUS_RESTRICT",
    ) -> list[dict]:
        """광고그룹에 부정 키워드 일괄 등록.

        keywords: 등록할 검색어/키워드 리스트 (중복 체크는 호출자가 미리)
        keyword_type:
          - "KEYWORD_PLUS_RESTRICT" (기본) — 확장 검색에서 차단
          - "KEYWORD" — 일반 부정

        반환: 등록 결과 객체 리스트
        """
        if not keywords:
            return []
        body = [
            {
                "nccAdgroupId": adgroup_id,
                "keyword": kw,
                "type": keyword_type,
            }
            for kw in keywords
        ]
        result = self._request(
            "POST",
            f"/ncc/adgroups/{adgroup_id}/restricted-keywords",
            json_body=body,
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return []

    # ─── stat reports (async: POST → polling → download) ────────────────

    def create_stat_report(self, report_type: str, stat_date: str) -> dict:
        """비동기 보고서 생성 요청.

        report_type: 'AD_DETAIL' (검색어), 'AD' (키워드 집계), 'TIME' (시간대별) 등
        stat_date: 단일 일자 'YYYY-MM-DD'

        반환: {"reportJobId": "...", "status": "REGIST"} 형식
        """
        body = {"reportTp": report_type, "statDt": stat_date}
        result = self._request("POST", "/stat-reports", json_body=body)
        if not isinstance(result, dict):
            raise NaverApiError(0, f"예상치 못한 응답: {result}")
        return result

    def get_stat_report(self, report_job_id: str) -> dict:
        """보고서 상태·다운로드 URL 조회.

        반환 예: {
            "reportJobId": "...",
            "status": "REGIST" | "RUNNING" | "BUILT" | "NONE" | "FAILED",
            "downloadUrl": "...",  (status == BUILT 일 때만)
            ...
        }
        """
        result = self._request("GET", f"/stat-reports/{report_job_id}")
        if not isinstance(result, dict):
            raise NaverApiError(0, f"예상치 못한 응답: {result}")
        return result

    def download_stat_report(self, download_url: str) -> bytes:
        """보고서 파일 다운로드 (TSV/CSV 바이너리 반환).

        Naver 의 downloadUrl 은 보통 별도 storage 호스트의 서명된 URL.
        같은 API 도메인이면 인증 헤더를 추가, 아니면 단순 GET.
        """
        if not download_url:
            raise ValueError("downloadUrl 이 비어있습니다")

        from urllib.parse import urlparse

        parsed = urlparse(download_url)
        headers: dict[str, str] = {}
        if parsed.netloc.endswith("searchad.naver.com"):
            headers = self._headers("GET", parsed.path or "/")

        try:
            response = requests.get(
                download_url, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as e:
            raise NaverApiError(0, str(e), hint="네트워크 또는 다운로드 URL 만료") from e

        if not 200 <= response.status_code < 300:
            raise NaverApiError(response.status_code, response.text[:200])

        return response.content

    # ─── update ──────────────────────────────────────────────────────────

    def update_keyword_bid(self, keyword_data: dict, new_bid: int) -> dict:
        """단일 키워드 입찰가 변경 (PUT /ncc/keywords)."""
        if not isinstance(keyword_data, dict):
            raise TypeError("keyword_data 는 dict 여야 합니다")
        updated = keyword_data.copy()
        updated["bidAmt"] = int(new_bid)
        updated["useGroupBidAmt"] = False  # 그룹 입찰 비활성화
        result = self._request(
            "PUT",
            "/ncc/keywords",
            params={"fields": "bidAmt"},
            json_body=[updated],
        )
        if isinstance(result, list) and result:
            return result[0]
        return result if isinstance(result, dict) else {}
