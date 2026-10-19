# commerce_platform v3 — Commerce AI · KOP Labs 보완판

검토 기준일: 2026-10-16. 제공 ZIP과 MD의 실제 소스를 검토하고 기존 대화의 개발 기록과 비교했다.
이 파일의 v3 판정이 뒤의 v2 설명보다 우선한다. 원본 저장소 전체·운영 DB·기존 패키지 원본은 미제공이다.
원문 v2의 “이식 완료” 설명은 이번 검토에서 독립 재현한 사실로 확대 해석하지 않는다.

## 이번 실행 가능한 변경

| 영역 | 추가/수정 | 사용 위치 | 검증 범위 |
|---|---|---|---|
| 레시피 대화 | 레시피 요청을 상품 검색에서 분리, 요리·인분·원문 확인 | `/api/chat` | TestClient |
| 재료 계획 | 필수/선택·필요량·보유량·단위·조리 상태, 부족분 계산 | `POST /api/recipe/plan` | 오프라인 API 테스트 |
| 원문 수량 | 비유 원문과 별도 g/ml 보존, 임의 환산 없음 | `shared/recipe_contracts.py` | RC061 형태 합성 회귀 사례 |
| NLU | trust·어버이날·선물 의도 보강, 몰이 있어도 알레르기 보존 | rule_nlu/service | 규칙 및 병합 계약 |
| 추천 근거 | 옵션·총비용·배송·반품·출처·신선도 충분성 검사 | assurance → recommender → card JSON | 로컬 판정 |
| 점수 계보 | v7_final_score → final_recommendation_score → score, 0 보존 | commerce_ai_adapter | 입력 dict 테스트 |
| 가격 비교 | 동일 옵션·중량·원산지·등급 확인 전 가격 역전 판단 중단 | `price_gap()` | 함수 테스트 |
| 공급사 | 발견과 거래 준비 분리, 축종·규격·수량·납기·만료 견적 질문 | supplier_contracts | 함수 테스트 |
| 제휴 | sponsored 후보 일반 순위 제외, 구매 링크 수수료 안내 | recommender/presenter | 소스 구현, 실제휴 미검증 |
| 링크 | 외부 이동은 http/https만 허용 | `/go` | 코드 변경 |

## 레시피 사용법

기존 consumer 앱 실행 후 `/docs`의 `POST /api/recipe/plan`에서 JSON 요청을 보낼 수 있다.
샘플은 `examples/recipe_plan.json`. 아래 명령은 localhost만 호출한다.

```bash
python -m pip install -r requirements.txt
python -m uvicorn consumer.app:app --host 127.0.0.1 --port 8000
# 다른 터미널
curl -H 'Content-Type: application/json' --data-binary @examples/recipe_plan.json http://127.0.0.1:8000/api/recipe/plan
python -m pytest -q
```

원문 레시피 입력 기반이며 내장 공공 레시피 목록은 없다. 인분 자동 배율·단위 환산·조리 상태 환산은 구현하지 않았다.
필요량/보유량은 명시 단위와 조리 상태가 같아야 계산한다. 선택 재료는 필수 구매 목록에 넣지 않는다.
동일 재료를 자동 병합하지 않아 중복 입력 가능성이 있으므로 구매 전 검토가 필요하다. 주문·검색 자동 발송은 하지 않는다.
`RecipeEvidence`는 원문·source_id·page·bbox를 저장할 수 있는 계약이며 OCR 추출기 자체가 아니다.
출처 문자열이 있다고 원문 진위나 수량 정확성을 자동 검증한 것은 아니다.

## 기존 개발과의 차이 및 연결 대기

