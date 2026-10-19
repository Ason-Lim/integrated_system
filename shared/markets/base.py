from __future__ import annotations

import re
from typing import Protocol

from shared.models import Offer

MALL_LABELS = {
    "coupang": "쿠팡", "naver": "네이버", "emart": "이마트", "ssg": "SSG",
    "marketkurly": "컬리", "sample": "예시몰",
}


class MarketAdapter(Protocol):
    code: str
    enabled: bool

    def search(self, query: str, limit: int = 20) -> list[Offer]: ...


def strip_html(s: str | None) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    for a, b in [("&quot;", '"'), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'")]:
        s = s.replace(a, b)
    return s.strip()


_UNIT_RE = re.compile(r"(\d+)\s*(?:개입|개|입|팩|봉|구)\b")
_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g)\b", re.IGNORECASE)


def parse_units(title: str) -> tuple[int | None, float | None]:
    """상품명에서 개입 수·중량(g)을 추정. 추정치이므로 화면에는 '약'으로만 쓴다."""
    unit = None
    m = _UNIT_RE.search(title or "")
    if m:
        unit = int(m.group(1))
    weight = None
    w = _WEIGHT_RE.findall(title or "")
    if w:
        v, u = w[-1]
        weight = float(v) * (1000 if u.lower() == "kg" else 1)
    return unit, weight
