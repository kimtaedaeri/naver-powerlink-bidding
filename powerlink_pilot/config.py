"""설정 로드 — `.env` 자격증명 + `keywords.yaml` 정책."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from .naver import NaverCredentials


CONFIG_PATH_DEFAULT = Path("keywords.yaml")
ENV_PATH_DEFAULT = Path(".env")


@dataclass
class KeywordPolicy:
    """단일 키워드의 정책 (yaml 에서 파싱)."""

    name: str
    target_rank: int
    max_bid: int
    min_bid: int
    step: int


@dataclass
class AdgroupRef:
    id: str
    name: str = ""


DEFAULT_TARGET_RANK = 3
DEFAULT_MAX_BID = 10000
DEFAULT_MIN_BID = 100
DEFAULT_STEP = 500


@dataclass
class Defaults:
    target_rank: int = DEFAULT_TARGET_RANK
    max_bid: int = DEFAULT_MAX_BID
    min_bid: int = DEFAULT_MIN_BID
    step: int = DEFAULT_STEP


@dataclass
class Config:
    adgroups: list[AdgroupRef] = field(default_factory=list)
    keywords: list[KeywordPolicy] = field(default_factory=list)
    defaults: Defaults = field(default_factory=Defaults)
    analyze_overrides: dict = field(default_factory=dict)  # yaml 의 analyze 섹션 (raw)


# ─── env / credentials ──────────────────────────────────────────────────


def load_credentials(env_path: Path = ENV_PATH_DEFAULT) -> NaverCredentials:
    """`.env` 또는 환경변수에서 자격증명 로드."""
    if env_path.exists():
        load_dotenv(env_path)

    creds = NaverCredentials(
        api_key=os.environ.get("NAVER_API_KEY", "").strip(),
        secret_key=os.environ.get("NAVER_SECRET_KEY", "").strip(),
        customer_id=os.environ.get("NAVER_CUSTOMER_ID", "").strip(),
    )
    return creds


def require_credentials(env_path: Path = ENV_PATH_DEFAULT) -> NaverCredentials:
    """자격증명 누락 시 친절한 에러 메시지를 던진다."""
    creds = load_credentials(env_path)
    if not creds.is_complete():
        missing = [
            name
            for name, val in [
                ("NAVER_API_KEY", creds.api_key),
                ("NAVER_SECRET_KEY", creds.secret_key),
                ("NAVER_CUSTOMER_ID", creds.customer_id),
            ]
            if not val
        ]
        raise ValueError(
            f"자격증명 누락: {', '.join(missing)}\n"
            f"   `python -m powerlink_pilot setup` 을 실행해서 .env 를 생성하거나, "
            f".env.example 을 참고해 직접 만들어주세요."
        )
    return creds


# ─── yaml / policy ──────────────────────────────────────────────────────


def load_config(yaml_path: Path = CONFIG_PATH_DEFAULT) -> Config:
    """keywords.yaml 을 읽어 Config 로 반환. 검증 포함."""
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"{yaml_path} 가 없습니다.\n"
            f"   `python -m powerlink_pilot setup` 으로 생성하거나, "
            f"`examples/keywords.example.yaml` 을 참고해주세요."
        )

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{yaml_path}: 최상위는 매핑이어야 합니다")

    defaults_raw = data.get("defaults") or {}
    d_target = int(defaults_raw.get("target_rank", DEFAULT_TARGET_RANK))
    d_max = int(defaults_raw.get("max_bid", DEFAULT_MAX_BID))
    d_min = int(defaults_raw.get("min_bid", DEFAULT_MIN_BID))
    d_step = int(defaults_raw.get("step", DEFAULT_STEP))
    defaults = Defaults(target_rank=d_target, max_bid=d_max, min_bid=d_min, step=d_step)

    # adgroups (v0.2 부터, 샘플 모드에선 비어있어도 OK)
    adgroups: list[AdgroupRef] = []
    for entry in data.get("adgroups") or []:
        if isinstance(entry, dict) and entry.get("id"):
            adgroups.append(AdgroupRef(id=entry["id"], name=entry.get("name", "")))
        elif isinstance(entry, str):
            adgroups.append(AdgroupRef(id=entry))

    # keywords
    raw_list = data.get("keywords") or []
    if not raw_list:
        raise ValueError(f"{yaml_path}: 'keywords' 가 비어있습니다")

    keywords: list[KeywordPolicy] = []
    for idx, kw in enumerate(raw_list, 1):
        if not isinstance(kw, dict) or "name" not in kw:
            raise ValueError(f"{yaml_path}: {idx}번째 항목에 'name' 이 없습니다")

        name = str(kw["name"]).strip()
        target_rank = int(kw.get("target_rank", d_target))
        max_bid = int(kw.get("max_bid", d_max))
        min_bid = int(kw.get("min_bid", d_min))
        step = int(kw.get("step", d_step))

        if not 1 <= target_rank <= 10:
            raise ValueError(
                f"{yaml_path}: '{name}' target_rank={target_rank} 는 1~10 범위 밖"
            )
        if min_bid >= max_bid:
            raise ValueError(
                f"{yaml_path}: '{name}' min_bid({min_bid}) 가 max_bid({max_bid}) 이상"
            )
        if step <= 0:
            raise ValueError(f"{yaml_path}: '{name}' step 은 양수여야 합니다")

        keywords.append(
            KeywordPolicy(
                name=name,
                target_rank=target_rank,
                max_bid=max_bid,
                min_bid=min_bid,
                step=step,
            )
        )

    # analyze 섹션 (선택) — 사장님이 임계치를 yaml 로 조정할 수 있음
    analyze_section = data.get("analyze") or {}
    if not isinstance(analyze_section, dict):
        raise ValueError(f"{yaml_path}: 'analyze' 섹션은 매핑이어야 합니다")

    return Config(
        adgroups=adgroups,
        keywords=keywords,
        defaults=defaults,
        analyze_overrides=analyze_section,
    )


def get_analyze_thresholds(config: Config):
    """Config 의 analyze_overrides 를 analyzer.AnalyzeThresholds 로 변환.

    yaml 에 명시 안 된 필드는 기본값 유지. 순환 import 방지로 함수 내에서 import.
    """
    from .analyzer import AnalyzeThresholds

    base = AnalyzeThresholds()
    for key, val in (config.analyze_overrides or {}).items():
        if hasattr(base, key):
            setattr(base, key, val)
    return base


def policies_by_name(config: Config) -> dict[str, KeywordPolicy]:
    return {p.name: p for p in config.keywords}


# ─── yaml regeneration ─────────────────────────────────────────────────


def _yaml_quote(s: str) -> str:
    """yaml 문자열 quote (" 와 백슬래시 이스케이프)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_config(config: Config) -> str:
    """Config 를 yaml 문자열로 렌더링. defaults 와 다른 필드만 keyword override 로 출력."""
    lines: list[str] = []
    lines.append("# powerlink-pilot 설정")
    lines.append("# `setup` 으로 자동 생성됨. `set`/`set-defaults` 명령 또는 직접 편집 가능.")
    lines.append("# 키워드 이름은 네이버 광고 계정과 일치해야 합니다.")
    lines.append("")

    if config.adgroups:
        lines.append("adgroups:")
        for g in config.adgroups:
            lines.append(f'  - id: "{_yaml_quote(g.id)}"')
            if g.name:
                lines.append(f'    name: "{_yaml_quote(g.name)}"')
        lines.append("")

    d = config.defaults
    lines.append("defaults:")
    lines.append(f"  target_rank: {d.target_rank}")
    lines.append(f"  max_bid: {d.max_bid}")
    lines.append(f"  min_bid: {d.min_bid}")
    lines.append(f"  step: {d.step}")
    lines.append("")

    lines.append("keywords:")
    for kw in config.keywords:
        lines.append(f'  - name: "{_yaml_quote(kw.name)}"')
        # defaults 와 다른 필드만 override 로 출력
        if kw.target_rank != d.target_rank:
            lines.append(f"    target_rank: {kw.target_rank}")
        if kw.max_bid != d.max_bid:
            lines.append(f"    max_bid: {kw.max_bid}")
        if kw.min_bid != d.min_bid:
            lines.append(f"    min_bid: {kw.min_bid}")
        if kw.step != d.step:
            lines.append(f"    step: {kw.step}")
    lines.append("")
    return "\n".join(lines)


def write_config(path: Path, config: Config) -> None:
    """Config 를 atomic 으로 yaml 에 쓴다."""
    write_yaml_atomic(path, render_config(config))


# ─── atomic write ───────────────────────────────────────────────────────


def write_yaml_atomic(path: Path, content: str) -> None:
    """임시 파일에 쓰고 rename — 부분 쓰기를 막는다."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def write_env_atomic(path: Path, creds: NaverCredentials, anthropic_key: str = "") -> None:
    lines = [
        "# 네이버 검색광고 API",
        f"NAVER_API_KEY={creds.api_key}",
        f"NAVER_SECRET_KEY={creds.secret_key}",
        f"NAVER_CUSTOMER_ID={creds.customer_id}",
        "",
        "# Anthropic API (AI 기능 v0.3+ 사용 시)",
        f"ANTHROPIC_API_KEY={anthropic_key}",
        "",
    ]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(path)
