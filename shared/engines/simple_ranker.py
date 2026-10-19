"""기본 랭커 — commerce_ai 엔진이 연결되지 않았을 때 사용.

점수 = 관련도(0~40) + 평점(0~20) + 후기량 log(0~20) + 가격 적합도(0~20)
값이 없는 항목은 0점이 아니라 '미반영'으로 두고 미확인 목록에 남긴다.
"""
from __future__ import annotations

import math

from shared.models import Intent, Offer, ScoredOffer


def relevance(query: str, title: str) -> float:
    toks = [t for t in query.split() if t]
    if not toks:
        return 0.5
    return sum(1 for t in toks if t in title) / len(toks)


def price_fit(price: int, lo: int | None, hi: int | None, priority: str | None,
              pmin: int, pmax: int) -> float:
    if hi and price > hi:
        return 0.0
    if lo and price < lo:
        return 0.3
    if priority in {"price", "value"} and pmax > pmin:
        return 1 - (price - pmin) / (pmax - pmin)
    return 0.6


def rank(offers: list[Offer], intent: Intent, query: str) -> list[ScoredOffer]:
    if not offers:
        return []
    s = intent.slots
    prices = [o.total_price or o.price for o in offers]
    pmin, pmax = min(prices), max(prices)
    out = []
    for o in offers:
        ev, un = [], []
        score = 40 * relevance(query, o.title)
        if o.rating is not None:
            score += 20 * max(0.0, (o.rating - 3.0) / 2.0)
            ev.append(f"평점 {o.rating:.1f}")
        else:
            un.append("평점")
        if o.review_count:
            score += min(20.0, 20 * math.log10(o.review_count + 1) / 4)
            ev.append(f"후기 약 {o.review_count:,}개")
        else:
            un.append("후기 수")
        price = o.total_price or o.price
        score += 20 * price_fit(price, s.get("budget_min"), s.get("budget_max"), s.get("priority"), pmin, pmax)
        if o.shipping_fee is None:
            un.append("배송비")
        if s.get("priority") == "quality" and o.original_price is None and (o.rating or 0) >= 4.7:
            score += 3
        so = ScoredOffer(offer=o, score=round(score, 1), evidence=ev, unverified=un)
        if o.rankability == "NOT_RANKABLE":
            so.rankable = False
            so.not_rankable_reason = "판매처 근거로 구매조건 확정 불가"
        out.append(so)
    out.sort(key=lambda x: (not x.rankable, -x.score))
    return out
