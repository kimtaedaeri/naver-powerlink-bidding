"""샘플 모드 — API 키 없이 가상 키워드로 입찰 자동화를 시뮬레이션한다."""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import KeywordPolicy, load_config
from .db import get_last_bid, log_decision
from .engine import decide


@dataclass
class SampleKeyword:
    name: str
    target_rank: int
    min_bid: int
    max_bid: int
    initial_bid: int
    pressure: float = 0.5
    step: int = 500


# 내장 샘플 — 설정 파일 없이도 즉시 시연 가능
BUILTIN_SAMPLES: list[SampleKeyword] = [
    SampleKeyword(
        name="키워드_쉬움",
        target_rank=3,
        min_bid=1000,
        max_bid=5000,
        initial_bid=2500,
        pressure=0.2,
    ),
    SampleKeyword(
        name="키워드_중간",
        target_rank=3,
        min_bid=2000,
        max_bid=8000,
        initial_bid=4000,
        pressure=0.5,
    ),
    SampleKeyword(
        name="키워드_경쟁심한",
        target_rank=2,
        min_bid=3000,
        max_bid=12000,
        initial_bid=5000,
        pressure=0.85,
        step=800,
    ),
]


def simulate_rank(bid: int, min_bid: int, max_bid: int, pressure: float) -> int:
    """입찰가가 받을 가상 순위. 입찰가 ↑ → 순위 좋아짐(낮은 숫자). pressure ↑ → 어려워짐."""
    span = max(max_bid - min_bid, 1)
    bid_norm = (bid - min_bid) / span
    bid_norm = max(0.0, min(1.0, bid_norm))
    base = 1 + (1 - bid_norm) * 9 + pressure * 3
    noise = random.uniform(-0.5, 0.5)
    return max(1, round(base + noise))


def _policy_to_sample(p: KeywordPolicy) -> SampleKeyword:
    return SampleKeyword(
        name=p.name,
        target_rank=p.target_rank,
        min_bid=p.min_bid,
        max_bid=p.max_bid,
        initial_bid=(p.min_bid + p.max_bid) // 2,
        pressure=0.5,  # 사용자 yaml 에선 노출 안 함, 중간값으로 합성
        step=p.step,
    )


def run_sample(yaml_path: Optional[Path] = None) -> int:
    """한 tick 의 샘플 시뮬레이션을 실행하고 결정을 DB 에 기록한다."""
    if yaml_path is not None:
        config = load_config(yaml_path)
        keywords = [_policy_to_sample(p) for p in config.keywords]
        source = f"설정 파일: {yaml_path}"
    else:
        keywords = BUILTIN_SAMPLES
        source = "내장 샘플 (3개)"

    print("🚀 powerlink-pilot — sample mode")
    print(f"📊 {source}")
    print()

    name_width = max(len(k.name) for k in keywords)
    arrow_map = {"raise": "⬆", "lower": "⬇", "hold": "=", "skip": "·", "capped": "⚠"}

    for kw in keywords:
        last_bid = get_last_bid(kw.name)
        current_bid = last_bid if last_bid is not None else kw.initial_bid
        current_rank = simulate_rank(current_bid, kw.min_bid, kw.max_bid, kw.pressure)

        decision = decide(
            current_bid=current_bid,
            target_rank=kw.target_rank,
            min_bid=kw.min_bid,
            max_bid=kw.max_bid,
            step=kw.step,
            current_rank=current_rank,
        )

        arrow = arrow_map[decision.action]
        print(
            f"  {kw.name:<{name_width}}  순위 {current_rank}  "
            f"입찰 {current_bid:>6,}원 → 목표 {kw.target_rank}  "
            f"새 입찰 {decision.new_bid:>6,}원  {arrow} {decision.action}"
        )

        log_decision(
            mode="sample",
            keyword_name=kw.name,
            current_bid=current_bid,
            target_rank=kw.target_rank,
            new_bid=decision.new_bid,
            action=decision.action,
            reason=decision.reason,
        )

    print()
    print(f"✅ {len(keywords)}건 기록됨")
    print("   다시 실행하면 이어집니다 (수렴 과정 확인)")
    print("   기록 보기: python -m powerlink_pilot history")
    return len(keywords)
