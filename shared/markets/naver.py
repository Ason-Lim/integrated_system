"""네이버 쇼핑 검색 API (food-nlu/naver_api.py 이식).

※ 2026-07-31 네이버가 쇼핑 검색 API(shop.json)를 종료했다 (SE05 '존재하지 않는 검색 api', NAVER API HUB 대체 없음).
   NAVER_ENABLED=1 이어도 결과가 오지 않는다. 네이버 상품은 쇼핑커넥트 등록부(수작업)로만 다룬다.

변경점: Offer 모델로 정규화, 배송비는 API가 주지 않으므로 None(미확인)으로 둔다.
(기존 코드는 0원으로 넣어 '무료배송'처럼 보일 위험이 있었음)
"""
from __future__ import annotations

import os

import requests

from shared.markets.base import parse_units, strip_html
from shared.models import Offer

BASE = "https://openapi.naver.com/v1/search/shop.json"


class NaverShoppingAdapter:
    code = "naver"

    def __init__(self, enabled: bool | None = None):
        self.cid = os.getenv("NAVER_CLIENT_ID")
        self.csec = os.getenv("NAVER_CLIENT_SECRET")
        flag = enabled if enabled is not None else os.getenv("NAVER_ENABLED", "0") == "1"
        self.enabled = bool(flag and self.cid and self.csec)

    def search(self, query: str, limit: int = 20, sort: str = "sim") -> list[Offer]:
        if not self.enabled:
            return []
        r = requests.get(BASE, timeout=10, params={
            "query": query, "display": min(limit, 100), "start": 1, "sort": sort},
            headers={"X-Naver-Client-Id": self.cid, "X-Naver-Client-Secret": self.csec})
        r.raise_for_status()
        out = []
        for it in r.json().get("items", []):
            title = strip_html(it.get("title"))
            unit, weight = parse_units(title)
            out.append(Offer(
                mall="naver", mall_label=strip_html(it.get("mallName")) or "네이버",
                mall_product_id=str(it.get("productId")), title=title,
                brand=strip_html(it.get("brand")) or None, category=it.get("category2") or it.get("category1"),
                price=int(it.get("lprice") or 0), shipping_fee=None,
                url=it.get("link"), image_url=it.get("image"),
                unit_count=unit, weight_g=weight, raw=it))
        return out