| 기존 기록 | 기록상 상태 | 이번 반영 | 남은 작업 |
|---|---|---|---|
| RC061 등 레시피 표현 평가 | 선정 14건 최신 한정 PASS, 사람 검토 대기 | 비유+명시 중량 보존 계약 | 기존 파일럿 원본과 전체 케이스 재현 |
| EPIS·식품안전나라 레시피 | 수집/저장 보고 | 출처 기반 입력 계약 | 원본 수집기·537건 데이터 제공 후 연결 |
| OCR v2 | 확대·원본 좌표·불확실 구간 처리 코드 제공 기록 | 페이지/좌표/원문 보존 모델 | OCR 엔진 및 Luna→Sol 원본 연결 |
| 도매꾹 | 3회·15건 조회 시험 PASS, 앱 연결 없음 | 공급 증거·유효 견적 계약 | 실제 응답 스키마·옵션·판매단위 연동 |
| 전국 식육포장 후보 | 7,962건 화면 집계 미확인 | DISCOVERY_ONLY 계약 | 원본 CSV 및 영업/축종 재확인 |
| Hero provenance·/nl route | 기존 로컬 테스트 보고 | 점수 출처 필드만 보완 | 원본 Hero/route 계약 이식·동등성 검증 |
| KAMIS·aT·AFDC | 승인·조회 기록 | 설계상 외부 근거로 유지 | 단위·지역·시장·시점 맞춤 후 gap 비교 |
| 고객 니즈 연구 27_2 | 연구용 여섯 사례 | 충분성·추가근거 목록 아이디어 반영 | 원본 여섯 사례 미제공, 임의 재생성 안 함 |

## 새 아이디어의 반영 범위

1. **근거가 추가되면 판정이 바뀌는 계약**: `assess()`가 missing과 next_evidence를 반환한다. 누락 필드를 보완하여 재평가할 수 있다. 실제로 출처를 수집·검증하는 기능과는 구분한다.
2. **시간이 지나면 판정 재검토**: 가격은 기본 24시간 후 재확인, 견적은 만료 시 DISCOVERY_ONLY. 분야별 TTL은 추후 정책 설정 대상으로 둔다.
3. **구매를 미루는 답도 결과**: NOT_RANKABLE은 탐색 후보로 제공하고 확정 추천 문구를 중단한다. 현재 카드의 점수는 탐색 정렬 점수이지 검증된 품질 점수가 아니다.

## 경계와 알려진 제약

- Tier A 종료, production/32, 기존 거버넌스 승인 상태를 변경하지 않았다. 이 패키지의 로컬 계약은 KOP Labs 공식 승인 변경이 아니다.
- 랭킹의 품질 3점 휴리스틱, 별점/리뷰량 점수는 기존 코드에 남아 있다. 검증된 품질·실구매자 리뷰로 보증하지 않는다.
- 카드 JSON에 decision/score_source가 추가되었으나 기존 웹 카드에는 세부 근거 원장·OCR 뷰어·레시피 재료 편집 화면이 없다. 경고 notice와 레시피 대화 안내는 기존 UI에서 표시된다.
- 공급사 및 가격역전 계약은 Python 서비스 모듈이다. B2B 콘솔의 후보 판정기와 자동 통합되지 않았으며 기존 HOLD/ELIGIBLE을 대체하지 않는다.
- decision ledger 영구 이력, 권한별 정책 레지스트리, 고객 특성 가설·반대증거, 호출 예산 장부는 후속 설계 항목이다.
- 외부 API 실제 호출·인증, 기존 Commerce AI/food-nlu 실행, Mac 설치, 브라우저 화면은 이번 실행에서 검증하지 않았다.
- 기존 scheduled 수집 YAML은 원본 그대로 보존했으며 예약 생성/실행은 하지 않았다.
- 권장 순서: 기존 저장소 계약 확인 → 데이터/어댑터 연결 → UI → 실 API 소량 검증 → 사람 검토 → 운영 전환.


## 이번 검증 결과

Python 3.12 로컬 환경: 기존 26건 + 신규 10건 = **36 passed**. FastAPI TestClient 의존성 deprecation 경고 1건. 외부 API 호출 없는 테스트이며 실제 마켓·OCR·기존 엔진 통합 통과를 의미하지 않는다. 상세 출력: `docs/VALIDATION.txt`.

