# 소비자 추천 UI/UX 설계 — 프롬프트 중심 탐색 화면 흐름

작성일 2026-10-20 · 대상 폴더 `integrated_system/ui_ux` · 백엔드 `consumer/app.py` (`POST /api/chat`)

## 1. 목표와 범위

통합 설계(commerce_platform)의 원칙인 **실구매가 우선 · 근거와 미확인 구분 · 유료 소개 분리 · 안전한 판매처 이동**을
고객이 실제로 눌러 볼 수 있는 화면 흐름으로 연결한다.

| 단계 | 고객 화면 | 핵심 기능 | 이번 개발 |
|---|---|---|---|
| ① 원하는 것 입력 | “부모님 드릴 부드러운 소고기, 10만원 안쪽” | 자연어 입력, 예시 질문 | ✅ `HomeScreen` |
| ② 필요한 조건 확인 | “몇 분이 드시나요?” | 선택에 영향을 주는 질문만 **한 번에 하나씩** | ✅ `ClarifyForm` |
| ③ 후보 비교 | 조건에 맞는 상품 3개 내외 | 총가격·중량·배송·선택 이유·확인되지 않은 조건 | ✅ `CandidateCompare` (+1:1 `ComparisonCard`) |
| ④ 상품 판단 | 상세정보·리뷰 요약 | 판매자 표기 / 리뷰 근거 분리, 원문 연결 | ✅ `ProductDetail` |
| ⑤ 구매 연결 | 선택 상품·옵션 확인 | 옵션·수량·배송비 확인 → 판매처 이동 | ◐ 미리보기 (`/go/{sid}/{rank}` 연결) |
| 레시피 | 메뉴 → 보유 재료 → 부족 재료만 추천 | | ◐ 예시 모드에서 질문 흐름만 |

## 2. 기술 스택과 실행

- React 18 (함수형 컴포넌트) · TypeScript (strict) · Tailwind CSS 3 · Vite 6
- 기존 `consumer/web/index.html` 팔레트(종이색 배경, 초록 강조, Pretendard)를 CSS 변수로 이어받고 다크 모드 지원

```bash
cd ui_ux
npm install
npm run dev:mock     # 백엔드 없이 예시 시나리오 (http://localhost:5173)
# 실제 API 연결
../run_consumer.sh   # FastAPI :8000
npm run dev          # /api, /go 를 :8000 으로 프록시
npm run build        # 타입 검사 + dist/ 생성
```

`.env.example` → `VITE_API_MODE=mock|live`, `VITE_API_TARGET` (기본 `http://127.0.0.1:8000`).

## 3. 화면 구조

```
ChatWindow ─┬─ header: 로고 · FlowStepper(①~⑤) · 새 대화
            ├─ (대화 없음) HomeScreen  ← ① 큰 입력창 + 예시 질문 4개
            ├─ (대화 있음) 대화 기록
            │     ├─ 사용자 말풍선
            │     └─ AI 응답 = BlockRenderer(blocks)
            │            text · notice · verdict · chips
            │            clarify_form      → ClarifyForm        ②
            │            candidate_compare → CandidateCompare   ③
            │            comparison_pair   → ComparisonCard     ③ (1:1 split view)
            │            product_list      → ProductList (참고용 목록)
            │            sponsored_list    → SponsoredList (유료 소개 영역)
            │            shipping_options  → ShippingOptions (해외 접속 시)
            ├─ 하단 Composer (Enter 전송, 한글 조합 중 Enter 무시)
            └─ ProductDetail  ④⑤  PC: 오른쪽 패널 480px / 모바일: 하단 시트 (Esc·배경 클릭으로 닫기)
```

FlowStepper 의 현재 단계는 **마지막 AI 응답의 블록 종류**와 상세 패널 상태로 계산한다
(`clarify_form` → ②, 비교 블록 → ③, 상세 열림 → ④, 옵션 확인 → ⑤).

### 파일

