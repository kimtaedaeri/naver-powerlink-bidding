# powerlink-pilot

> 네이버 검색광고 자동입찰 오픈소스 도구. 룰베이스부터 AI까지 단계별로 확장합니다.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Version](https://img.shields.io/badge/version-0.2.0-green.svg)](pyproject.toml)

> 🎬 **[김태대리 채널](https://youtube.com/@kimtaedaeri)의 첫 오픈소스**입니다.
> 1인 사업자 사장님 대신 일하는 코드 — 영원히 무료, AI까지 한 번에.

**v0.2 — 네이버 API 연동 + 대화형 setup + dry-run/live 모드 지원.**

---

## 🧭 가이드 선택

| 당신은 누구신가요? | 어디로 가야 할까요? |
|---|---|
| 📺 **사장님** — 코딩 0줄, 결과만 보고 싶다 | → [사장님 5분 시작](#-사장님-5분-시작) |
| 💻 **개발자** — 직접 설치·운영하고 싶다 | → [30초 체험](#30초-체험-api-키-불필요) |

---

## 📺 사장님 5분 시작

**코딩 안 해도 됩니다. 채팅으로만 합니다.**

### 1단계 — Claude Code 설치 (1분)

[Claude Code 공식 설치 가이드](https://docs.claude.com/claude-code) 를 따라 한 번만 설치하세요.

> 💡 ChatGPT 같은 채팅인데, 사장님 컴퓨터의 파일을 만지고 명령을 실행할 수 있는 버전입니다.

### 2단계 — 채팅에 한 줄 입력 (30초)

설치 후 터미널에서 `claude` 라고 치면 채팅이 열립니다. 거기에 이렇게 말씀하세요:

> **"github.com/kimtaedaeri/naver-powerlink-bidding 다운로드해서 데모 보여줘"**

김태대리(Claude)가 알아서 다운로드·설치·실행을 다 해 드립니다.

### 3단계 — 결과 확인 (30초)

3개의 가상 키워드가 목표 순위로 입찰가를 조정하는 시뮬레이션이 보입니다. **API 키 없이 작동**합니다.

### 4단계 — 본격 운영 (영상 가이드)

샘플이 마음에 드시면 실제 광고 계정과 연동하세요. 채팅에 이렇게 말씀하시면 됩니다:

> **"내 네이버 광고 계정 연결해줘"**

→ API 키 발급부터 첫 입찰 실행까지 단계별 안내가 시작됩니다.

📺 영상 가이드: [김태대리 채널](https://youtube.com/@kimtaedaeri)
📂 막히면: 채팅에 "막혔어요" 라고만 입력하세요

---

## 30초 체험 (API 키 불필요)

```bash
git clone https://github.com/kimtaedaeri/naver-powerlink-bidding
cd naver-powerlink-bidding
pip install -e .
python -m powerlink_pilot run --sample
```

내장 샘플 키워드 3개로 룰베이스 입찰 자동화를 시뮬레이션합니다.

```
🚀 powerlink-pilot — sample mode
📊 내장 샘플 (3개)

  키워드_쉬움      순위 7  입찰  2,500원 → 목표 3  새 입찰  3,000원  ⬆ raise
  키워드_중간      순위 8  입찰  4,000원 → 목표 3  새 입찰  4,500원  ⬆ raise
  키워드_경쟁심한  순위 11 입찰  5,000원 → 목표 2  새 입찰  5,800원  ⬆ raise

✅ 3건 기록됨
```

여러 번 실행하면 입찰가가 목표 순위로 **수렴**합니다. max_bid 안에서 목표를 못 잡으면 `⚠ capped` 으로 표시되어 한도 조정 신호가 됩니다.

---

## 실 광고 계정 연동 (5분)

### 1️⃣ 네이버 검색광고 API 키 발급

[네이버 검색광고 콘솔](https://manage.searchad.naver.com/customers) → **도구 > API 사용 관리** 에서:
- API 키
- 비밀키
- Customer ID

세 가지 값을 확보합니다.

### 2️⃣ 대화형 설정

```bash
python -m powerlink_pilot setup
```

마법사가 다음을 수행합니다:
1. API 키 입력 → 즉시 검증 (틀리면 재입력 루프)
2. 광고 계정의 광고그룹 자동 발견 → 관리할 그룹 선택
3. 선택된 그룹의 키워드 자동 불러오기 (활성·승인 상태만)
4. 기본값 입력 (목표 순위, 최대/최소 입찰가, 조정 단위)
5. `.env` + `keywords.yaml` 자동 생성

### 3️⃣ 안전 시뮬 (드라이런)

```bash
python -m powerlink_pilot run --dry-run
```

실제 네이버 API 를 호출해 현재 입찰가·추정 입찰가를 가져오지만 **입찰가는 변경하지 않습니다**. 결과 검토용.

```
🚀 powerlink-pilot — DRY-RUN mode
📁 설정: keywords.yaml
📂 광고그룹 1개, 키워드 12개

📡 키워드 페치 중...
   매칭된 키워드: 12개

📊 Estimate API 호출 중 (batch)...
   추정 입찰가 수신: 12개

  토지담보대출    현재  8,500원 → 목표 2  추정 12,300원  새 입찰  9,000원  ⬆ raise
  아파트담보대출  현재  9,200원 → 목표 2  추정 10,800원  새 입찰  9,700원  ⬆ raise
  ...

✅ 처리 12건 / 스킵 0건 / 실패 0건
   → 결과가 만족스러우면: python -m powerlink_pilot run --live
```

### 4️⃣ 실 운영 (라이브)

```bash
python -m powerlink_pilot run --live
```

명시적 확인 프롬프트가 나옵니다 — `yes` 입력 시에만 진행:

```
============================================================
⚠️  LIVE 모드 — 실제 입찰가가 변경됩니다.
============================================================
처음 사용하시는 경우 `--dry-run` 으로 먼저 결과를 확인하세요.

계속하시려면 'yes' 를 입력하세요: _
```

자동화 환경(GitHub Actions 등)에선 `--yes` 플래그로 스킵 가능.

---

## 명령어 한눈에 보기

```bash
# 셋업
python -m powerlink_pilot setup                  # 대화형 마법사 (.env + yaml 생성)

# 조회
python -m powerlink_pilot list adgroups          # 계정의 광고그룹
python -m powerlink_pilot list keywords          # yaml 의 그룹별 키워드 + 현재 입찰가
python -m powerlink_pilot show                   # 현재 키워드 정책 표
python -m powerlink_pilot show 토지담보대출      # 특정 키워드 상세

# 정책 수정 (yaml 수정만, API 호출 X)
python -m powerlink_pilot set 토지담보대출 --target-rank 2 --max-bid 16000
python -m powerlink_pilot set 토지담보대출 --reset                # override 제거
python -m powerlink_pilot set --match 아파트 --target-rank 2      # 부분 일치 일괄
python -m powerlink_pilot set-defaults --max-bid 25000            # defaults 변경

# 실행
python -m powerlink_pilot run --sample           # 가상 시뮬 (API 키 불필요)
python -m powerlink_pilot run --sample --config FILE
python -m powerlink_pilot run --dry-run          # 실 API, 변경 X
python -m powerlink_pilot run --live             # 실제 변경 (yes 확인)
python -m powerlink_pilot run --live --yes       # 자동화용

# 이력
python -m powerlink_pilot history                # 최근 20건
python -m powerlink_pilot history --mode live    # live 만
python -m powerlink_pilot history --reset        # 모든 기록 초기화
```

### 키워드별 정책 빠르게 조정하기

setup 직후엔 모든 키워드가 `defaults` 를 쓰지만, 키워드별로 조정이 필요한 경우가 많습니다.

**단일 키워드:**
```bash
python -m powerlink_pilot set 토지담보대출 --target-rank 2 --max-bid 16000
```

**부분 일치 일괄 (예: '아파트' 가 들어가는 모든 키워드):**
```bash
python -m powerlink_pilot set --match 아파트 --target-rank 2
# → 매칭된 키워드 19개 미리보기 + 확인 프롬프트
```

**override 제거 (defaults 사용):**
```bash
python -m powerlink_pilot set 토지담보대출 --reset
```

**현재 상태 확인:**
```bash
python -m powerlink_pilot show              # 전체 표 (override 컬럼)
python -m powerlink_pilot show 토지담보대출 # 키워드별 default/override 표시
```

`set` 명령은 `keywords.yaml` 만 수정합니다. 네이버 API 호출은 일어나지 않으므로 안전합니다. 실제 입찰 변경은 `run --live` 단계에서 발생합니다.

---

## 키워드 정책 — keywords.yaml

```yaml
adgroups:
  - id: "grp-a001-01-..."
    name: "광고그룹_표시이름"

defaults:
  target_rank: 3      # 목표 순위 (1=최상단)
  max_bid: 10000      # 최대 입찰가 (원)
  min_bid: 100        # 최소 입찰가 (원)
  step: 500           # 1회 조정 단위 (원)

keywords:
  - name: 토지담보대출
    target_rank: 2
    max_bid: 16000

  - name: 아파트담보대출   # defaults 사용
```

| 필드 | 필수 | 기본값 | 설명 |
|---|:-:|---:|---|
| `name` | ✅ | — | 키워드 이름 (네이버 광고 계정과 정확히 일치) |
| `target_rank` | ⬜ | 3 | 목표 순위 (1=최상단, 1~10) |
| `max_bid` | ⬜ | 10,000 | 최대 입찰가 (원, 절대 넘지 않을 금액) |
| `min_bid` | ⬜ | 100 | 최소 입찰가 (원, 안전선) |
| `step` | ⬜ | 500 | 1회 조정 단위 (원) |

전체 예시: [`examples/keywords.example.yaml`](examples/keywords.example.yaml)

---

## 작동 원리

### 입찰 결정 로직

각 실행마다 키워드별로:

1. **현재 입찰가** 를 네이버 API 에서 조회 (`bidAmt`)
2. **추정 입찰가** 를 네이버 Estimate API 로 조회 (`target_rank` 도달에 필요한 금액)
3. **방향 결정** — 추정 > 현재 → ↑, 추정 < 현재 → ↓, 같으면 hold
4. **한 번에 `step` 만큼만 이동** — 급격한 변경 방지
5. **`min_bid` ~ `max_bid` 범위에 클램프**
6. **결과를 SQLite 에 로그**

```
새 입찰가 = 클램프(현재 입찰가 ± step, min_bid, max_bid, 추정 입찰가)
```

### 왜 Selenium 안 쓰나

기존 룰베이스 자동화는 보통 SERP 를 직접 크롤링해 순위를 측정합니다. powerlink-pilot 은 대신 **네이버 공식 Estimate API** 를 사용합니다:

- ✅ 셋업 0 (Chrome / ChromeDriver 불필요)
- ✅ 빠름 (100 키워드 1초 미만, batch 호출)
- ✅ Mac/Linux/Windows/GitHub Actions 모두 동일 동작

추정값이 실제 노출 순위와 다소 차이날 수 있지만, 매 시간 재추정으로 자연 수렴합니다.

---

## 향후 계획

| 버전 | 추가 내용 |
|---|---|
| ✅ v0.1 | 샘플 모드 (시뮬레이션) |
| ✅ v0.2 | 네이버 API 연동, setup 마법사, dry-run/live |
| 🔜 v0.3 | Claude AI 광고 카피 자동 생성·A/B |
| 🔜 v0.4 | 검색 쿼리 분석 → 부정 키워드 자동 발굴 |
| 🔜 v0.5 | 시간대별 룰 자동 튜닝 |

---

## 영상 가이드

(영상 링크는 출시 시 추가됩니다)

---

## 비용

| 항목 | 월 비용 |
|---|---|
| GitHub Actions cron (셀프호스팅) | ₩0 |
| 네이버 광고 API | ₩0 |
| Anthropic API (v0.3+) | 약 ₩2,000~5,000 |

본인 명의 네이버 광고주 계정만 있으면 추가 비용 0원으로 운영 가능합니다.

---

## GitHub Actions 로 자동 운영

`.github/workflows/hourly_bid.yml`:

```yaml
name: hourly bid
on:
  schedule:
    - cron: '0 * * * *'   # 매 시간 정각
  workflow_dispatch:

jobs:
  bid:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e .
      - run: python -m powerlink_pilot run --live --yes
        env:
          NAVER_API_KEY: ${{ secrets.NAVER_API_KEY }}
          NAVER_SECRET_KEY: ${{ secrets.NAVER_SECRET_KEY }}
          NAVER_CUSTOMER_ID: ${{ secrets.NAVER_CUSTOMER_ID }}
```

GitHub Secrets 에 키 3개 등록 후 푸시하면 매 시간 자동 운영. **인프라 비용 0원.**

---

## 보안

- `.env` 와 `keywords.yaml` 은 `.gitignore` 에 포함되어 있어 실수로 커밋되지 않습니다
- API 키는 본인의 개인 환경 / 사용자 명의 GitHub Secrets 에만 저장하세요
- 절대 다른 사람의 광고주 계정 키로 운영하지 마세요

---

## 기여

이슈·PR 환영합니다. 큰 변경은 먼저 이슈로 논의해주세요.

---

## 라이센스

MIT — © 2026 김태대리. 자세한 내용은 [LICENSE](LICENSE) 참조.

상업적 이용 가능. 본인 책임 하에 사용하세요. 광고비 운영 결과에 대한 책임은 사용자에게 있습니다.

---

## 만든 사람

**김태대리** — 1인 사업자 사장님 대신 일하는 코드를 만듭니다.

- YouTube: [@kimtaedaeri](https://youtube.com/@kimtaedaeri)
- GitHub: [@kimtaedaeri](https://github.com/kimtaedaeri)
- Contact: kimtaedaeri@gmail.com
