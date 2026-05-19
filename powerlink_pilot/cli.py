"""CLI — argparse 기반 명령 디스패치."""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from . import __version__
from .db import init_db, recent_decisions, reset_db


# ─── command implementations ───────────────────────────────────────────


def cmd_setup(args: argparse.Namespace) -> int:
    from .wizard import run_setup

    return run_setup()


def cmd_run(args: argparse.Namespace) -> int:
    init_db()

    # mutually exclusive: --sample / --dry-run / --live
    modes = [args.sample, args.dry_run, args.live]
    if sum(bool(m) for m in modes) != 1:
        print("❌ 모드를 하나만 지정하세요: --sample / --dry-run / --live")
        return 1

    if args.sample:
        from .sample import run_sample

        config_path: Path | None = Path(args.config) if args.config else None
        if config_path is not None and not config_path.exists():
            print(f"❌ 설정 파일을 찾을 수 없습니다: {config_path}")
            return 1
        try:
            run_sample(config_path)
        except (ValueError, FileNotFoundError) as e:
            print(f"❌ 설정 오류: {e}")
            return 1
        return 0

    # dry-run / live → 실 모드
    from .live import run as run_live

    yaml_path = Path(args.config) if args.config else Path("keywords.yaml")
    try:
        return run_live(live=args.live, yaml_path=yaml_path, skip_confirm=args.yes)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return 1
    except ValueError as e:
        print(f"❌ {e}")
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    from .config import require_credentials
    from .naver import NaverAdsClient, NaverApiError

    try:
        creds = require_credentials()
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    client = NaverAdsClient(creds)

    if args.target == "adgroups":
        try:
            adgroups = client.list_all_adgroups()
        except NaverApiError as e:
            print(f"❌ {e}")
            return 1
        if not adgroups:
            print("광고그룹이 없습니다.")
            return 0
        print(f"\n광고그룹 {len(adgroups)}개:\n")
        for g in adgroups:
            camp = g.get("_campaign_name", "")
            print(f"  - {g.get('name', ''):<30}  {g.get('nccAdgroupId', '')}  ({camp})")
        return 0

    if args.target == "keywords":
        from .config import load_config

        try:
            config = load_config()
        except (FileNotFoundError, ValueError) as e:
            print(f"❌ {e}")
            return 1
        if not config.adgroups:
            print("yaml 에 adgroups 가 없습니다. 먼저 setup 을 실행하세요.")
            return 1
        for ag in config.adgroups:
            try:
                kws = client.list_keywords(ag.id)
            except NaverApiError as e:
                print(f"⚠️  '{ag.id}' 조회 실패: {e}")
                continue
            label = ag.name or ag.id
            print(f"\n[{label}] 키워드 {len(kws)}개:")
            for kw in kws:
                print(
                    f"  {kw.get('keyword', ''):<30}  "
                    f"입찰가 {kw.get('bidAmt', 0):>6,}원  "
                    f"id={kw.get('nccKeywordId', '')}"
                )
        return 0

    print(f"❌ 알 수 없는 대상: {args.target}")
    return 1


def _validate_value(field: str, value: int) -> int:
    if field == "target_rank":
        if not 1 <= value <= 10:
            raise ValueError(f"target_rank 는 1~10 범위여야 합니다 (입력: {value})")
    elif field in ("max_bid", "min_bid"):
        if value < 70:
            raise ValueError(f"{field} 는 70원 이상이어야 합니다 (네이버 최저)")
    elif field == "step":
        if value <= 0:
            raise ValueError(f"step 은 양수여야 합니다 (입력: {value})")
    return value


