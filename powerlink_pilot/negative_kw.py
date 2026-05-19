"""부정 키워드 추천 → 사장님 확인 → API 등록.

흐름:
  1. analyzer 가 만든 Recommendation 리스트를 받음
  2. 광고그룹별로 그룹화 + 기존 부정 키워드와 차집합 (중복 등록 방지)
  3. 사장님께 미리보기 보여주고 y/N 확인
  4. y 면 API 호출 — 광고그룹별 일괄 등록

사장님이 명시적으로 y 라고 한 경우에만 실제 API 호출.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Optional

from .analyzer import Recommendation
from .naver import NaverAdsClient, NaverApiError


@dataclass
class RegistrationPlan:
    """광고그룹 1개에 등록할 부정 키워드 묶음."""

    adgroup_id: str
    new_queries: list[str]  # 신규로 등록할 검색어 (이미 있는 건 제외됨)
    skipped_existing: list[str]  # 이미 등록되어 있어 스킵된 검색어
    recs_by_query: dict[str, Recommendation]  # 표시용

    def to_summary(self) -> str:
        lines = [f"광고그룹 {self.adgroup_id}:"]
        lines.append(f"   - 등록 예정: {len(self.new_queries)}개")
        if self.skipped_existing:
            lines.append(f"   - 이미 등록됨 (스킵): {len(self.skipped_existing)}개")
        return "\n".join(lines)


@dataclass
class RegistrationResult:
    """등록 시도 결과."""

    adgroup_id: str
    registered: list[str]
    failed: list[tuple[str, str]]  # (query, error_msg)


# ─── 계획 단계 ─────────────────────────────────────────────────────────


def build_plans(
    client: NaverAdsClient,
    recs: list[Recommendation],
) -> list[RegistrationPlan]:
    """추천 리스트를 광고그룹별로 묶고, 기존 부정 키워드와 비교해 신규만 추림.

    같은 광고그룹에 같은 검색어가 여러 룰로 추천돼도 한 번만 등록.
    """
    # 광고그룹별로 그룹화
    by_ag: dict[str, list[Recommendation]] = defaultdict(list)
    for r in recs:
        if r.adgroup_id:
            by_ag[r.adgroup_id].append(r)

    plans: list[RegistrationPlan] = []
    for ag_id, items in by_ag.items():
        # 기존 부정 키워드 조회 (중복 등록 방지용)
        existing_raw: list[dict] = []
        fetch_failed = False
        try:
            existing_raw = client.list_restricted_keywords(ag_id)
        except NaverApiError as e:
            # 조회 실패 시 경고 출력 + 중복 등록 위험 알림
            fetch_failed = True
            print(
                f"   ⚠️  '{ag_id}' 기존 부정 키워드 조회 실패: {e}\n"
                f"      → 중복 등록 위험. 진행하시려면 그대로, 아니면 잠시 후 재시도 권장."
            )

        existing = {(kw.get("keyword") or "").strip().lower() for kw in existing_raw}

        # 검색어 dedupe (같은 query 중복 추천 합치기 — 가장 강한 severity 보존)
        seen: dict[str, Recommendation] = {}
        for r in items:
            q = (r.query or "").strip()
            if not q:
                continue
            if q not in seen or r.severity > seen[q].severity:
                seen[q] = r

        new_queries: list[str] = []
        skipped: list[str] = []
        for q, r in seen.items():
            if q.lower() in existing:
                skipped.append(q)
            else:
                new_queries.append(q)

        plans.append(
            RegistrationPlan(
                adgroup_id=ag_id,
                new_queries=new_queries,
                skipped_existing=skipped,
                recs_by_query=seen,
            )
        )

    return plans


# ─── 사장님 확인 + 등록 ──────────────────────────────────────────────


def format_plans_korean(plans: list[RegistrationPlan]) -> str:
    """등록 미리보기 (사장님 확인용)."""
    if not plans:
        return "등록할 부정 키워드가 없어요."

    total_new = sum(len(p.new_queries) for p in plans)
    total_skip = sum(len(p.skipped_existing) for p in plans)

    lines = []
    lines.append(f"📋 등록 미리보기 — 총 {total_new}개 신규 / 이미 등록 {total_skip}개")
    lines.append("")
    for p in plans:
        if not p.new_queries:
            continue
        lines.append(f"━━ 광고그룹 {p.adgroup_id} ━━")
        for q in p.new_queries[:20]:
            rec = p.recs_by_query.get(q)
            tag = rec.rule if rec else ""
            lines.append(f"   - {q}   ({tag})")
        if len(p.new_queries) > 20:
            lines.append(f"   ... 외 {len(p.new_queries) - 20}개")
        lines.append("")
    return "\n".join(lines)


def register_plans(
    client: NaverAdsClient,
    plans: list[RegistrationPlan],
    *,
    dry_run: bool = True,
    progress: Optional[Callable[[str], None]] = None,
) -> list[RegistrationResult]:
    """플랜에 따라 부정 키워드 등록. dry_run=True 면 시뮬레이션만.

    한 광고그룹씩 API 호출. 실패 시 다음 그룹은 계속 시도.
    """
    results: list[RegistrationResult] = []

    for plan in plans:
        if not plan.new_queries:
            continue

        if dry_run:
            results.append(
                RegistrationResult(
                    adgroup_id=plan.adgroup_id,
                    registered=plan.new_queries.copy(),  # 가상 등록
                    failed=[],
                )
            )
            if progress:
                progress(
                    f"[dry-run] {plan.adgroup_id}: {len(plan.new_queries)}개 등록 시뮬"
                )
            continue

        try:
            api_result = client.add_restricted_keywords(
                plan.adgroup_id,
                plan.new_queries,
            )
            registered_names = [
                (item.get("keyword") or "") for item in api_result
            ]
            registered = [q for q in plan.new_queries if q in registered_names]
            failed: list[tuple[str, str]] = []
            # API 가 일부만 성공한 경우 (드물지만 대비)
            missing = set(plan.new_queries) - set(registered_names)
            for m in missing:
                failed.append((m, "API 응답에 누락 — 재시도 권장"))

            results.append(
                RegistrationResult(
                    adgroup_id=plan.adgroup_id,
                    registered=registered,
                    failed=failed,
                )
            )
            if progress:
                progress(
                    f"✅ {plan.adgroup_id}: 등록 {len(registered)}개 / 실패 {len(failed)}개"
                )

        except NaverApiError as e:
            # 전부 실패 처리
            results.append(
                RegistrationResult(
                    adgroup_id=plan.adgroup_id,
                    registered=[],
                    failed=[(q, str(e)) for q in plan.new_queries],
                )
            )
            if progress:
                progress(
                    f"❌ {plan.adgroup_id}: 등록 실패 ({e})"
                )

    return results


def format_results_korean(results: list[RegistrationResult]) -> str:
    """등록 결과 요약."""
    total_ok = sum(len(r.registered) for r in results)
    total_fail = sum(len(r.failed) for r in results)

    lines = []
    if total_fail == 0 and total_ok > 0:
        lines.append(f"✅ {total_ok}개 부정 키워드 등록 완료")
    elif total_ok > 0:
        lines.append(f"⚠️ 등록 {total_ok}개 / 실패 {total_fail}개")
    elif total_fail > 0:
        lines.append(f"❌ 등록 실패: {total_fail}개")
    else:
        lines.append("등록된 항목이 없습니다")

    for r in results:
        if r.registered:
            lines.append(f"   [{r.adgroup_id}] 등록: {', '.join(r.registered[:5])}"
                         + (f" 외 {len(r.registered) - 5}개" if len(r.registered) > 5 else ""))
        if r.failed:
            lines.append(f"   [{r.adgroup_id}] 실패:")
            for q, msg in r.failed[:3]:
                lines.append(f"      - {q}: {msg}")

    return "\n".join(lines)
