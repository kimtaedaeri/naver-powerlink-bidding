"""광고그룹 발견 — 사장님 네이버 계정의 모든 광고그룹을 JSON 으로 출력.

Chat-driven 셋업의 2단계. Claude 이 출력을 파싱해서 사장님께 한국어로 보여주고,
선택을 받아 `scripts/setup_yaml.py` 에 전달한다.

출력: stdout 에 JSON ({"adgroups": [...]} 또는 {"error": "..."})
종료 코드: 0 (성공) / 1 (실패)
"""
from __future__ import annotations

import json
import sys

from powerlink_pilot.config import require_credentials
from powerlink_pilot.naver import NaverAdsClient, NaverApiError


def main() -> int:
    try:
        creds = require_credentials()
    except ValueError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1

    client = NaverAdsClient(creds)
    try:
        adgroups = client.list_all_adgroups()
    except NaverApiError as e:
        print(json.dumps({"error": f"광고그룹 조회 실패: {e}"}, ensure_ascii=False))
        return 1

    result = {
        "adgroups": [
            {
                "id": g.get("nccAdgroupId", ""),
                "name": g.get("name", ""),
                "campaign": g.get("_campaign_name", ""),
            }
            for g in adgroups
            if g.get("nccAdgroupId")
        ]
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
