"""쿠팡 파트너스 검색 API (food-nlu/coupang_api.py 이식, HMAC 서명 동일)."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from shared.markets.base import parse_units
from shared.models import Offer

DOMAIN = "https://api-gateway.coupang.com"
SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"


class CoupangPartnersAdapter:
    code = "coupang"

    def __init__(self):
        self.access = os.getenv("COUPANG_ACCESS_KEY")
        self.secret = os.getenv("COUPANG_SECRET_KEY")
        self.partner = os.getenv("COUPANG_PARTNER_ID")
        self.enabled = bool(self.access and self.secret and self.partner)

    def _auth(self, method: str, path: str, query: str) -> str:
        dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
        sig = hmac.new(self.secret.encode(), f"{dt}{method}{path}{query}".encode(),
                       hashlib.sha256).hexdigest()
        return (f"CEA algorithm=HmacSHA256, access-key={self.access}, "
                f"signed-date={dt}, signature={sig}")

    def search(self, query: str, limit: int = 10) -> list[Offer]:
        if not self.enabled:
            return []
        qs = urlencode({"keyword": query, "limit": max(1, min(int(limit), 10))})
        r = requests.get(f"{DOMAIN}{SEARCH_PATH}?{qs}", timeout=10, headers={
            "Authorization": self._auth("GET", SEARCH_PATH, qs),
            "Content-Type": "application/json;charset=UTF-8"})
        r.raise_for_status()
        out = []
        for it in r.json().get("data", {}).get("productData", []):
            title = it.get("productName", "")
            unit, weight = parse_units(title)
            free = it.get("isFreeShipping")
            out.append(Offer(
                mall="coupang", mall_label="쿠팡", mall_product_id=str(it.get("productId")),
                title=title, category=it.get("categoryName"),
                price=int(it.get("productPrice") or 0),
                shipping_fee=0 if free is True else None,       # 무료배송 표시가 있을 때만 0
                url=it.get("productUrl"), image_url=it.get("productImage"),
                unit_count=unit, weight_g=weight, raw=it))
        return out