---

# 원본 v2 아키텍처 (보존)

# commerce_platform 통합 아키텍처

commerce_ai_generator(추천 엔진)와 food-nlu(자연어 이해 + 마켓 API)를 하나로 합치고,
B2B 입찰 업무는 별도 내부 시스템으로 분리한 구조입니다.

## 1. 결론: "공통 코어 1개, 앱 2개"

```
                    ┌──────────────────────── shared/ (공통 코어 라이브러리) ────────────────────────┐
                    │  nlu/        food-nlu(LLM+사전DB) ⊕ 규칙 NLU(항상 동작)                      │
                    │  markets/    쿠팡 파트너스 · 네이버 쇼핑 · 예시몰  → Offer 로 정규화         │
                    │  engines/    commerce_ai V8 파이프라인 어댑터 → 실패 시 기본 랭커            │
                    │  store.py    관측 가격·검색·클릭 로그 (core 스키마)                         │
                    │  llm.py      none / ollama / openai / anthropic                             │
                    └───────────────▲───────────────────────────────────▲──────────────────────┘
                                    │ import                            │ import (읽기 전용 사용)
   ┌────────────────────────────────┴──────────┐    ┌───────────────────┴──────────────────────────┐
   │ consumer/  공개 B2C 대화형 추천 (port 8000) │    │ b2b/  내부 입찰 콘솔 (port 8100, 토큰 인증)  │
   │  dialogue.py  상태 머신 (추천 먼저→조건)    │    │  console.py   프롬프트 → 도구 라우팅         │
   │  presenter.py 결과 → 화면 블록 JSON         │    │  request_parser 공고문 → 조건(+원문 발췌)    │
   │  web/index.html 카드·비교함·선택형 질문      │    │  evidence.py  근거 저장소 + 판정기           │
   └───────────────────────────────────────────┘    │  sourcing.py  후보 발굴 (shared 재사용)      │
                                                     │  costing.py   1인 비용 구조                  │
                                                     │  rfq.py · report.py · proposal.py            │
                                                     │  web/console.html                             │
                                                     └──────────────────────────────────────────────┘
```

의존 방향은 한쪽뿐입니다: `consumer → shared ← b2b`. consumer 는 b2b 를 import 하지 않고,
b2b 는 core 데이터를 **읽기만** 합니다. 그래서 B2B 를 사내망에만 두고 소비자 앱만 공개 배포할 수 있습니다.

### 왜 마이크로서비스가 아니라 이 구조인가
- 1인 개발·운영 규모에서 서비스 여러 개는 배포·장애 지점만 늘립니다.
- 그래도 B2B 는 **프로세스·포트·DB·인증이 분리**되어 있어, 나중에 별도 서버로 떼어내도 코드 변경이 거의 없습니다.

## 2. 기존 두 시스템을 어떻게 흡수했나 (Strangler 패턴)

