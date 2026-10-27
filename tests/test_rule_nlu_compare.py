"""정보·비교 질문 의도와 검색어 정제 회귀 테스트 (2026-10-22 '감홍사과' 화면 점검).

화면에서 "감홍사과 처음 사보는데 문경 거랑 다른 산지랑 뭐가 달라?" 가
recommend_food / 검색어 "감홍사과 처음 문경 거랑" 으로 처리되어 쿠팡이
섬유유연제·칫솔·화장품을 돌려준 문제를 막는다.
"""
from consumer import presenter
from shared.engines.recommender import Recommender, relevant_offers
from shared.markets.registry import MarketRegistry
from shared.models import Intent, Offer
from shared.nlu import rule_nlu

SCREENSHOT_Q = "감홍사과 처음 사보는데 문경 거랑 다른 산지랑 뭐가 달라?"


# ── rule_nlu ────────────────────────────────────────────────
def test_screenshot_question_is_compare_info_with_clean_query():
    i = rule_nlu.parse(SCREENSHOT_Q)
    assert i.action == "compare_info"
    assert i.slots["product"] == "감홍사과 문경"
    assert i.slots["compare_axis"] == "origin"
    assert "budget_max" not in i.slots and "budget_min" not in i.slots


def test_compare_variants():
    i = rule_nlu.parse("청송 사과랑 문경 사과 차이가 뭐야?")
    assert i.action == "compare_info" and i.slots["product"] == "청송 사과 문경"
    i = rule_nlu.parse("감홍이랑 부사 중에 뭐가 더 나아?")
    assert i.action == "compare_info" and i.slots["product"] == "감홍 부사"
    assert rule_nlu.parse("감홍사과 품종 차이 알려줘").slots["compare_axis"] == "variety"


def test_particles_and_filler_removed():
    for t in ("처음", "거랑", "산지", "뭐가", "달라", "사과랑"):
        assert t not in rule_nlu.parse(SCREENSHOT_Q).slots["product"].split()


def test_purchase_requests_are_not_compare():
    assert rule_nlu.parse("문경 감홍사과 추천해줘").action == "recommend_food"
    i = rule_nlu.parse("다른 사과 추천해줘")       # '다른' 단독은 비교 신호가 아님
    assert i.action == "recommend_food" and i.slots["product"] == "사과"
    assert rule_nlu.parse("홍로사과").slots["product"] == "홍로사과"
    # 기존 ACTION 우선순위 유지
    assert rule_nlu.parse("쿠팡에서 견과류 선물세트 최저가").action == "recommend_in_mall"
    assert rule_nlu.parse("부모님 추석 선물 견과류").action == "recommend_gift"


def test_compare_wins_over_mall_but_keeps_mall_slot():
    i = rule_nlu.parse("쿠팡에서 감홍이랑 부사 뭐가 달라?")
    assert i.action == "compare_info" and i.slots["mall"] == "coupang"


# ── 쿠팡 무관 상품 차단 (recommender) ─────────────────────────
JUNK = [
    Offer(mall="coupang", mall_product_id="1", title="다우니 퍼퓸 쥬얼 에메랄드 브리즈 향기부스터", price=27900),
    Offer(mall="coupang", mall_product_id="2", title="오랄비 크로스액션 탁월한 세정력 칫솔", price=19950),
    Offer(mall="coupang", mall_product_id="3", title="라로슈포제 시카플라스트 B5+ 밤 100ml 세트", price=41000),
]
APPLE = Offer(mall="coupang", mall_product_id="9", title="문경 감홍 사과 5kg 산지직송", price=39000, shipping_fee=0)


class _FakeCoupang:
    code, enabled = "coupang", True

    def __init__(self, offers):
        self.offers = offers

    def search(self, query, limit=10):
        return list(self.offers)


def _rec(offers):
    return Recommender(markets=MarketRegistry(adapters=[_FakeCoupang(offers)]))


def test_relevant_offers_ignores_spacing():
    kept = relevant_offers(JUNK + [APPLE], Intent(slots={"product": "감홍사과 문경"}))
    assert kept == [APPLE]          # '감홍사과' ↔ '감홍 사과' 띄어쓰기 차이 허용


def test_unrelated_market_results_are_dropped():
    r = _rec(JUNK + [APPLE])
    _, items = r.recommend(Intent(action="compare_info", slots={"product": "감홍사과 문경"}))
    assert [x.offer.mall_product_id for x in items] == ["9"]
    assert r.last_dropped_irrelevant == 3


def test_all_unrelated_returns_empty_not_fallback():
    r = _rec(JUNK)
    _, items = r.recommend(Intent(slots={"product": "감홍사과 문경"}))
    assert items == []


# ── 화면: 비교 질문에는 예산을 묻지 않는다 ─────────────────────
def _form_questions(blocks):
    return [q["id"] for b in blocks if b.type == "clarify_form" for q in b.data["questions"]]


def test_compare_info_skips_budget_question():
    intent = Intent(action="compare_info", slots={"product": "감홍사과 문경", "compare_axis": "origin"})
    _, items = _rec([APPLE]).recommend(intent)
    blocks = presenter.recommendation_blocks(intent, items, active_malls=["coupang"])
    assert "budget" not in _form_questions(blocks)
    assert "산지 비교" in blocks[0].data["md"]


def test_compare_info_empty_result_has_no_budget_form():
    intent = Intent(action="compare_info", slots={"product": "감홍사과 문경"})
    blocks = presenter.recommendation_blocks(intent, [], active_malls=["coupang"])
    assert "찾지 못했어요" in blocks[0].data["md"] and not _form_questions(blocks)
