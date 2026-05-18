"""입찰 결정 로직.

샘플 모드(시뮬레이션 순위 기반)와 실 모드(네이버 estimate 기반) 둘 다 처리한다.
공통 원리: 한 번에 step 만큼만 이동, min_bid~max_bid 안에 클램프.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BidDecision:
    new_bid: int
    action: str  # 'raise' / 'lower' / 'hold' / 'skip'
    reason: str
    estimated_bid: Optional[int] = None


def decide(
    *,
    current_bid: int,
    target_rank: int,
    min_bid: int,
    max_bid: int,
    step: int,
    estimated_bid: Optional[int] = None,
    current_rank: Optional[int] = None,
) -> BidDecision:
    """current_rank(샘플) 또는 estimated_bid(실 모드) 중 하나로 결정한다."""
    if current_rank is not None:
        return _decide_from_rank(
            current_bid=current_bid,
            current_rank=current_rank,
            target_rank=target_rank,
            min_bid=min_bid,
            max_bid=max_bid,
            step=step,
        )

    if estimated_bid is not None:
        return _decide_from_estimate(
            current_bid=current_bid,
            estimated_bid=estimated_bid,
            target_rank=target_rank,
            min_bid=min_bid,
            max_bid=max_bid,
            step=step,
        )

    return BidDecision(
        new_bid=current_bid,
        action="skip",
        reason="신호 없음 (current_rank/estimated_bid 모두 None)",
    )


def _decide_from_rank(
    *,
    current_bid: int,
    current_rank: int,
    target_rank: int,
    min_bid: int,
    max_bid: int,
    step: int,
) -> BidDecision:
    if current_rank > target_rank:
        new_bid = min(current_bid + step, max_bid)
        action = "capped" if new_bid == current_bid else "raise"
    elif current_rank < target_rank:
        new_bid = max(current_bid - step, min_bid)
        action = "capped" if new_bid == current_bid else "lower"
    else:
        new_bid = current_bid
        action = "hold"

    if action == "capped":
        if current_rank > target_rank:
            reason = f"순위 {current_rank}→목표 {target_rank}, max_bid 도달 (목표 미달)"
        else:
            reason = f"순위 {current_rank}→목표 {target_rank}, min_bid 도달"
    else:
        reason = f"현재 순위 {current_rank} vs 목표 {target_rank}"
    return BidDecision(new_bid=new_bid, action=action, reason=reason)


def _decide_from_estimate(
    *,
    current_bid: int,
    estimated_bid: int,
    target_rank: int,
    min_bid: int,
    max_bid: int,
    step: int,
) -> BidDecision:
    if estimated_bid > current_bid:
        new_bid = min(current_bid + step, max_bid, estimated_bid)
        action = "capped" if new_bid == current_bid else "raise"
    elif estimated_bid < current_bid:
        new_bid = max(current_bid - step, min_bid, estimated_bid)
        action = "capped" if new_bid == current_bid else "lower"
    else:
        new_bid = current_bid
        action = "hold"

    if action == "capped":
        bound = "max_bid" if estimated_bid > current_bid else "min_bid"
        reason = f"순위 {target_rank} 추정 {estimated_bid:,}원, {bound} 도달"
    else:
        reason = f"순위 {target_rank} 추정 입찰가 {estimated_bid:,}원"
    return BidDecision(
        new_bid=new_bid,
        action=action,
        reason=reason,
        estimated_bid=estimated_bid,
    )