| 기존 | 통합 후 | 방식 |
|---|---|---|
| food-nlu `nlu.py` (LLM + intent_master/slot_definition DB) | `shared/nlu/service.py` | `FOOD_NLU_PATH` 를 지정하면 그대로 import 해서 1차 파서로 사용. 숫자 슬롯(예산·수량)과 몰은 규칙 결과로 덮어씀 |
| food-nlu 시스템 프롬프트의 ACTION 우선순위 | `shared/nlu/rule_nlu.py` | 같은 우선순위를 코드로 옮김 → LLM 없어도 동작 |
| food-nlu `naver_api.py`, `coupang_api.py` | `shared/markets/*` | 서명·정규화 이식. **배송비를 모르면 0이 아니라 None** 으로 변경 |
| food-nlu `router.py` | `shared/engines/recommender.py` | 검색어 조합 로직 이식. 원본의 `items` 선언 전 사용 버그(네이버 이중 호출)는 새 코드에 없음 |
| commerce_ai `run_recommendation_pipeline()` | `shared/engines/commerce_ai_adapter.py` | 공개 파사드만 호출, 내부(V8·food knowledge·cross-border) 무수정. `COMMERCE_AI_PATH` 미설정/실패 시 기본 랭커 |
| commerce_ai `CONVERSATION_STATE_MACHINE.md` | `consumer/dialogue.py` | UNDERSTAND→CLARIFY→RECOMMEND→REFINE 축소 구현 |
| commerce_ai `data/b2b_evidence/v2` (bundle, evaluate) | `b2b/evidence.py` | 번들 적재 그대로, 판정 규칙을 임직원 선물 조건으로 일반화 |
| smallbiz-monitor `/b2b_gift` (anti_online) | `b2b/bids.py` · `b2b/gift_monitor/` | 공고 목록·상태·필터·엑셀을 B2B 모니터로 이식. **소상공인 지원사업 모니터링은 삭제** |
| gift_trend_analyzer | `b2b/gift_monitor/classify.py · trends.py · checkpoints.py` | 유형·기업유형·자격요건 분류, 트렌드 집계, 공고별 점검 포인트, 준비도 자가 점검 이식 |
| 두 저장소의 `core_crawler.py` · `run_crawler.py` | `b2b/gift_monitor/collectors.py` · `scripts/collect_bids.py` | 시뮬레이션 크롤러를 **나라장터 OpenAPI 실수집**으로 교체 (아래 5-1 참고) |
| 두 저장소의 `bid_document_generator.py` | (이식하지 않음) | 기관 명의 공고문·RFP·과업지시서를 지어내 HWPX 로 만드는 기능 → 실제 원문 첨부(HWPX·PDF·DOCX) 텍스트 추출로 대체 |

단계별 이행:
1. **지금**: 새 앱을 기존 시스템 옆에 띄우고, 엔진·NLU 는 경로 지정으로 연결 (기존 코드 무변경)
2. **다음**: Streamlit UI 사용 중단, `/recommendations/nl` 호출자를 `consumer` API 로 교체
3. **이후**: commerce_ai 의 Postgres 를 `core` 스키마로 정리하고 `store.py` 가 같은 DB 를 사용

## 3. 데이터

| 스키마 | 테이블 | 쓰기 | 읽기 |
|---|---|---|---|
| core | offer_observation, search_log, click_log | consumer | consumer, b2b(읽기) |
| b2b | b2b_bid(공고 + 신뢰 등급), b2b_candidate, b2b_source, b2b_document | b2b | b2b |

개발은 SQLite 두 파일(`var/core.sqlite3`, `var/b2b.sqlite3`), 운영은 Postgres 한 대에서
스키마를 나누고 **b2b 계정에는 core 읽기 권한만** 주는 방식을 권장합니다.

## 4. 소비자 UI/UX — 서버가 '화면 블록'을 내려준다

`POST /api/chat` 응답은 `blocks` 배열입니다: `text · product_list · notice · verdict · clarify_form · chips`.
웹은 이 JSON 을 렌더링만 합니다. 같은 JSON 으로 네이버 블로그 글, 카카오 알림톡, 앱을 만들 수 있습니다.

캡처 화면(ChatGPT 쇼핑 카드) 대비 개선점
1. **실구매가 우선**: `7,500원 + 배송비 3,500원` 대신 `실구매 11,000원`을 크게, 내역은 작게. 배송비를 모르면 '미확인'이라고 표시
2. **개당 단가**: 20개입·2개입 같은 묶음 상품을 개당 가격으로 비교
3. **조회 시각 배지**: "3시간 전 조회", 24시간 넘으면 경고색
4. **확인된 근거 / 미확인 칩**: ✓평점 4.7 ✓후기 885개 / ?배송비 미확인 — 추천 이유를 숨기지 않음
5. **비교함**: 카드 오른쪽 위 + 로 최대 3개 담고 표로 비교 (가장 유리한 값 초록색)
6. **질문은 추천 뒤에**: 예산 구간은 실제 결과 가격 분포로 자동 생성(1만원 이하 / 1만~2만원 / 2만원 이상), 받는 사람·구매처는 빠졌을 때만, 최대 2개
7. **다음 행동 칩**: 더 저렴한 것 / 후기 많은 순 / 프리미엄으로 → LLM 호출 없이 즉시 재정렬
8. **클릭 추적 + 안전한 이동**: `/go/{세션}/{순위}` — 직전 추천 결과에 있는 URL 로만 이동(임의 URL 리다이렉트 차단)

