"""기본 랭커 — commerce_ai 엔진이 연결되지 않았을 때 사용.

점수 = 관련도(0~40) + 평점(0~20) + 후기량 log(0~20) + 가격 적합도(0~20)
값이 없는 항목은 0점이 아니라 '미반영'으로 두고 미확인 목록에 남긴다.
"""
from __future__ import annotations

import math
import re

from shared.markets.base import NO_RATING_MALLS

from shared.assurance import assess
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


BULK_WORDS = re.compile(r"식당용|업소용|도매|대용량|벌크|업소|대량")


def bulk_info(o: Offer) -> str | None:
    """상품명으로 본 대용량·묶음 여부 ('…, 20개' / '식당용'). 쿠팡 검색 API는 옵션 하나의 가격만 주므로
    묶음 옵션이 대표로 오면 가격이 수십만 원이 된다 (2026-10-28 과메기 20개 548,000원)."""
    if (o.unit_count or 0) >= 10:
        return f"{o.unit_count}개 묶음"
    m = BULK_WORDS.search(o.title or "")
    return f"{m.group(0)} 상품" if m else None


def rank(offers: list[Offer], intent: Intent, query: str) -> list[ScoredOffer]:
    if not offers:
        return []
    s = intent.slots
    prices = [o.total_price or o.price for o in offers]
    pmin, pmax = min(prices), max(prices)
    median = sorted(prices)[len(prices) // 2]
    wants_bulk = s.get("bulk_ok") or (s.get("quantity") or 0) >= 5
    small = s.get("small_pack")
    out = []
    for o in offers:
        ev, un = [], []
        score = 40 * relevance(query, o.title)
        provides_rating = o.mall not in NO_RATING_MALLS   # API가 원래 주지 않는 값은 '미확인'으로 표시하지 않음
        if o.rating is not None:
            score += 20 * max(0.0, (o.rating - 3.0) / 2.0)
            ev.append(f"평점 {o.rating:.1f}")
        elif provides_rating:
            un.append("평점")
        if o.review_count:
            score += min(20.0, 20 * math.log10(o.review_count + 1) / 4)
            ev.append(f"후기 약 {o.review_count:,}개")
        elif provides_rating:
            un.append("후기 수")
        price = o.total_price or o.price
        score += 20 * price_fit(price, s.get("budget_min"), s.get("budget_max"), s.get("priority"), pmin, pmax)
        if o.shipping_fee is None:
            un.append("배송비")
        if s.get("priority") == "quality" and o.original_price is None and (o.rating or 0) >= 4.7:
            score += 3
        # 대용량·묶음: 대량 구매 의도가 없으면 뒤로 (점수 감점 + 근거에 표시)
        bulk = bulk_info(o)
        if bulk:
            if o.unit_count and o.unit_count >= 2:
                ev.append(f"{bulk} (개당 약 {price // o.unit_count:,}원)")
            else:
                ev.append(bulk)
            if not wants_bulk:
                score -= 25 if small else 15
        # 다른 후보보다 지나치게 비싼 상품 (중앙값의 3배 초과)
        if not wants_bulk and median and price > 3 * median:
            score -= 10
        if small and pmax > pmin:      # 처음·소량이면 저렴한 쪽을 조금 더
            score += 5 * (1 - (price - pmin) / (pmax - pmin))
        so = ScoredOffer(offer=o, score=round(score, 1), evidence=ev, unverified=un)
        # 결정 가능성 판정: 총비용/배송비 미확정은 점수 하향이 아니라 랭킹 분리
        so.decision = assess(o)
        if so.decision["status"] != "RANKABLE" or o.rankability == "NOT_RANKABLE":
            so.rankable = False
            so.not_rankable_reason = so.not_rankable_reason or "판매처 근거로 구매조건 확정 불가"
        out.append(so)
    out.sort(key=lambda x: (not x.rankable, -x.score))
    return out