```
src/
  types/blocks.ts          블록 계약 (기존 + 제안) · 화면용 Candidate / ProductDetail
  api/client.ts            sendChat (mock|live) · goUrl
  api/adapt.ts             응답 정규화 (형식 차이 흡수, 3개 이상 → candidate_compare, 유료 분리, 중복 제거)
  api/mock.ts              예시 시나리오: 소고기(전체 흐름) · 쿠키(1:1 비교) · 레시피(질문 흐름)
  state/useConversation.ts 대화 상태 · 세션 · 단계 계산
  components/              ChatWindow · HomeScreen · Composer · FlowStepper · BlockRenderer
                           ClarifyForm · CandidateCompare · ComparisonCard · ProductList(SponsoredList)
                           ShippingOptions · ProductDetail · ChipsRow · ui(Thumb·TotalPrice·태그)
  lib/                     format(원화·중량·100g당) · Markdown(**굵게**·목록만, HTML 해석 안 함)
```

## 4. 단계별 설계 결정

### ① 원하는 것 입력
- 첫 화면은 질문 한 줄 + 큰 입력창. 예시 질문은 선물·간식·레시피·캠핑 4종 (누르면 바로 전송).
- “유료 소개는 따로 표시한다”는 원칙을 첫 화면 하단에 미리 밝힌다.

### ② 필요한 조건 확인
- 서버의 `clarify_form.questions` 를 **순차 표시**한다. 고른 질문은 한 줄 요약(“몇 분이 드시나요? 3~4명 · 수정”)으로 접혀 언제든 고칠 수 있다.
- 질문마다 `why`(이 질문이 선택에 주는 영향)를 한 줄로 보여 주고, 선택지에는 `hint`(예: “1kg 안팎”)를 붙인다.
- “잘 모르겠어요 · 건너뛰기” — 모르는 조건을 강요하지 않는다. 건너뛴 항목은 서버로 보내지 않는다.
- 전송 형식은 기존과 같다: `{"answers": {"servings":"3-4","cooking":"grill"}}`.

### ③ 후보 비교
- **같은 기준, 같은 순서**: 총가격 → 중량(100g당) → 배송 → 선택 이유 → 확인되지 않은 조건 → 출처.
- PC는 열=상품 비교표, 모바일은 같은 순서의 카드 세로 쌓기 (가로 스크롤 없음).
- 총가격은 배송비 포함. 배송비를 모르면 0원으로 가정하지 않고 “상품가 + **배송비 미확인**”.
- 가장 유리한 값(최저 총가격, 최저 100g당)만 초록색. 순위 숫자보다 기준별 비교가 먼저 보이도록 했다.
- 적용한 조건을 칩으로 상단에 보여 줘서 “왜 이 3개인지”를 설명한다.
- 2개짜리 후속 비교(“도착일 보장되는 것만”, “더 저렴한 곳”)는 `ComparisonCard` split view (모바일 세로).

### ④ 상품 판단
- **판매자 표기**(검정 점)와 **리뷰 근거**(파랑 점)를 섹션·색으로 분리. 판매자 표기는 항목마다 원문 링크, 리뷰는 요약 포인트마다 언급 수 + 원문 인용 펼치기.
- **확인되지 않은 조건**(노랑)은 별도 섹션 — 판매자 표기와 리뷰 어디에서도 확인 못 한 항목.
- 리뷰 요약이 없으면 지어내지 않고 “아직 리뷰 요약이 없어요”를 표시.

### ⑤ 구매 연결 (미리보기)
- 옵션·수량을 고르면 상품가×수량 + 배송비 = 결제 예상 금액. 배송비 미확인이면 “확정 불가”.
- 이동은 기존 `/go/{sid}/{rank}` (직전 추천 결과 URL 로만 리다이렉트 + 클릭 로그). 예시 데이터는 버튼 비활성.
- 유료 소개 상품은 추천 순위(`last_items`)에 없으므로 판매처 URL 로 직접 이동하고 `rel="sponsored"` 를 붙인다.

### 유료 소개 분리
- `is_sponsored` 카드는 어떤 블록에서 오든 adapter 가 빼내 `sponsored_list` 로 모은다.
- 위치는 일반 추천과 안내문 **뒤**, 다음 행동 칩 앞. 점선 테두리 + 보라색 “유료 소개” 라벨 + “순위에 반영하지 않아요” 문구.

## 5. 블록 계약

### 5-1. 기존 블록 (presenter.py 그대로 사용)
`text{md}` · `notice{md,tone}` · `verdict{md}` · `chips{items,mode}` · `clarify_form{questions,submit}` ·
`product_list{items}` · `comparison_pair{pairs[{cards,chips}]}` · `shipping_options{title,note,options,items}`