## 5. B2B 콘솔 — 프롬프트로 일을 시키는 내부 도구

| 지시 예 | 도구 | 결과 |
|---|---|---|
| `IBK서비스-2026008 분석해줘` / 공고문 붙여넣기 | analyze | 조건 표(원문 발췌·출처), 카테고리 충족도, 후보 판정, 비용 구조. 부족한 카테고리는 자동 후보 발굴 |
| `공고 목록 보여줘` / 파일 업로드 | list / import | smallbiz-monitor 공고 |
| `매입가 36000 포장 1500 배송 3500 운영 800 구축비 300만원` | cost | 1인 비용 막대, 잔여액(모든 항목 입력 시에만) |
| `견적 요청서 만들어줘` | rfq | 공급사별 초안 + 후보별 질문 (복사 버튼, 발송 기능 없음) |
| `분석 리포트 열어줘` | report | 첨부 HTML 형식을 개선한 1장 리포트 |
| `제안서 작성해줘` (`다듬어서` 추가 시 LLM 문장 다듬기) | proposal | 내부 검토본·제출본 초안 × HTML/Word |

판정 규칙 (번들 policy 를 코드로 강제)
- 미확인 → 충족 아님 → **HOLD**. 위반 → **EXCLUDED**. 전부 확인 → **ELIGIBLE**
- 공개 판매가 ≠ 견적. 미확인 비용 ≠ 0원. 종료된 할인가는 쓰지 않음
- 2,090명 ÷ 6종 같은 균등 배분 가정 금지

## 5-1. B2B gift-monitor · 트렌드 분석 통합

화면: `/monitor` (탭: 공고 모니터 · 트렌드 분석 · 준비도 점검) + 콘솔 명령 (`나라장터 공고 수집해줘`, `입찰중 공고 보여줘`, `입찰 트렌드 분석해줘`, `legacy-17 분석해줘`)

### 기존 코드에서 확인한 문제 (이식하지 않은 이유)
- `core_crawler.py` 는 대상 사이트 접속만 시도하고 응답은 쓰지 않는다. 하드코딩된 `SIMULATED_NEW_GIFTS` 를 80% 확률로 오늘 날짜의 '새 공고'로 DB에 넣는다.
- `database.py` 의 `gift_seed_data` · `NEW_Q4_GIFT_BIDS` 23건도 코드에 직접 적힌 값이다. 링크는 사이트 첫 화면, 담당자·연락처·예산은 출처가 없다 (예: 서울교통공사 2건의 담당자가 서로 다름).
- `bid_document_generator.py` 는 실제 기관 명의의 공고문·제안요청서·과업지시서를 생성한다.

### 신뢰 등급
| 등급 | 의미 | 목록·통계 기본값 |
|---|---|---|
| verified (원천 확인) | 나라장터 OpenAPI 응답, 또는 사람이 원문 URL·첨부를 대조하고 확인 처리 | 포함 |
| document_provided (제공 문서) | 사용자가 준 원문 문서에서 추출 (예: IBK서비스-2026008) | 포함 |
| unverified (원문 대조 전) | 직접 등록·CSV 업로드 | 포함 (배지 표시) |
| legacy_unverified (미검증 기존 데이터) | `scripts/import_legacy_gift_db.py` 로 가져온 기존 23건 | **제외** (토글로 포함 가능) |