def cmd_set(args: argparse.Namespace) -> int:
    from .config import (
        CONFIG_PATH_DEFAULT,
        KeywordPolicy,
        load_config,
        write_config,
    )

    # mutex: --reset 와 값 플래그 동시 불가
    has_values = any(
        v is not None for v in (args.target_rank, args.max_bid, args.min_bid, args.step)
    )
    if args.reset and has_values:
        print("❌ --reset 과 값 옵션은 동시에 사용할 수 없습니다")
        return 1
    if not args.reset and not has_values:
        print("❌ 변경할 값이 없습니다. --target-rank/--max-bid/--min-bid/--step 또는 --reset 사용")
        return 1
    if args.keyword and args.match:
        print("❌ 키워드 이름과 --match 는 동시에 사용할 수 없습니다")
        return 1
    if not args.keyword and not args.match:
        print("❌ 키워드 이름 또는 --match SUBSTR 가 필요합니다")
        return 1

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return 1

    # 매칭 대상 결정
    if args.keyword:
        targets = [k for k in config.keywords if k.name == args.keyword]
        if not targets:
            print(f"❌ '{args.keyword}' 가 keywords.yaml 에 없습니다.")
            all_names = [k.name for k in config.keywords]
            suggestions = difflib.get_close_matches(args.keyword, all_names, n=3, cutoff=0.5)
            if suggestions:
                print("   비슷한 이름:")
                for s in suggestions:
                    print(f"     - {s}")
            return 1
    else:
        substr = args.match
        targets = [k for k in config.keywords if substr in k.name]
        if not targets:
            print(f"❌ '{substr}' 를 포함하는 키워드가 없습니다")
            return 1
        print(f"매칭된 키워드 {len(targets)}개:")
        for k in targets:
            print(f"   - {k.name}")
        confirm = input("이 키워드들에 변경을 적용하시겠습니까? (y/N): ").strip().lower()
        if confirm != "y":
            print("취소되었습니다.")
            return 0

    # 변경 적용
    d = config.defaults
    changes = []
    try:
        for kw in targets:
            if args.reset:
                kw.target_rank = d.target_rank
                kw.max_bid = d.max_bid
                kw.min_bid = d.min_bid
                kw.step = d.step
                changes.append(f"   {kw.name}: 모든 override 제거 → defaults 사용")
            else:
                parts = []
                if args.target_rank is not None:
                    v = _validate_value("target_rank", args.target_rank)
                    kw.target_rank = v
                    parts.append(f"target_rank={v}")
                if args.max_bid is not None:
                    v = _validate_value("max_bid", args.max_bid)
                    kw.max_bid = v
                    parts.append(f"max_bid={v:,}")
                if args.min_bid is not None:
                    v = _validate_value("min_bid", args.min_bid)
                    kw.min_bid = v
                    parts.append(f"min_bid={v:,}")
                if args.step is not None:
                    v = _validate_value("step", args.step)
                    kw.step = v
                    parts.append(f"step={v}")
                if kw.min_bid >= kw.max_bid:
                    print(f"❌ {kw.name}: min_bid({kw.min_bid}) 가 max_bid({kw.max_bid}) 이상")
                    return 1
                changes.append(f"   {kw.name}: {', '.join(parts)}")
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    write_config(CONFIG_PATH_DEFAULT, config)
    print(f"✅ {len(targets)}개 키워드 업데이트:")
    for c in changes[:10]:
        print(c)
    if len(changes) > 10:
        print(f"   ... (+{len(changes) - 10}개)")
    return 0


