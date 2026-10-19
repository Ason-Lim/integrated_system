"""장바구니 모델 — 국내/해외 상품을 함께 담고 결제 분기에 필요한 정보를 제공한다.

해외 상품은 `is_overseas=True` 로 표시하며, 최종 견적(LandedCost)을 함께 보관할 수 있다.
장바구니 단위로 국내/해외가 섞이면 결제는 상품별로 분기된다(consumer/checkout.py 참고).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from shared.logistics.shipping_agency import LandedCost
from shared.models import Offer


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CartItem(BaseModel):
    """장바구니 항목. 국내 상품은 Offer 만으로 충분하고, 해외 상품은 견적을 덧붙인다."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    offer: Offer
    quantity: int = Field(1, ge=1)
    is_overseas: bool = False
    # 해외 상품일 때만 채워진다. 통화는 KRW 로 환산된 최종 견적.
    landed_cost: LandedCost | None = None
    added_at: datetime = Field(default_factory=_now)

    @property
    def unit_price(self) -> int | None:
        """국내: 실구매가(배송비 포함). 해외: 최종 견적 총액."""
        if self.is_overseas:
            return self.landed_cost.total_krw if self.landed_cost else None
        return self.offer.total_price or self.offer.price

    @property
    def line_total(self) -> int | None:
        unit = self.unit_price
        return None if unit is None else unit * self.quantity


class Cart(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    session_id: str | None = None
    items: list[CartItem] = Field(default_factory=list)
    currency: str = "KRW"
    updated_at: datetime = Field(default_factory=_now)

    def add(self, offer: Offer, *, quantity: int = 1, is_overseas: bool = False,
            landed_cost: LandedCost | None = None) -> CartItem:
        if is_overseas and landed_cost is None:
            raise ValueError("해외 상품은 landed_cost(최종 견적)가 필요합니다.")
        item = CartItem(offer=offer, quantity=quantity, is_overseas=is_overseas,
                        landed_cost=landed_cost)
        self.items.append(item)
        self.updated_at = _now()
        return item

    def remove(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [x for x in self.items if x.id != item_id]
        self.updated_at = _now()
        return len(self.items) != before

    @property
    def has_overseas(self) -> bool:
        return any(x.is_overseas for x in self.items)

    @property
    def has_domestic(self) -> bool:
        return any(not x.is_overseas for x in self.items)

    @property
    def total(self) -> int | None:
        """모든 항목의 합계. 하나라도 가격 미확인이면 None."""
        if not self.items:
            return 0
        totals = [x.line_total for x in self.items]
        if any(t is None for t in totals):
            return None
        return sum(totals)  # type: ignore[arg-type]

    def split(self) -> tuple[list[CartItem], list[CartItem]]:
        """(국내 항목, 해외 항목)으로 분리."""
        domestic = [x for x in self.items if not x.is_overseas]
        overseas = [x for x in self.items if x.is_overseas]
        return domestic, overseas
