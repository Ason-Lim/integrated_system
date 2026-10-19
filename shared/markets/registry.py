"""마켓 어댑터 묶음 — 여러 몰 검색 결과를 합치고 중복을 제거한다."""
from __future__ import annotations

import logging

from shared.config import Settings, get_settings
from shared.markets.coupang import CoupangPartnersAdapter
from shared.markets.naver import NaverShoppingAdapter
from shared.markets.sample import SampleMarketAdapter
from shared.models import Offer

log = logging.getLogger(__name__)


class MarketRegistry:
    def __init__(self, settings: Settings | None = None, adapters=None):
        s = settings or get_settings()
        self.adapters = adapters if adapters is not None else [
            CoupangPartnersAdapter(), NaverShoppingAdapter(s.naver_enabled),
        ]
        # 실 API 가 하나도 없을 때만 예시몰 사용 (실데이터와 섞지 않는다)
        if adapters is None and not any(a.enabled for a in self.adapters) and s.sample_market_enabled:
            self.adapters.append(SampleMarketAdapter(True))

    @property
    def active(self) -> list[str]:
        return [a.code for a in self.adapters if a.enabled]

    def search(self, query: str, *, malls: list[str] | None = None, limit: int = 20) -> list[Offer]:
        out: list[Offer] = []
        for a in self.adapters:
            if not a.enabled:
                continue
            if malls and a.code not in malls and a.code != "sample":
                continue
            try:
                out += a.search(query, limit=limit)
            except Exception as e:  # 한 몰 장애가 전체를 막지 않게
                log.warning("market %s failed: %s", a.code, e)
        return dedupe(out)


def dedupe(offers: list[Offer]) -> list[Offer]:
    seen: set[tuple] = set()
    res = []
    for o in offers:
        key = (o.mall, o.mall_product_id or o.title)
        if key in seen:
            continue
        seen.add(key)
        res.append(o)
    return res
