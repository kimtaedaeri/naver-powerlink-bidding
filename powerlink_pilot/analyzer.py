"""검색어 분석 룰 — 비효율 검색어 후보 추천.

DB에 저장된 search_queries 데이터에 3가지 룰을 적용해 추천 리스트를 만든다.
모든 처리는 in-memory + 표준 라이브러리만 (pandas/numpy X).

룰:
  R1. 노출 임계치 이상 + 클릭 0회 → "no_clicks" (가장 강력한 신호)
  R2. 클릭 임계치 이상 + 전환 0회 → "no_conversion" (전환 추적 있을 때만)
  R3. CTR 이 광고그룹 평균의 ratio 미만 → "low_ctr" (보조 신호)
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Optional


# ─── 임계치 ──────────────────────────────────────────────────────────────


@dataclass
class AnalyzeThresholds:
    """사장님이 yaml 로 조정 가능한 임계치들. 기본값은 1인 사업자 평균 기준."""

    # R1: 노출 N+ 클릭 0
    no_clicks_min_impressions: int = 50

    # R2: 클릭 N+ 전환 0
    no_conversion_min_clicks: int = 5

    # R3: CTR < 평균 × ratio
    low_ctr_min_impressions: int = 30
    low_ctr_ratio_vs_avg: float = 0.3

    # 공통
    exclude_own_keywords: bool = True  # 등록 키워드와 동일한 검색어는 제외 (자기 광고)


@dataclass
class Recommendation:
    """비효율 검색어 추천 1건."""

    query: str
    rule: str  # "no_clicks" / "no_conversion" / "low_ctr"
    severity: int  # 1 (낮음) ~ 3 (높음)
    reason: str
    adgroup_id: Optional[str]
    impressions: int
    clicks: int
    cost: int
    ctr: float

    def to_dict(self) -> dict:
        return asdict(self)


# ─── 룰 적용 ────────────────────────────────────────────────────────────


def _aggregate_by_query(rows: list[dict]) -> dict[tuple, dict]:
    """동일 (adgroup_id, query) 행을 합쳐 노출·클릭·비용 누계."""
    agg: dict[tuple, dict] = {}
    for r in rows:
        key = (r.get("adgroup_id"), r.get("query") or "")
        if not key[1]:
            continue
        slot = agg.setdefault(
            key,
            {
                "adgroup_id": key[0],
                "query": key[1],
                "keyword": r.get("keyword"),
                "impressions": 0,
                "clicks": 0,
                "cost": 0,
                "conversions": 0,
                "has_conversion_data": False,
            },
        )
        slot["impressions"] += r.get("impressions", 0) or 0
        slot["clicks"] += r.get("clicks", 0) or 0
        slot["cost"] += r.get("cost", 0) or 0
        c = r.get("conversions")
        if c is not None:
            slot["has_conversion_data"] = True
            slot["conversions"] += c
    return agg


def _avg_ctr_by_adgroup(agg: dict[tuple, dict]) -> dict[str, float]:
    """광고그룹별 평균 CTR (전체 노출·클릭 합계 기반)."""
    by_ag: dict[str, list[int]] = {}
    for v in agg.values():
        ag = v["adgroup_id"] or ""
        b = by_ag.setdefault(ag, [0, 0])
        b[0] += v["impressions"]
        b[1] += v["clicks"]
    return {ag: (clk / imp if imp > 0 else 0.0) for ag, (imp, clk) in by_ag.items()}


def analyze_queries(
    rows: list[dict],
    thresholds: Optional[AnalyzeThresholds] = None,
) -> list[Recommendation]:
    """검색어 데이터를 분석해 비효율 검색어 후보 리스트를 반환.

    rows: db.get_search_queries() 의 결과 (dict 리스트)
    """
    t = thresholds or AnalyzeThresholds()

    agg = _aggregate_by_query(rows)
    avg_ctr_by_ag = _avg_ctr_by_adgroup(agg)

    recs: list[Recommendation] = []

    for (ag_id, query), data in agg.items():
        # 자기 키워드 자체는 부정 후보 X
        if t.exclude_own_keywords and data.get("keyword") and data["keyword"].strip() == query.strip():
            continue

        imp = data["impressions"]
        clk = data["clicks"]
        cost = data["cost"]
        ctr = (clk / imp) if imp > 0 else 0.0
        conv = data["conversions"]
        has_conv = data["has_conversion_data"]

        # R1. no_clicks
        if imp >= t.no_clicks_min_impressions and clk == 0:
            recs.append(
                Recommendation(
                    query=query,
                    rule="no_clicks",
                    severity=3,
                    reason=f"노출 {imp:,}회 / 클릭 0회 — 광고비만 새고 효과 없음",
                    adgroup_id=ag_id,
                    impressions=imp,
                    clicks=clk,
                    cost=cost,
                    ctr=ctr,
                )
            )
            continue  # 가장 강한 신호로 1회만 추천

        # R2. no_conversion (전환 추적 데이터 있을 때만)
        if has_conv and clk >= t.no_conversion_min_clicks and conv == 0:
            recs.append(
                Recommendation(
                    query=query,
                    rule="no_conversion",
                    severity=2,
                    reason=f"클릭 {clk}회 / 전환 0건 — 사장님 사업과 안 맞는 검색어",
                    adgroup_id=ag_id,
                    impressions=imp,
                    clicks=clk,
                    cost=cost,
                    ctr=ctr,
                )
            )
            continue

        # R3. low_ctr
        if imp >= t.low_ctr_min_impressions:
            avg_ctr = avg_ctr_by_ag.get(ag_id or "", 0.0)
            if avg_ctr > 0 and ctr < avg_ctr * t.low_ctr_ratio_vs_avg:
                pct_avg = (ctr / avg_ctr) * 100 if avg_ctr else 0
                recs.append(
                    Recommendation(
                        query=query,
                        rule="low_ctr",
                        severity=1,
                        reason=f"CTR {ctr*100:.2f}% — 광고그룹 평균의 {pct_avg:.0f}% 수준",
                        adgroup_id=ag_id,
                        impressions=imp,
                        clicks=clk,
                        cost=cost,
                        ctr=ctr,
                    )
                )

    # severity desc, cost desc 정렬 (강한 신호 + 광고비 큰 것 먼저)
    recs.sort(key=lambda r: (-r.severity, -r.cost, -r.impressions))
    return recs


# ─── 데모 모드 (영상 시연용 합성 데이터) ────────────────────────────────


def generate_sample_queries() -> list[dict]:
    """영상 시연용 — Naver 검색어 보고서를 흉내낸 가상 데이터.

    분포 의도:
      - 좋은 검색어: 노출 ↑ · 클릭 ↑ · CTR 평균
      - 비효율 검색어 (R1): 노출 ↑ · 클릭 0  ← 추천 대상
      - 비효율 검색어 (R3): CTR 매우 낮음    ← 추천 대상
    """
    rng = random.Random(42)  # 시연 재현성

    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    sample_ag = "demo-adgroup-001"

    # 정상 검색어들 (광고그룹 평균 형성)
    healthy = [
        ("토지담보대출", "토지담보대출", 320, 18, 27000),
        ("토지담보대출", "토지 담보 대출", 280, 14, 21000),
        ("아파트담보대출", "아파트담보대출", 410, 22, 32000),
        ("아파트담보대출", "아파트 담보대출 금리", 180, 11, 16500),
        ("상가담보대출", "상가담보대출", 240, 13, 19500),
    ]

    # 비효율 - R1 (노출 많은데 클릭 0)
    wasteful_r1 = [
        ("토지담보대출", "토지 대출 사기 후기", 87, 0, 0),
        ("토지담보대출", "토지대출 거절 사유", 64, 0, 0),
        ("아파트담보대출", "아파트 대출 깡 처벌", 92, 0, 0),
    ]

    # 비효율 - R3 (CTR 낮음)
    wasteful_r3 = [
        ("아파트담보대출", "아파트 대출 갈아타기 후기", 156, 1, 1300),
        ("상가담보대출", "상가 임대료 시세", 110, 1, 1200),
    ]

    rows: list[dict] = []
    for keyword, query, imp, clk, cost in healthy + wasteful_r1 + wasteful_r3:
        rows.append(
            {
                "stat_date": yesterday,
                "adgroup_id": sample_ag,
                "keyword_id": f"kid-{keyword}",
                "keyword": keyword,
                "query": query,
                "impressions": imp,
                "clicks": clk,
                "cost": cost,
                "ctr": (clk / imp) if imp else 0.0,
                "cpc": (cost // clk) if clk else 0,
                "conversions": None,
                "conv_value": None,
            }
        )
    rng.shuffle(rows)
    return rows


# ─── 사람 친화 출력 ────────────────────────────────────────────────────


def format_recommendations_korean(recs: list[Recommendation], max_show: int = 20) -> str:
    """사장님께 보여줄 한국어 요약."""
    if not recs:
        return "✅ 분석한 검색어에서 비효율 신호를 찾지 못했어요. (데이터가 더 쌓이면 더 정확해집니다)"

    severity_label = {3: "🔴 강함", 2: "🟡 중간", 1: "🟢 약함"}
    rule_label = {
        "no_clicks": "광고비 새는 검색어",
        "no_conversion": "클릭은 있지만 전환 없는 검색어",
        "low_ctr": "CTR 낮은 검색어",
    }

    lines: list[str] = []
    lines.append(f"💡 비효율 검색어 {len(recs)}개 발견")
    lines.append("")

    rule_groups: dict[str, list[Recommendation]] = {}
    for r in recs:
        rule_groups.setdefault(r.rule, []).append(r)

    for rule in ("no_clicks", "no_conversion", "low_ctr"):
        items = rule_groups.get(rule)
        if not items:
            continue
        lines.append(f"━━ {rule_label[rule]} ({len(items)}개) ━━")
        for r in items[:max_show]:
            lines.append(
                f"  {severity_label.get(r.severity, '')} {r.query}"
            )
            lines.append(f"     {r.reason}")
        if len(items) > max_show:
            lines.append(f"  ... 외 {len(items) - max_show}개")
        lines.append("")

    lines.append("부정 키워드로 등록하면 광고비 누수를 막을 수 있어요.")
    lines.append("등록하시려면: 'y' (또는 '등록해줘')")
    return "\n".join(lines)
