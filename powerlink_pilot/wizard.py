"""대화형 setup 마법사.

4 단계: 자격증명 입력·검증 → 광고그룹 선택 → 키워드 페치 → 기본값 입력 → atomic 저장.
"""
from __future__ import annotations

import getpass
from pathlib import Path
from typing import Optional

from .config import (
    CONFIG_PATH_DEFAULT,
    ENV_PATH_DEFAULT,
    write_env_atomic,
    write_yaml_atomic,
)
from .naver import NaverAdsClient, NaverApiError, NaverAuthError, NaverCredentials


def _prompt(prompt: str, default: Optional[str] = None, secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        if secret:
            value = getpass.getpass(f"{prompt}{suffix}: ").strip()
        else:
            value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default


def _prompt_int(prompt: str, default: int, minv: int = 1, maxv: int = 10**8) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if not raw:
            return default
        try:
            n = int(raw)
        except ValueError:
            print("   ⚠️  숫자만 입력해주세요")
            continue
        if not minv <= n <= maxv:
            print(f"   ⚠️  {minv}~{maxv} 범위 안의 숫자여야 합니다")
            continue
        return n


# ─── steps ──────────────────────────────────────────────────────────────


def _step1_auth() -> tuple[NaverCredentials, NaverAdsClient]:
    print("\n[1/4] 네이버 검색광고 API 인증")
    print("  발급 페이지: https://manage.searchad.naver.com/customers")
    print("  → 도구 > API 사용 관리 에서 API 키 / 비밀키 / Customer ID 확인")
    print()

    while True:
        api_key = _prompt("  API_KEY", secret=False)
        secret_key = _prompt("  SECRET_KEY", secret=True)
        customer_id = _prompt("  CUSTOMER_ID")

        creds = NaverCredentials(
            api_key=api_key,
            secret_key=secret_key,
            customer_id=customer_id,
        )
        client = NaverAdsClient(creds)

        print("\n  🔐 자격증명 검증 중...")
        try:
            client.verify()
            print("  ✅ 인증 성공")
            return creds, client
        except NaverAuthError as e:
            print(f"  ❌ 인증 실패: {e}")
            print("  키를 다시 확인해주세요.\n")
        except NaverApiError as e:
            print(f"  ❌ API 오류: {e}")
            print("  잠시 후 다시 시도해주세요.\n")


def _step2_select_adgroups(client: NaverAdsClient) -> list[dict]:
    print("\n[2/4] 관리할 광고그룹 선택")
    print("  📡 광고그룹 발견 중...")
    try:
        adgroups = client.list_all_adgroups()
    except NaverApiError as e:
        print(f"  ❌ 광고그룹 조회 실패: {e}")
        return []

    if not adgroups:
        print("  ⚠️  광고그룹이 없습니다. 네이버 광고 콘솔에서 캠페인·광고그룹을 먼저 생성하세요.")
        return []

    print(f"  발견된 광고그룹 {len(adgroups)}개:\n")
    for i, g in enumerate(adgroups, 1):
        camp = g.get("_campaign_name", "")
        gname = g.get("name", "")
        gid = g.get("nccAdgroupId", "")
        camp_str = f" / {camp}" if camp else ""
        print(f"   [{i}] {gname}{camp_str}")
        print(f"       {gid}")

    while True:
        raw = input("\n  관리할 그룹 번호 (콤마 구분, 또는 'all'): ").strip().lower()
        if not raw:
            continue
        if raw == "all":
            return adgroups
        try:
            indices = [int(x) for x in raw.split(",")]
            selected = [adgroups[i - 1] for i in indices]
            return selected
        except (ValueError, IndexError):
            print("   ⚠️  올바른 번호로 입력해주세요 (예: 1,3 또는 all)")


def _step3_fetch_keywords(client: NaverAdsClient, adgroups: list[dict]) -> list[dict]:
    print(f"\n[3/4] 키워드 자동 불러오기 ({len(adgroups)}개 그룹)")
    all_keywords: list[dict] = []
    for g in adgroups:
        gid = g.get("nccAdgroupId")
        gname = g.get("name", "")
        try:
            kws = client.list_keywords(gid)
        except NaverApiError as e:
            print(f"   ⚠️  '{gname}' 키워드 조회 실패: {e}")
            continue
        print(f"   '{gname}': 키워드 {len(kws)}개 (활성·승인 완료)")
        all_keywords.extend(kws)
    print(f"\n  총 {len(all_keywords)}개 키워드")
    return all_keywords


def _step4_defaults() -> dict:
    print("\n[4/4] 기본값 설정 (각 키워드는 yaml 에서 개별 override 가능)")
    return {
        "target_rank": _prompt_int("  목표 순위 (1~10)", default=3, minv=1, maxv=10),
        "max_bid": _prompt_int("  최대 입찰가 (원)", default=10000, minv=70),
        "min_bid": _prompt_int("  최소 입찰가 (원)", default=100, minv=70),
        "step": _prompt_int("  1회 조정 단위 (원)", default=500, minv=10),
    }


# ─── yaml builder ───────────────────────────────────────────────────────


def _build_yaml(adgroups: list[dict], keywords: list[dict], defaults: dict) -> str:
    lines: list[str] = []
    lines.append("# powerlink-pilot 설정 — `python -m powerlink_pilot setup` 으로 생성됨")
    lines.append("# 키워드 이름은 네이버 광고 계정과 일치해야 합니다 (수정 X)")
    lines.append("# target_rank·max_bid 등 정책 값은 자유롭게 수정하세요")
    lines.append("")

    lines.append("adgroups:")
    for g in adgroups:
        gid = g.get("nccAdgroupId", "")
        gname = g.get("name", "").replace('"', '\\"')
        lines.append(f'  - id: "{gid}"')
        if gname:
            lines.append(f'    name: "{gname}"')
    lines.append("")

    lines.append("defaults:")
    lines.append(f"  target_rank: {defaults['target_rank']}")
    lines.append(f"  max_bid: {defaults['max_bid']}")
    lines.append(f"  min_bid: {defaults['min_bid']}")
    lines.append(f"  step: {defaults['step']}")
    lines.append("")

    lines.append("keywords:")
    for kw in keywords:
        name = kw.get("keyword", "").replace('"', '\\"')
        lines.append(f'  - name: "{name}"')
    lines.append("")
    return "\n".join(lines)


# ─── entry point ────────────────────────────────────────────────────────


def run_setup(
    yaml_path: Path = CONFIG_PATH_DEFAULT,
    env_path: Path = ENV_PATH_DEFAULT,
) -> int:
    print("=" * 60)
    print("powerlink-pilot setup")
    print("=" * 60)

    if yaml_path.exists():
        print(f"\n⚠️  {yaml_path} 가 이미 존재합니다.")
        keep = input("   덮어쓰시겠습니까? 기존 파일은 .bak 으로 백업됩니다 (y/N): ").strip().lower()
        if keep != "y":
            print("취소되었습니다.")
            return 1
        backup = yaml_path.with_suffix(yaml_path.suffix + ".bak")
        yaml_path.replace(backup)
        print(f"   백업 완료: {backup}")

    creds, client = _step1_auth()
    selected_adgroups = _step2_select_adgroups(client)
    if not selected_adgroups:
        print("\n❌ 선택된 광고그룹이 없어 설정을 종료합니다.")
        return 1

    keywords = _step3_fetch_keywords(client, selected_adgroups)
    if not keywords:
        print("\n❌ 키워드가 없어 설정을 종료합니다.")
        return 1

    defaults = _step4_defaults()

    # Atomic write — yaml 먼저, env 그 다음
    yaml_content = _build_yaml(selected_adgroups, keywords, defaults)
    write_yaml_atomic(yaml_path, yaml_content)
    write_env_atomic(env_path, creds)

    print()
    print(f"✅ {yaml_path} 생성 완료 ({len(keywords)}개 키워드)")
    print(f"✅ {env_path} 생성 완료")
    print()
    print("다음 단계:")
    print("   python -m powerlink_pilot run --dry-run    # 안전 시뮬 (실제 변경 X)")
    print("   python -m powerlink_pilot run --live       # 실제 입찰 변경")
    return 0
