"""프론트엔드(Next.js) 개발자용 — comparison_pair / shipping_options 블록의 JSON 스키마 출력.

실행:
    pytest tests/test_presenter_schema.py -s

`-s` 옵션으로 print 출력을 확인한다. 각 테스트는 실제 presenter 함수를 호출해
블록의 `data` 구조를 그대로 덤프하므로, 프론트는 이 JSON 을 기준으로 화면을 그린다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from consumer import presenter
from shared.logistics.shipping_agency import LandedCost
from shared.models import Intent, Offer, ScoredOffer


def _offer(title: str, price: int, *, mall: str = "coupang", pid: str = "p1",
           shipping: int | None = 0, unit: int | None = None, count: int | None = None) -> Offer:
    return Offer(
        mall=mall, mall_product_id=pid, title=title, price=price,
        shipping_fee=shipping, unit_price=unit, unit_count=count,
        url=f"https://example.com/{pid}", observed_at=datetime.now(timezone.utc),
    )


def _scored(o: Offer, *, reason: str = "", evidence: list[str] | None = None,
            unverified: list[str] | None = None) -> ScoredOffer:
    return ScoredOffer(
        offer=o, score=0.9, reason=reason, evidence=evidence or [],
        unverified=unverified or [], badges=["최저가"],
        decision={"status": "RANKABLE"},
    )


def _dump(name: str, data: dict) -> None:
    print(f"\n===== {name} =====")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def test_comparison_pair_schema():
    """comparison_pair 블록: pairs[].cards[] 에 카드 2장 + reasoning + follow_up 칩."""
    items = [
        _scored(_offer("견과류 선물세트 A", 29900, pid="a", unit=2990, count=10),
                reason="가격·후기 균형이 좋아요", evidence=["리뷰 1,200건", "무료배송"]),
        _scored(_offer("견과류 선물세트 B", 34900, mall="naver", pid="b"),
                evidence=["리뷰 3,400건"], unverified=["배송비"]),
    ]
    block = presenter.Block(type="comparison_pair",
                            data={"pairs": presenter.comparison_pair(items)})
    _dump("comparison_pair", block.model_dump())

    data = block.data
    assert isinstance(data["pairs"], list) and data["pairs"]
    pair = data["pairs"][0]
    assert set(pair) >= {"pair_index", "cards", "compare", "chips"}
    assert len(pair["cards"]) == 2
    card = pair["cards"][0]
    # 프론트가 의존하는 카드 필드
    for key in ("rank", "title", "price", "shipping_fee", "total", "unit_price",
                "badges", "reasoning", "follow_up", "source", "observed", "stale",
                "url", "is_sample", "cta"):
        assert key in card, f"카드에 {key} 필드가 없습니다"
    assert isinstance(card["follow_up"], list)
    if card["follow_up"]:
        assert set(card["follow_up"][0]) == {"label", "value"}


def test_shipping_options_schema_with_estimate(monkeypatch):
    """shipping_options 블록: items[].estimate 에 배송비·기간·최종 견적이 포함된 형태."""
    def fake_landed(*, product_usd, req, **kw):
        return LandedCost(
            product_krw=round(product_usd * 1350),
            shipping_krw=18000, agency_fee_krw=4000,
            duty_krw=0, vat_krw=0, total_krw=round(product_usd * 1350) + 22000,
            eta_days_min=5, eta_days_max=9, agency="maltese",
            fx_krw_per_usd=1350.0,
            notes=["면세 한도(150 USD) 이내로 관세·부가세를 반영하지 않았습니다."],
        )

    monkeypatch.setattr(presenter, "total_landed_cost", fake_landed)

    items = [_scored(_offer("해외 직구 상품", 50000, mall="amazon", pid="x"))]
    block = presenter._shipping_options_block(items)
    _dump("shipping_options (estimate 포함)", block.model_dump())

    data = block.data
    assert set(data) >= {"title", "note", "options", "items"}
    assert isinstance(data["options"], list) and data["options"]
    assert set(data["options"][0]) == {"id", "label", "desc"}
    entry = data["items"][0]
    assert set(entry) >= {"title", "mall", "estimate"}
    est = entry["estimate"]
    for key in ("agency", "shipping_krw", "agency_fee_krw", "duty_krw", "vat_krw",
                "total_krw", "eta_days_min", "eta_days_max", "fx_krw_per_usd", "notes"):
        assert key in est, f"estimate 에 {key} 필드가 없습니다"


def test_shipping_options_schema_without_estimate(monkeypatch):
    """API 키 미설정 등으로 견적 계산이 실패하면 items[].estimate 가 생략된다."""
    from shared.logistics.shipping_agency import AgencyUnavailable

    def fail(*a, **k):
        raise AgencyUnavailable("maltese: API 키/베이스 URL 미설정")

    monkeypatch.setattr(presenter, "total_landed_cost", fail)

    items = [_scored(_offer("해외 직구 상품", 50000, mall="amazon", pid="x"))]
    block = presenter._shipping_options_block(items)
    _dump("shipping_options (estimate 없음)", block.model_dump())

    entry = block.data["items"][0]
    assert "estimate" not in entry
    assert "예상 견적은 표시할 수 없어요" in block.data["note"]
