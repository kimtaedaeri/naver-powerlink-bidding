"""실 모드 — Naver Search Ad API 와 estimate API 를 사용한 dry-run / live 실행."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from .config import (
    CONFIG_PATH_DEFAULT,
    ENV_PATH_DEFAULT,
    Config,
    KeywordPolicy,
    load_config,
    policies_by_name,
    require_credentials,
)
from .db import log_decision
from .engine import decide
from .naver import NaverAdsClient, NaverApiError


# ─── helpers ────────────────────────────────────────────────────────────


def _fetch_managed_keywords(
    client: NaverAdsClient,
    config: Config,
) -> list[dict]:
    """yaml 의 adgroup ID 들에서 키워드를 수집하고, yaml 의 keyword 이름과 매칭."""
    if not config.adgroups:
        raise ValueError(
            "yaml 에 'adgroups' 섹션이 없습니다.\n"
            "   `python -m powerlink_pilot setup` 을 실행해 광고그룹을 등록하세요."
        )

    target_names = {p.name for p in config.keywords}
    matched: list[dict] = []
    matched_names: set[str] = set()

    for ag in config.adgroups:
        try:
            kws = client.list_keywords(ag.id)
        except NaverApiError as e:
            print(f"⚠️  광고그룹 '{ag.id}' 조회 실패: {e}")
            continue
        for kw in kws:
            kname = kw.get("keyword", "")
            if kname in target_names:
                matched.append(kw)
                matched_names.add(kname)

    missing = target_names - matched_names
    if missing:
        print(f"⚠️  네이버 계정에서 매칭 안 된 키워드 {len(missing)}개:")
        for name in list(missing)[:5]:
            print(f"     - {name}")
        if len(missing) > 5:
            print(f"     ... (+{len(missing) - 5}개)")
        print("   yaml 의 keyword 이름이 광고 계정과 정확히 일치하는지 확인하세요.\n")

    return matched


def _batch_estimate(
    client: NaverAdsClient,
    matched_keywords: list[dict],
    policies: dict[str, KeywordPolicy],
) -> dict[str, int]:
    """키워드별 target_rank 도달 추정 입찰가를 한 번의 batch 로 받는다."""
    items = []
    for kw in matched_keywords:
        kname = kw.get("keyword", "")
        policy = policies.get(kname)
        if not policy:
            continue
        items.append({"keyword": kname, "position": policy.target_rank})

    if not items:
        return {}

    try:
        results = client.estimate_position_bids(items)
    except NaverApiError as e:
        print(f"⚠️  Estimate API 호출 실패: {e}")
        return {}

    out: dict[str, int] = {}
    for r in results:
        # 네이버 응답은 'key' 필드를 사용 (request 와 동일)
        kname = r.get("key") or r.get("keyword")
        bid = r.get("bid") or r.get("estimateBid") or r.get("estimatedBid")
        if kname and bid is not None:
            try:
                out[kname] = int(bid)
            except (TypeError, ValueError):
                continue
    return out


# ─── confirmation prompts ──────────────────────────────────────────────


def _confirm_live() -> bool:
    print()
    print("=" * 60)
    print("⚠️  LIVE 모드 — 실제 입찰가가 변경됩니다.")
    print("=" * 60)
    print("처음 사용하시는 경우 `--dry-run` 으로 먼저 결과를 확인하세요.")
    print()
    answer = input("계속하시려면 'yes' 를 입력하세요: ").strip().lower()
    return answer == "yes"


# ─── main run ───────────────────────────────────────────────────────────


def run(
    *,
    live: bool,
    yaml_path: Path = CONFIG_PATH_DEFAULT,
    env_path: Path = ENV_PATH_DEFAULT,
    skip_confirm: bool = False,
) -> int:
    """dry-run (live=False) 또는 live (live=True) 실행."""
    creds = require_credentials(env_path)  # 누락이면 ValueError
    config = load_config(yaml_path)

    mode_label = "LIVE" if live else "DRY-RUN"
    print(f"🚀 powerlink-pilot — {mode_label} mode")
    print(f"📁 설정: {yaml_path}")
    print(f"📂 광고그룹 {len(config.adgroups)}개, 키워드 {len(config.keywords)}개")

    if live and not skip_confirm:
        if not _confirm_live():
            print("취소되었습니다.")
            return 1

    client = NaverAdsClient(creds)
    print("\n📡 키워드 페치 중...")
    matched = _fetch_managed_keywords(client, config)
    if not matched:
        print("❌ 매칭된 키워드가 없습니다.")
        return 1
    print(f"   매칭된 키워드: {len(matched)}개")

    policies = policies_by_name(config)

    print("\n📊 Estimate API 호출 중 (batch)...")
    estimates = _batch_estimate(client, matched, policies)
    print(f"   추정 입찰가 수신: {len(estimates)}개")

    name_width = max(len(kw.get("keyword", "")) for kw in matched)
    arrow_map = {"raise": "⬆", "lower": "⬇", "hold": "=", "skip": "·", "capped": "⚠"}

    print()
    success = 0
    skipped = 0
    failed = 0

    for idx, kw in enumerate(matched):
        if idx > 0:
            time.sleep(0.1)  # rate limit 완화

        kname = kw.get("keyword", "")
        policy = policies.get(kname)
        if not policy:
            continue

        current_bid = int(kw.get("bidAmt", 0))
        estimated_bid = estimates.get(kname)

        if estimated_bid is None:
            log_decision(
                mode="dry" if not live else "live",
                keyword_id=kw.get("nccKeywordId"),
                keyword_name=kname,
                adgroup_id=kw.get("nccAdgroupId"),
                current_bid=current_bid,
                target_rank=policy.target_rank,
                new_bid=current_bid,
                action="skip",
                reason="estimate 없음",
            )
            print(f"  {kname:<{name_width}}  현재 {current_bid:>6,}원  · skip (estimate 없음)")
            skipped += 1
            continue

        decision = decide(
            current_bid=current_bid,
            target_rank=policy.target_rank,
            min_bid=policy.min_bid,
            max_bid=policy.max_bid,
            step=policy.step,
            estimated_bid=estimated_bid,
        )

        arrow = arrow_map[decision.action]
        prefix = "  "
        line = (
            f"{prefix}{kname:<{name_width}}  "
            f"현재 {current_bid:>6,}원 → 목표 {policy.target_rank}  "
            f"추정 {estimated_bid:>6,}원  "
            f"새 입찰 {decision.new_bid:>6,}원  {arrow} {decision.action}"
        )

        # live 모드면 실제 PUT
        if live and decision.action in ("raise", "lower"):
            try:
                client.update_keyword_bid(kw, decision.new_bid)
                line += "  ✅"
                success += 1
            except NaverApiError as e:
                line += f"  ❌ ({e.status_code})"
                failed += 1
                log_decision(
                    mode="live",
                    keyword_id=kw.get("nccKeywordId"),
                    keyword_name=kname,
                    adgroup_id=kw.get("nccAdgroupId"),
                    current_bid=current_bid,
                    target_rank=policy.target_rank,
                    estimated_bid=estimated_bid,
                    new_bid=current_bid,
                    action="error",
                    reason=f"PUT 실패: {e.status_code}",
                )
                print(line)
                continue
        else:
            success += 1

        print(line)
        log_decision(
            mode="live" if live else "dry",
            keyword_id=kw.get("nccKeywordId"),
            keyword_name=kname,
            adgroup_id=kw.get("nccAdgroupId"),
            current_bid=current_bid,
            target_rank=policy.target_rank,
            estimated_bid=estimated_bid,
            new_bid=decision.new_bid,
            action=decision.action,
            reason=decision.reason,
        )

    print()
    print(f"✅ 처리 {success}건 / 스킵 {skipped}건 / 실패 {failed}건")
    if not live:
        print("   → 결과가 만족스러우면: python -m powerlink_pilot run --live")
    print("   기록 보기: python -m powerlink_pilot history")
    return 0 if failed == 0 else 1