def cmd_set_defaults(args: argparse.Namespace) -> int:
    from .config import CONFIG_PATH_DEFAULT, load_config, write_config

    has_values = any(
        v is not None for v in (args.target_rank, args.max_bid, args.min_bid, args.step)
    )
    if not has_values:
        print("❌ 변경할 값이 없습니다")
        return 1

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return 1

    d = config.defaults
    parts = []
    try:
        if args.target_rank is not None:
            d.target_rank = _validate_value("target_rank", args.target_rank)
            parts.append(f"target_rank={d.target_rank}")
        if args.max_bid is not None:
            d.max_bid = _validate_value("max_bid", args.max_bid)
            parts.append(f"max_bid={d.max_bid:,}")
        if args.min_bid is not None:
            d.min_bid = _validate_value("min_bid", args.min_bid)
            parts.append(f"min_bid={d.min_bid:,}")
        if args.step is not None:
            d.step = _validate_value("step", args.step)
            parts.append(f"step={d.step}")
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    if d.min_bid >= d.max_bid:
        print(f"❌ defaults.min_bid({d.min_bid}) 가 max_bid({d.max_bid}) 이상")
        return 1

    write_config(CONFIG_PATH_DEFAULT, config)
    print(f"✅ defaults 업데이트: {', '.join(parts)}")
    print("   변경 후 일부 키워드의 override 가 defaults 와 같아져 자동 정리될 수 있습니다.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    from .config import load_config

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        return 1

    d = config.defaults

    if args.keyword:
        match = [k for k in config.keywords if k.name == args.keyword]
        if not match:
            all_names = [k.name for k in config.keywords]
            suggestions = difflib.get_close_matches(args.keyword, all_names, n=3, cutoff=0.5)
            print(f"❌ '{args.keyword}' 가 keywords.yaml 에 없습니다.")
            if suggestions:
                print("   비슷한 이름:", ", ".join(suggestions))
            return 1
        kw = match[0]
        print(f"\n키워드: {kw.name}")
        for fname, kval, dval in [
            ("target_rank", kw.target_rank, d.target_rank),
            ("max_bid", kw.max_bid, d.max_bid),
            ("min_bid", kw.min_bid, d.min_bid),
            ("step", kw.step, d.step),
        ]:
            label = "override" if kval != dval else "default"
            display = f"{kval:,}" if fname != "target_rank" else str(kval)
            print(f"  {fname:<12} {display:>10}  ({label})")
        return 0

    # 전체 표
    print(f"\ndefaults:")
    print(
        f"   target_rank={d.target_rank}  max_bid={d.max_bid:,}  "
        f"min_bid={d.min_bid:,}  step={d.step:,}"
    )
    print(f"\n키워드 {len(config.keywords)}개:")
    print("-" * 80)
    print(f"{'이름':<22}{'target':>8}{'max_bid':>10}{'min_bid':>10}{'step':>8}  override")
    print("-" * 80)
    for kw in config.keywords:
        diffs = []
        if kw.target_rank != d.target_rank:
            diffs.append("target")
        if kw.max_bid != d.max_bid:
            diffs.append("max")
        if kw.min_bid != d.min_bid:
            diffs.append("min")
        if kw.step != d.step:
            diffs.append("step")
        marker = ",".join(diffs) if diffs else "—"
        print(
            f"{kw.name:<22}{kw.target_rank:>8}{kw.max_bid:>10,}"
            f"{kw.min_bid:>10,}{kw.step:>8,}  {marker}"
        )
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    init_db()

    if args.reset:
        confirm = input("정말 모든 기록을 삭제하시겠습니까? (y/N): ").strip().lower()
        if confirm != "y":
            print("취소되었습니다.")
            return 0
        reset_db()
        print("✅ 기록이 초기화되었습니다.")
        return 0

    rows = recent_decisions(limit=args.limit, mode=args.mode)
    if not rows:
        print("기록이 없습니다. `run --sample` 또는 `run --dry-run` 으로 시작해보세요.")
        return 0

    title_extra = f" (mode={args.mode})" if args.mode else ""
    print(f"\n📋 최근 결정 {len(rows)}건{title_extra}")
    print("-" * 96)
    print(
        f"{'시각':<13}{'모드':<8}{'키워드':<20}"
        f"{'현재':>9}{'→':^4}{'새 입찰':>9}{'액션':>8}  설명"
    )
    print("-" * 96)
    for r in rows:
        ts = r["ts"][5:16]  # MM-DDTHH:MM
        cb = f"{r['current_bid']:,}" if r["current_bid"] is not None else "-"
        nb = f"{r['new_bid']:,}" if r["new_bid"] is not None else "-"
        print(
            f"{ts:<13}{r['mode']:<8}{r['keyword_name']:<20}"
            f"{cb:>9}{'→':^4}{nb:>9}{r['action']:>8}  {r['reason'] or ''}"
        )
    return 0


# ─── fetch-stats command ──────────────────────────────────────────────


def cmd_fetch_stats(args: argparse.Namespace) -> int:
    """네이버 stat-reports 비동기 보고서 다운로드 → DB 저장."""
    init_db()

    from .config import require_credentials
    from .naver import NaverAdsClient
    from .reports import fetch_search_query_report, fetch_hourly_report, last_n_days
    from .db import save_search_queries, save_hourly_stats

    try:
        creds = require_credentials()
    except ValueError as e:
        print(f"❌ {e}")
        return 1

    client = NaverAdsClient(creds)
    dates = last_n_days(args.days)
    print(f"📅 기간: {dates[-1]} ~ {dates[0]} ({args.days}일)")

    types: list[str] = []
    if args.type in ("search", "all"):
        types.append("search")
    if args.type in ("hourly", "all"):
        types.append("hourly")

    def progress(msg: str) -> None:
        print(msg)

    total_days = len(dates)
    overall_ok = True

    if "search" in types:
        print()
        print("━━━ 검색어 보고서 (AD_DETAIL) ━━━")
        rows = fetch_search_query_report(client, dates, progress=progress)
        got_dates = {r.stat_date for r in rows}
        missing = total_days - len(got_dates)
        if rows:
            n = save_search_queries(rows)
            print(f"💾 저장: {n}행 — 데이터 받은 일자 {len(got_dates)}/{total_days}일"
                  + (f", 빈 데이터 {missing}일" if missing else ""))
        else:
            print(f"⚠️  검색어 데이터 0건 — 요청한 {total_days}일 모두 빈 데이터")
            print("    원인 후보: 광고 노출이 적거나, 광고 안 돌아간 기간")
            overall_ok = False

    if "hourly" in types:
        print()
        print("━━━ 시간대 보고서 (TIME) ━━━")
        rows = fetch_hourly_report(client, dates, progress=progress)
        got_dates = {r.stat_date for r in rows}
        missing = total_days - len(got_dates)
        if rows:
            n = save_hourly_stats(rows)
            print(f"💾 저장: {n}행 — 데이터 받은 일자 {len(got_dates)}/{total_days}일"
                  + (f", 빈 데이터 {missing}일" if missing else ""))
        else:
            print(f"⚠️  시간대 데이터 0건 — 요청한 {total_days}일 모두 빈 데이터")
            overall_ok = False

    print()
    if overall_ok:
        print("✅ 완료. 다음 단계:")
        print("   python -m powerlink_pilot analyze        # 검색어 분석")
    else:
        print("⚠️  일부 또는 전체 데이터를 받지 못했습니다.")
        print("   - 광고가 돌아간 기간이 짧으면 --days 30 으로 늘려서 재시도")
        print("   - 그래도 빈 데이터면 광고 노출이 너무 적은 상태")
    return 0 if overall_ok else 1


# ─── analyze command ──────────────────────────────────────────────────


def cmd_analyze(args: argparse.Namespace) -> int:
    """검색어 데이터 분석 → 비효율 검색어 추천 → (선택) 등록."""
    init_db()

    from .analyzer import (
        AnalyzeThresholds,
        analyze_queries,
        format_recommendations_korean,
        generate_sample_queries,
    )

    # yaml 에 analyze 섹션 있으면 사장님 설정 반영, 없으면 기본값
    thresholds = AnalyzeThresholds()
    used_yaml_overrides = False
    if not args.sample:
        try:
            from .config import load_config, get_analyze_thresholds

            cfg = load_config()
            if cfg.analyze_overrides:
                thresholds = get_analyze_thresholds(cfg)
                used_yaml_overrides = True
        except (FileNotFoundError, ValueError):
            pass  # yaml 없거나 형식 문제면 기본값 사용

    if used_yaml_overrides:
        print(f"⚙️  keywords.yaml 의 analyze 임계치 적용 (필드 {len(cfg.analyze_overrides)}개)")
    elif not args.sample:
        print("⚙️  분석 임계치 기본값 사용")
        print("   조정하시려면 keywords.yaml 에 analyze: 섹션 추가 (examples 참고)")

    # 데이터 소스 결정
    if args.sample:
        print("🎬 sample 모드 — 합성 데이터로 데모")
        rows = generate_sample_queries()
    else:
        from .db import get_search_queries

        rows = get_search_queries(
            since_date=args.since,
            until_date=args.until,
            adgroup_id=args.adgroup,
        )
        if not rows:
            print("⚠️  분석할 검색어 데이터가 없습니다.")
            print("   먼저 데이터를 받아야 합니다:")
            print("     python -m powerlink_pilot fetch-stats")
            return 1

    print(f"📊 분석 대상: {len(rows)}행")
    recs = analyze_queries(rows, thresholds=thresholds)

    print()
    print(format_recommendations_korean(recs))

    if not recs:
        return 0

    # apply 모드
    if args.apply:
        if args.sample:
            print()
            print("⚠️  sample 모드에서는 실제 API 호출하지 않습니다.")
            return 0

        from .config import require_credentials
        from .naver import NaverAdsClient
        from .negative_kw import (
            build_plans,
            format_plans_korean,
            format_results_korean,
            register_plans,
        )

        try:
            creds = require_credentials()
        except ValueError as e:
            print(f"❌ {e}")
            return 1

        client = NaverAdsClient(creds)
        print()
        print("📡 기존 부정 키워드 조회 중 (중복 방지)...")
        plans = build_plans(client, recs)

        print()
        print(format_plans_korean(plans))

        if not any(p.new_queries for p in plans):
            print("등록할 신규 부정 키워드가 없어요.")
            return 0

        if not args.yes:
            confirm = input("\n정말로 등록하시겠어요? (y/N): ").strip().lower()
            if confirm != "y":
                print("취소되었습니다.")
                return 0

        print()
        results = register_plans(client, plans, dry_run=False, progress=lambda m: print("  " + m))
        print()
        print(format_results_korean(results))
        return 0

    print()
    print("→ 등록하시려면: python -m powerlink_pilot analyze --apply")
    return 0


# ─── parser ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="powerlink-pilot",
        description="네이버 검색광고 자동입찰 오픈소스 도구",
    )
    parser.add_argument(
        "--version", action="version", version=f"powerlink-pilot {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    p_setup = subparsers.add_parser("setup", help="대화형 셋업 (.env + keywords.yaml 생성)")
    p_setup.set_defaults(func=cmd_setup)

    # run
    p_run = subparsers.add_parser("run", help="입찰 자동화 실행")
    p_run.add_argument("--sample", action="store_true", help="샘플 모드 (API 키 불필요)")
    p_run.add_argument("--dry-run", dest="dry_run", action="store_true", help="실 API 조회, 입찰 변경 X")
    p_run.add_argument("--live", action="store_true", help="실제 입찰 변경")
    p_run.add_argument(
        "--config",
        metavar="FILE",
        help="keywords.yaml 경로 (기본: keywords.yaml 또는 내장 샘플)",
    )
    p_run.add_argument(
        "--yes", action="store_true", help="--live 확인 프롬프트 스킵 (자동화 환경용)"
    )
    p_run.set_defaults(func=cmd_run)

    # list
    p_list = subparsers.add_parser("list", help="광고그룹 / 키워드 조회")
    p_list.add_argument("target", choices=["adgroups", "keywords"], help="조회 대상")
    p_list.set_defaults(func=cmd_list)

    # set
    p_set = subparsers.add_parser("set", help="키워드 정책 변경 (yaml 수정, API 호출 X)")
    p_set.add_argument("keyword", nargs="?", help="키워드 이름")
    p_set.add_argument("--match", metavar="SUBSTR", help="이름 부분 일치로 일괄 적용")
    p_set.add_argument("--target-rank", dest="target_rank", type=int)
    p_set.add_argument("--max-bid", dest="max_bid", type=int)
    p_set.add_argument("--min-bid", dest="min_bid", type=int)
    p_set.add_argument("--step", type=int)
    p_set.add_argument(
        "--reset", action="store_true", help="모든 override 제거 → defaults 사용"
    )
    p_set.set_defaults(func=cmd_set)

    # set-defaults
    p_def = subparsers.add_parser("set-defaults", help="defaults 값 변경")
    p_def.add_argument("--target-rank", dest="target_rank", type=int)
    p_def.add_argument("--max-bid", dest="max_bid", type=int)
    p_def.add_argument("--min-bid", dest="min_bid", type=int)
    p_def.add_argument("--step", type=int)
    p_def.set_defaults(func=cmd_set_defaults)

    # show
    p_show = subparsers.add_parser("show", help="현재 정책 표시")
    p_show.add_argument("keyword", nargs="?", help="특정 키워드 (생략 시 전체 표)")
    p_show.set_defaults(func=cmd_show)

    # history
    p_hist = subparsers.add_parser("history", help="최근 결정 이력")
    p_hist.add_argument("--limit", type=int, default=20, help="표시 개수 (기본: 20)")
    p_hist.add_argument(
        "--mode", choices=["sample", "dry", "live"], help="모드 필터"
    )
    p_hist.add_argument("--reset", action="store_true", help="모든 기록 삭제")
    p_hist.set_defaults(func=cmd_history)

    # fetch-stats
    p_fetch = subparsers.add_parser(
        "fetch-stats",
        help="네이버 광고 데이터 받아오기 (비동기 보고서, 수십초~수분 소요)",
    )
    p_fetch.add_argument(
        "--days", type=int, default=7,
        help="지난 N일 데이터 (기본: 7)",
    )
    p_fetch.add_argument(
        "--type", choices=["search", "hourly", "all"], default="search",
        help="search=검색어 / hourly=시간대 / all=둘 다",
    )
    p_fetch.set_defaults(func=cmd_fetch_stats)

    # analyze
    p_an = subparsers.add_parser(
        "analyze",
        help="저장된 데이터로 비효율 검색어 분석 + 부정 키워드 추천",
    )
    p_an.add_argument("--sample", action="store_true", help="데모 — 합성 데이터로 시연")
    p_an.add_argument("--apply", action="store_true", help="추천을 실제 부정 키워드로 등록")
    p_an.add_argument("--yes", action="store_true", help="--apply 확인 프롬프트 스킵")
    p_an.add_argument("--since", metavar="YYYY-MM-DD", help="분석 시작 일자")
    p_an.add_argument("--until", metavar="YYYY-MM-DD", help="분석 종료 일자")
    p_an.add_argument("--adgroup", metavar="ID", help="특정 광고그룹만")
    p_an.set_defaults(func=cmd_analyze)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
