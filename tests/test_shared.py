from shared.engines.recommender import Recommender
from shared.models import Intent, Offer
from shared.nlu import rule_nlu


def test_budget_parsing():
    assert rule_nlu.parse_budget("5만원 이하") == (None, 50000)
    assert rule_nlu.parse_budget("1만~2만원") == (10000, 20000)
    assert rule_nlu.parse_budget("2만원 이상") == (20000, None)
    assert rule_nlu.parse_budget("10만원대 한우") == (100000, 199999)


def test_action_priority_follows_food_nlu_rules():
    assert rule_nlu.parse("쿠팡에서 견과류 선물세트 최저가").action == "recommend_in_mall"
    assert rule_nlu.parse("글루텐 없는 과자 추천").action == "allergy"
    assert rule_nlu.parse("부모님 추석 선물 견과류").action == "recommend_gift"


def test_product_terms_keep_words_intact():
    assert rule_nlu.parse("쿠팡에서 두바이 쫀득쿠키 추천해줘").slots["product"] == "두바이 쫀득쿠키"
    i = rule_nlu.parse("캠핑 가는데 숯불에 구워 먹을 고기 세 개만")
    assert i.slots["quantity"] == 3 and "고기" in i.slots["product"]


def test_unknown_shipping_is_not_free():
    o = Offer(mall="naver", title="x", price=10000, shipping_fee=None)
    assert o.total_price is None


def test_budget_filter_and_badges():
    r = Recommender()
    q, items = r.recommend(Intent(slots={"product": "두바이 쫀득쿠키", "budget_max": 20000}))
    assert items and all((x.offer.total_price or x.offer.price) <= 20000 for x in items)
    assert "1순위 추천" in items[0].badges
