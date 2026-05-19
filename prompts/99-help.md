# 🆘 99 — 막혔어요 (진단 가이드)

## 사장님이 채팅에 입력할 한 마디

> **"막혔어요"**

또는

> **"에러나요"**

---

## Claude 진단 절차

순서대로 체크. 한 번에 한 단계씩, 사장님 답변 받으며 진행.

### Step 1 — 어디서 막혔는지

```
사장님, 어떤 단계에서 막히셨어요?

A. 설치할 때 ("다운로드해줘"가 안 됨)
B. API 키 발급할 때
C. 셋업할 때 (광고 계정 연결)
D. 입찰 돌릴 때
E. 검색어 분석할 때 (fetch-stats, analyze)
F. 모르겠어요 / 다른 거예요
```

### Step 2 — 환경 체크 (A인 경우)

```bash
python --version
ls -la
```

- Python 없음 → Claude Code 재설치 안내
- 폴더가 빈 폴더 → `git clone` 다시 실행
- venv 없음 → `python -m venv .venv && .venv/bin/pip install -e .`

### Step 3 — 키 체크 (B인 경우)

```bash
python scripts/verify_keys.py
```

- "키 누락" → `.env` 다시 작성 (`prompts/02-api-key-naver.md`)
- "401/403" → 사장님 네이버 콘솔에서 키 재발급
- "네트워크" → 인터넷 확인

### Step 4 — 셋업 체크 (C인 경우)

```bash
ls -la .env keywords.yaml
python -m powerlink_pilot show
```

- `.env` 없음 → setup 다시
- `keywords.yaml` 없음 → setup 다시
- show 에러 → yaml 형식 확인 (들여쓰기 깨졌나?)

### Step 5 — 입찰 체크 (D인 경우)

```bash
python -m powerlink_pilot run --dry-run
```

- "매칭 안 된 키워드" → 키워드 이름 불일치 (yaml vs 네이버 계정)
- "Estimate 호출 실패" → 잠시 후 재시도 (rate limit)
- "PUT 실패" → 광고그룹 권한 확인

### Step 5b — 검색어 분석 체크 (E인 경우)

```bash
python -m powerlink_pilot analyze --sample      # 일단 데모 모드로 동작 확인
```

- **분석 안 됨 (`run --sample` 도 안 됨)** → 환경 문제 (Step 2 환경 체크로)
- **"분석할 검색어 데이터가 없습니다"** → `python -m powerlink_pilot fetch-stats` 먼저 실행
- **`fetch-stats` 가 5분 이상 멈춤** → 광고 데이터 양 많음. 그대로 두거나, `Ctrl+C` 후 `--days 3` 으로 단축
- **`fetch-stats` 가 "데이터 없음" 만 반복** → 사장님 광고가 그 기간 안 돌았거나 광고 노출 0. 더 긴 기간 시도 (`--days 30`)
- **"보고서 생성 실패 (status=FAILED)"** → 네이버 서버 일시 문제. 30분 후 재시도
- **"광고그룹 조회 실패"** → 키 만료. Step 3 키 체크
- **`analyze --apply` 가 "권한 없음" 에러** → 광고 계정 권한 부족. 네이버 콘솔에서 권한 확인

### Step 6 — 그래도 막히면

```
사장님, 제가 해결 못 드린 것 같아요. 두 가지 방법이 있어요:

1️⃣ 김태대리 채널 댓글 / GitHub Issues 에 남기기
   → https://github.com/kimtaedaeri/naver-powerlink-bidding/issues
   → 어떤 단계에서 막혔는지 + 에러 화면 캡처 첨부

2️⃣ 영상 가이드 보기
   → https://youtube.com/@kimtaedaeri
   → 비슷한 상황을 다룬 영상이 있을 수 있어요
```

---

## 🚨 자주 발생하는 막힘 8가지

| 증상 | 원인 | 해결 |
|---|---|---|
| `ModuleNotFoundError: powerlink_pilot` | venv 활성화 안 됨 또는 install -e 안 함 | `.venv/bin/python -m powerlink_pilot ...` 또는 `pip install -e .` 재실행 |
| `error: externally-managed-environment` | macOS 시스템 pip 차단 | `.venv` 가상환경 필수 — README 30초 체험 참고 |
| `자격증명 누락` | `.env` 없음 또는 키 빈 값 | `prompts/02b-edit-env.md` 가이드 |
| `[401] auth failed` | API 키 만료·오타 | 네이버 콘솔에서 재발급 |
| `매칭 안 된 키워드` | yaml 이름 ≠ 네이버 계정 키워드 | yaml에서 정확한 이름으로 수정 |
| `Estimate API 호출 실패 [429]` | 호출 빈도 초과 | 30분 후 재시도 |
| `분석할 검색어 데이터가 없습니다` | 한 번도 fetch-stats 안 함 | `python -m powerlink_pilot fetch-stats` |
| `.env` 한글 깨짐 또는 키 미인식 | 윈도우 메모장 인코딩 (UTF-16 BOM) | VS Code 또는 메모장에서 "UTF-8" 선택 저장 |

---

## 사장님 톤

- "에러가 났어요"라는 사장님 말은 화남보단 무력감일 가능성 높음
- 첫 답변은 **공감 + 안심**: "아 그러시군요. 같이 한 단계씩 봐드릴게요."
- 절대 사장님을 탓하지 말 것. "사장님이 잘못 누르셨나봐요" X
- 항상: "환경 문제일 가능성이 높아요. 한 번 같이 확인해 봐요."
