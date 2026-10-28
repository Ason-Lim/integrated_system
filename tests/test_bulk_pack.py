"""쿠팡 검색 API가 묶음 옵션(20개 548,000원)을 대표로 줄 때 (2026-10-28 과메기 화면)."""
from shared.engines import simple_ranker
from shared.markets.base import parse_units
from shared.models import Intent, Offer
from shared.nlu import rule_nlu


def offer(i, title, price):
    unit, weight = parse_units(title)
    return Offer(mall="coupang", mall_product_id=str(i), title=title, price=price, shipping_fee=0, url="u",
                 unit_count=unit, weight_g=weight)


OFFERS = [
    offer(1, "포항 구룡포 햇과메기 덕장직영 도매 식당용 반손질 과메기 단품, 20개, 반손질 과메기 20미 40쪽", 548000),
    offer(2, "포항 구룡포 제철 꽁치 완전손질 햇과메기, 1개, 5미 (10쪽 / 1~2인용) + 야채풀세트", 18900),
    offer(3, "포항 구룡포 해풍 햇 과메기, 1개, 꽁치 20미 단품", 34800),
]


def test_first_timer_question_sets_small_pack():
    s = rule_nlu.parse("과메기 처음 사보는데 비린내 없이 먹는 법이랑 같이 살 거 알려줘").slots
    assert s.get("small_pack") and not s.get("bulk_ok")
    assert rule_nlu.parse("식당용 과메기 대량으로").slots.get("bulk_ok")


def test_bulk_pack_goes_last_and_is_labeled():
    out = simple_ranker.rank(OFFERS, Intent(action="recommend_food", slots={"product": "과메기"}), "과메기")
    assert out[-1].offer.mall_product_id == "1"
    assert any("20개 묶음 (개당 약 27,400원)" in e for e in out[-1].evidence)


def test_bulk_allowed_when_user_wants_it():
    out = simple_ranker.rank(OFFERS, Intent(action="recommend_food", slots={"product": "과메기", "bulk_ok": True}), "과메기")
    bulk = next(x for x in out if x.offer.mall_product_id == "1")
    small = next(x for x in out if x.offer.mall_product_id == "3")
    assert bulk.score >= small.score - 1       # 감점 없음 (관련도 차이만)
