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