첨부 예시 형식(`text{text}`, `clarify_form{title,options}`, `shipping_options{estimated_days,total_landed_cost,agency}`)도 adapter 가 받아 준다.

### 5-2. 제안 블록 / 필드 (백엔드 추가 요청)

| 위치 | 필드 | 용도 | 없을 때 화면 |
|---|---|---|---|
| `clarify_form` | `layout: "sequential"`, 질문별 `why`, 선택지별 `hint`, `skippable` | ② 순차 질문 | 순차 표시는 기본값, why/hint 생략 |
| `card()` | `weight_g` | ③ 중량·100g당 | 상품명에서 “1.2kg/800g” 추정, 없으면 “표기 없음” |
| `card()` | `delivery_terms` | ③ 배송 | “도착 예정일 표기 없음” + 미확인 칩 |
| `card()` | `is_sponsored` | 유료 분리 | 일반 추천으로 취급 (현재 recommender 가 유료 상품을 랭킹에서 제외하므로 영향 없음) |
| `card()` | `detail{sellerFacts[], reviews{points[], source}, options[]}` | ④⑤ | 규격·상품가·배송비만 판매자 표기로, 리뷰는 “요약 없음” |
| 새 블록 | `candidate_compare{conditions[], candidates[]}` | ③ | 카드 3개 이상인 `comparison_pair` 를 adapter 가 변환 |
| 새 블록 | `sponsored_list{note, items[]}` | 유료 분리 | `is_sponsored` 카드에서 adapter 가 생성 |

권장 엔드포인트: `GET /api/product/{sid}/{rank}` → `ProductDetail` (상세 패널을 열 때 지연 로딩. 리뷰 요약은 무겁기 때문에 채팅 응답에 넣지 않는 편이 낫다).

## 6. 실제 API 연결 점검 결과 (2026-10-20, 예시몰 데이터)

`DialogueManager.handle()` 실제 응답으로 확인한 사항:

1. **대화 순서 차이** — 현재 서버는 “추천 먼저, 조건은 뒤에” (상품명만 있으면 바로 추천 + 하단 질문 2개). 새 흐름 ②는 “선택에 영향을 주는 질문을 먼저”다.
   → 제안: 의도에 필수 슬롯(인원·조리법 등 카테고리별)이 비어 있으면 `stage=clarify` 로 `clarify_form` 만 먼저 반환. UI 는 두 순서 모두 그대로 동작한다.
2. **목록 중복** — rankable 후보가 0개면 `recommendation_blocks()` 가 같은 카드를 `product_list` 로 두 번 내려준다 (`elif cards:` 분기 + not_rankable 목록). adapter 에서 중복을 제거했고, 서버 쪽은 `elif cards:` 분기 삭제를 권장.
3. 예시몰 데이터는 전부 `rankable=false` 라 ③ 비교표 대신 “참고용 후보” 목록으로 보인다. 실 마켓 키를 켜거나 rankable 후보가 3개 이상이면 비교표로 바뀐다.
4. 요청 형식은 그대로 호환: `{"session_id":null,"message":"…"}`, `{"session_id":"…","answers":{"budget":"30000-50000","mall":"any"}}`.

## 7. 반응형·접근성

- 기준 폭: 모바일 390px, PC 1280px에서 화면 확인. 모바일은 가로 스크롤 없음, 입력창은 safe-area 고려.
- 선택지는 `role="radio"`/`aria-checked`, 단계 표시는 `aria-current="step"`, 상세 패널은 `role="dialog"` + Esc 닫기.
- 서버 문구는 **굵게**·목록만 해석하고 HTML 은 해석하지 않는다 (주입 방지).
- `prefers-reduced-motion` 에서 애니메이션 끔.

## 8. 다음 단계

1. 서버: ① 필수 조건 선질문 모드, ② `weight_g`·`delivery_terms`·`is_sponsored` 를 `card()` 에 추가, ③ product_list 중복 분기 정리
2. `GET /api/product/{sid}/{rank}` + 리뷰 요약 파이프라인 (요약 포인트마다 원문 리뷰 ID 보관)
3. 레시피: `/api/recipe/plan` 결과(`confirmed_missing`, `needs_question`)를 ② 질문 → ③ 부족 재료 비교로 연결
4. 빌드 결과(`dist/`)를 FastAPI 정적 경로로 서빙하거나 기존 `consumer/web/index.html` 대체