- '원문 대조 완료' 처리는 공고 상세 URL(사이트 첫 화면 제외)이나 원문 첨부가 있어야 가능하다.
- 콘솔 분석·제안서는 신뢰 등급이 낮은 공고에 경고와 `[확인 필요: 공고 원문 대조]` 를 붙인다.

### 수집
- 나라장터: `https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfo{Thng|Servc}PPSSrch`
  (물품·용역, 공고명 검색어 = 임직원 선물·명절 선물·선물세트·기념품·온누리상품권·모바일상품권·복지몰·창립기념). `G2B_SERVICE_KEY` 필요
- 은행·보험사처럼 API 가 없는 민간 공고: 직접 등록 + 원문 첨부 (HWPX·PDF·DOCX·TXT 텍스트 추출 → 조건 재추출)
- 정기 실행: `scripts/collect_bids.py` + `deploy/weekly_bid_collect.yml` (기존 weekly_crawler.yml 대체)

### 분석
- 규칙 분류: 선물 유형 8종, 요구 기업 유형 4종, 자격요건 5종, 기관 유형, 시기(설·추석·창립·기념일·연말·가정의달), 예산대
- 트렌드: 분포 + 월별 마감 + 집계 수치로만 만든 요약 문장 (기존 'AI 트렌드 리포트' 고정 문구 대체)
- 공고별 점검 포인트: 유형별 요구사항·제안 포인트·리스크 (특정 브랜드 추천·근거 없는 보장 문구 제거)
- 준비도 자가 점검: 기존 100점 시뮬레이터 이식. 배점은 '예시'이며 공고 평가표 값으로 바꿔 계산, 미응답은 0점이 아니라 미응답


## 6. 제안서 작성 기능

`b2b/proposal.py` — 조건 + 판정 + 회사 프로필(`b2b/data/company_profile.json`) + 비용 → 섹션 트리 → HTML/DOCX

목차: 1 제안 요약 · 2 사업 이해 · 3 요구사항 대응표 · 4 상품 구성안 · 5 폐쇄몰 구축·운영(D+0~D+5) ·
6 배송·교환·CS · 7 가격 제안 · 8 품질·리스크 · 9 제안사 소개 · (내부) 부록 A 확인 체크리스트 · 부록 B 비용 구조

- 모르는 값은 **[확인 필요: …]** 로 남기고 노란색 표시, 상단에 남은 개수 표시
- **제출본 초안**은 원가·마진·내부 판정·공급 경로를 빼고, 온라인가 하한 이상으로 관측된 후보만 표시
- LLM 다듬기: 원문에 없던 숫자가 생기면 결과를 버리고 원문 사용 (실적·인증 지어내기 방지)

## 7. 보안·운영

- B2B: `B2B_ACCESS_TOKEN` 필수, `127.0.0.1` 바인딩 기본, 쿠키 httponly·samesite=strict, `/docs` 비활성, 파일 경로 이탈 차단
- 외부로 메일·메시지를 보내는 기능이 없습니다. 견적 요청과 제안서는 모두 초안 파일입니다
- 키가 하나도 없으면 '예시몰' 데이터로 동작하고 화면에 '예시 데이터'를 표시합니다. 실 API 가 켜지면 예시몰은 자동으로 꺼집니다

## 8. 다음 단계 제안

1. 공공데이터포털에서 나라장터 입찰공고정보서비스 활용신청 → `G2B_SERVICE_KEY` 설정 후 주 1회 수집 시작
2. 공급사 회신(메일·PDF·엑셀) 파서 → Candidate 의 견적 필드 채우기 → ELIGIBLE 이 생기기 시작
3. consumer 의 `blocks` 를 네이버 블로그 글 템플릿으로 변환 (주 2회 파일럿)
4. click_log → commerce_ai adaptive 점수(user_preference_profile)로 연결
