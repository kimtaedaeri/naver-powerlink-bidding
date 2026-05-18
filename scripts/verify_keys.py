"""네이버 API 키 검증 — `.env` 의 NAVER_* 키 3개가 유효한지 확인.

Chat-driven 셋업의 1단계로 사용. 사장님께 보여줄 한국어 메시지만 출력.

종료 코드:
  0 — 인증 성공
  1 — 키 누락 또는 인증 실패 (메시지로 원인 구분)
"""
from __future__ import annotations

import sys

from powerlink_pilot.config import require_credentials
from powerlink_pilot.naver import NaverAdsClient, NaverApiError, NaverAuthError


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return "(빈 값)"
    if len(value) <= keep:
        return "••••"
    return f"••••{value[-keep:]}"


def main() -> int:
    try:
        creds = require_credentials()
    except ValueError as e:
        print(f"❌ {e}")
        print("   → .env 를 다시 작성하거나 `prompts/02-api-key-naver.md` 안내를 따라주세요")
        return 1

    print("🔐 네이버 검색광고 API 키 검증 중...")
    client = NaverAdsClient(creds)

    try:
        client.verify()
    except NaverAuthError:
        print("❌ 인증 실패 — API 키 또는 비밀 키가 맞지 않습니다")
        print("   네이버 검색광고 콘솔에서 키 재발급 후 .env 를 다시 작성해주세요")
        print("   콘솔: https://manage.searchad.naver.com/customers")
        return 1
    except NaverApiError as e:
        print(f"❌ API 오류: {e}")
        print("   네트워크 또는 네이버 서버 상태를 확인 후 잠시 후 재시도해주세요")
        return 1

    print(f"✅ 인증 성공")
    print(f"   API_KEY:     {_mask(creds.api_key)}")
    print(f"   SECRET_KEY:  {_mask(creds.secret_key)}")
    print(f"   CUSTOMER_ID: {creds.customer_id}")
    print()
    print("   다음 단계: python scripts/discover_adgroups.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
