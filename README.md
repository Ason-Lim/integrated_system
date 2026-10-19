# v3 보완판

레시피·자연어·근거 충분성 보완판입니다. 상세한 구현/연결 대기 구분과 실행 방법은 [아키텍처](docs/ARCHITECTURE.md)를 확인하세요.
레시피 API 샘플: `examples/recipe_plan.json`. 원본 프로젝트를 덮어쓰지 말고 별도 폴더에서 실행하세요.

# commerce_platform

commerce_ai(추천 엔진) + food-nlu(자연어·마켓 API)를 합친 **소비자 대화형 추천 앱**과,
별도로 분리한 **B2B 입찰 내부 콘솔**(선물 입찰 모니터·트렌드 분석·조건 분석·견적요청서·제안서 작성)입니다.
B2B gift-monitor(smallbiz-monitor `/b2b_gift`)와 gift_trend_analyzer 는 B2B 콘솔 안으로 통합했고, 소상공인 지원사업 모니터링은 제외했습니다. 구조는 `docs/ARCHITECTURE.md` 참고.

## 설치

```bash
cd commerce_platform
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 키 없이도 '예시 데이터'로 바로 동작
```

## 실행

```bash
./run_consumer.sh             # http://127.0.0.1:8000  소비자 추천
./run_b2b.sh                  # http://127.0.0.1:8100  B2B 콘솔 · /monitor 선물 입찰 모니터
python -m pytest -q           # 테스트 26개

# 기존 smallbiz-monitor DB 의 선물 입찰 23건 가져오기 ('미검증 기존 데이터'로 표시됨)
python scripts/import_legacy_gift_db.py ~/anti_online/data/smallbiz_programs.db
# 나라장터 수집 (G2B_SERVICE_KEY 필요) — cron/GitHub Actions 는 deploy/weekly_bid_collect.yml
python scripts/collect_bids.py --days 7
```

## 기존 시스템 연결 (.env)

| 변수 | 의미 |
|---|---|
| `COMMERCE_AI_PATH=/Users/mom/commerce_ai_generator` | 랭킹을 commerce_ai V8 파이프라인에 위임 (기존 DB 설정 그대로 필요) |
| `FOOD_NLU_PATH=/Users/mom/food-nlu` + `DATABASE_URL` + `LLM_PROVIDER=ollama` | food-nlu LLM NLU 사용 |
| `COUPANG_ACCESS_KEY` 등 / `NAVER_ENABLED=1` | 실 마켓 검색 (켜지면 예시몰 자동 비활성) |
| `G2B_SERVICE_KEY` | 나라장터 입찰공고정보서비스 키 (공공데이터포털) |
| `B2B_BID_SOURCE_URL` | (선택) 추가 공고 JSON 피드 |
| `COMPANY_PROFILE` | 제안서 회사 정보 JSON (기본 `b2b/data/company_profile.json`) |

## 폴더

```
shared/    공통 코어 — nlu · markets · engines · store · llm
consumer/  공개 추천 앱 — dialogue(상태머신) · presenter(화면 블록) · web/index.html
b2b/       내부 콘솔 — console · bids · request_parser · evidence · sourcing · costing · rfq · report · proposal
           gift_monitor/ (collectors · classify · trends · checkpoints) · web/console.html · web/monitor.html
           data/evidence_bundle_v2.json (commerce_ai data/b2b_evidence/v2 번들 사본), company_profile.json
scripts/   import_legacy_gift_db.py · collect_bids.py      deploy/ weekly_bid_collect.yml
tests/     pytest
```
