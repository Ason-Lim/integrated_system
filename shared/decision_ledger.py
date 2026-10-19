"""Decision Freshness Ledger (shadow) — arXiv:2610.18126 축소 구현.

추천 시점(decision_time)과 실행 예정 시점(intended_action_time) 사이에
가격·재고·배송일·쿠폰 등이 바뀌면 기존 추천을 재검토 대상으로 표시한다.
production 랭킹 규칙은 바꾸지 않고, 무효화 탐지율/불필요 재평가율 측정용으로만 쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from shared.models import Intent, Offer, now_utc

DEFAULT_WATCH = ("price", "shipping_fee", "stock", "delivery_date", "coupon")


@dataclass
class LedgerEntry:
    decision_time: datetime
    evidence_time: datetime
    intended_action_time: datetime
    revision_deadline: datetime
    watch_conditions: list[str] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)


def _snapshot(offer: Offer) -> dict:
    return {"price": offer.price, "shipping_fee": offer.shipping_fee,
            "total_price": offer.total_price, "service_date": offer.service_date,
            "rankability": offer.rankability}


def open_entry(intent: Intent, offers: list[Offer], *, action_delay: timedelta = timedelta(hours=24),
               revision_window: timedelta = timedelta(hours=12)) -> LedgerEntry:
    """추천 시점에 ledger 엔트리를 만든다. intent 에 타임스탬프를 채워 넣는다."""
    now = now_utc()
    intent.decision_time = intent.decision_time or now
    intent.evidence_time = intent.evidence_time or now
    intent.intended_action_time = intent.intended_action_time or (now + action_delay)
    intent.revision_deadline = intent.revision_deadline or (now + revision_window)
    intent.watch_conditions = intent.watch_conditions or list(DEFAULT_WATCH)
    return LedgerEntry(
        decision_time=intent.decision_time, evidence_time=intent.evidence_time,
        intended_action_time=intent.intended_action_time, revision_deadline=intent.revision_deadline,
        watch_conditions=list(intent.watch_conditions),
        snapshot={o.mall_product_id or o.title: _snapshot(o) for o in offers},
    )


def invalidated(entry: LedgerEntry, current: list[Offer], *, now: datetime | None = None) -> list[str]:
    """watch_conditions 중 실제로 바뀐 상품 키를 돌려준다. 빈 리스트면 유효."""
    now = now or now_utc()
    if now > entry.intended_action_time:
        return ["action_window_expired"]
    changed: list[str] = []
    for o in current:
        key = o.mall_product_id or o.title
        prev = entry.snapshot.get(key)
        if not prev:
            continue
        cur = _snapshot(o)
        for cond in entry.watch_conditions:
            if cond == "price" and prev.get("price") != cur.get("price"):
                changed.append(key)
                break
            if cond == "shipping_fee" and prev.get("shipping_fee") != cur.get("shipping_fee"):
                changed.append(key)
                break
            if cond == "delivery_date" and prev.get("service_date") != cur.get("service_date"):
                changed.append(key)
                break
    return changed
