"""keywords.yaml 자동 생성 — 선택된 광고그룹 ID 들로 yaml 빌드.

Chat-driven 셋업의 3단계. Claude 이 사장님 선택을 받은 후 호출한다.

사용법:
  python scripts/setup_yaml.py --groups grp-a001-...,grp-a001-...
  python scripts/setup_yaml.py --all                # 모든 광고그룹
  python scripts/setup_yaml.py --all --target-rank 2 --max-bid 15000

기존 keywords.yaml 이 있으면 .bak 으로 백업 후 덮어쓴다.
"""
from __future__ import annotations

import argparse
import sys

from powerlink_pilot.config import (
    CONFIG_PATH_DEFAULT,
    require_credentials,
    write_yaml_atomic,
)
from powerlink_pilot.naver import NaverAdsClient, NaverApiError
from powerlink_pilot.wizard import _build_yaml


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Chat-driven keywords.yaml 생성"
    )
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--groups",
        metavar="ID,ID,...",
        help="콤마 구분 광고그룹 ID 리스트",
    )
    g.add_argument(
        "--all",
        action="store_true",
        help="계정의 모든 광고그룹 포함",
    )

    parser.add_argument("--target-rank", dest="target_rank", type=int, default=3,
                        help="목표 순위 (1~10, 기본 3)")
    parser.add_argument("--max-bid", dest="max_bid", type=int, default=10000,
                        help="최대 입찰가 원 (기본 10000)")
    parser.add_argument("--min-bid", dest="min_bid", type=int, default=100,
                        help="최소 입찰가 원 (기본 100)")
    parser.add_argument("--step", type=int, default=500,
                        help="1회 조정 단위 원 (기본 500)")

    args = parser.parse_args()

    # 입력 검증
    if not 1 <= args.target_rank <= 10:
        print("❌ --target-rank 는 1~10 범위여야 합니다")
        return 1
    if args.min_bid >= args.max_bid:
        print(f"❌ --min-bid({args.min_bid}) 가 --max-bid({args.max_bid}) 이상")
        return 1
    if args.max_bid < 70 or args.min_bid < 70:
        print("❌ max_bid / min_bid 는 70원 이상 (네이버 최저)")
        return 1

    try:
        creds = require_credentials()
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    client = NaverAdsClient(creds)

    print("📡 광고그룹 정보 가져오는 중...")
    try:
        all_groups = client.list_all_adgroups()
    except NaverApiError as e:
        print(f"❌ 광고그룹 조회 실패: {e}")
        return 1

    if not all_groups:
        print("❌ 광고그룹이 하나도 없습니다. 네이버 광고 콘솔에서 캠페인·광고그룹을 먼저 만드세요")
        return 1

    if args.all:
        selected = all_groups
    else:
        wanted = {gid.strip() for gid in args.groups.split(",") if gid.strip()}
        if not wanted:
            print("❌ --groups 에 ID 가 비어있습니다")
            return 1
        selected = [g for g in all_groups if g.get("nccAdgroupId") in wanted]
        if not selected:
            print("❌ 지정한 광고그룹 ID 가 계정에서 발견되지 않았습니다")
            print(f"   계정의 광고그룹 ID: {[g.get('nccAdgroupId') for g in all_groups[:5]]}")
            return 1
        missing = wanted - {g.get("nccAdgroupId") for g in selected}
        if missing:
            print(f"⚠️  요청한 ID 중 발견 안 됨: {missing}")

    print(f"   선택된 광고그룹: {len(selected)}개")

    print("📡 키워드 페치 중...")
    all_keywords: list[dict] = []
    for g in selected:
        gid = g.get("nccAdgroupId")
        gname = g.get("name", "")
        try:
            kws = client.list_keywords(gid)
        except NaverApiError as e:
            print(f"   ⚠️  '{gname}' 키워드 조회 실패: {e}")
            continue
        print(f"   '{gname}': {len(kws)}개")
        all_keywords.extend(kws)

    if not all_keywords:
        print("❌ 활성·승인된 키워드가 없습니다. 광고그룹에 키워드를 추가하세요")
        return 1

    defaults = {
        "target_rank": args.target_rank,
        "max_bid": args.max_bid,
        "min_bid": args.min_bid,
        "step": args.step,
    }

    yaml_path = CONFIG_PATH_DEFAULT
    if yaml_path.exists():
        backup = yaml_path.with_suffix(yaml_path.suffix + ".bak")
        yaml_path.replace(backup)
        print(f"   기존 yaml 백업: {backup}")

    yaml_content = _build_yaml(selected, all_keywords, defaults)
    write_yaml_atomic(yaml_path, yaml_content)

    print()
    print(f"✅ {yaml_path} 생성 완료")
    print(f"   광고그룹 {len(selected)}개, 키워드 {len(all_keywords)}개")
    print(f"   기본 정책: target_rank={args.target_rank}, max_bid={args.max_bid:,}원, "
          f"min_bid={args.min_bid:,}원, step={args.step:,}원")
    print()
    print("   다음 단계: python -m powerlink_pilot run --dry-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
