from __future__ import annotations

import re
from typing import Protocol

from shared.models import Offer

# 검색 API가 평점·후기 수·도착 예정일을 제공하지 않는 판매처 (쿠팡 파트너스·네이버 쇼핑 검색).
# 이런 값은 '미확인 경고'가 아니라 '판매처에서 확인' 안내로 보여준다.
NO_RATING_MALLS = {"coupang", "naver"}

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

# 계층 속성 (HASTE, arXiv:2610.17368) — 품목 → 품종 → 등급 → 규격
_ITEM_WORDS = ("사과", "배추", "배", "감귤", "딸기", "한우", "전복", "참기름", "들기름", "견과", "김", "멸치",
               "곶감", "꿀", "쿠키", "홍삼", "비타민", "유산균", "수건", "타월", "텀블러", "핸드크림")
_VARIETY_WORDS = ("홍로", "부사", "시나노골드", "감홍", "샤인머스캣", "설향", "금실", "대봉", "단감")
_GRADE_RE = re.compile(r"(특|상|중|하)\s*등급|1\+|프리미엄급")
_SPEC_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:kg|g|ml|l|개입|개|입|팩|봉|구|병|박스)\b", re.IGNORECASE)


def parse_hierarchy(title: str) -> dict:
    """상품명에서 품목·품종·등급·규격을 추정한다. 추정 불가 항목은 None."""
    t = title or ""
    item = next((w for w in _ITEM_WORDS if w in t), None)
    variety = next((w for w in _VARIETY_WORDS if w in t), None)
    g = _GRADE_RE.search(t)
    grade = g.group(0) if g else None
    specs = _SPEC_RE.findall(t)
    spec_grade = " ".join(specs) if specs else None
    return {"item": item, "variety": variety, "grade": grade, "spec_grade": spec_grade}


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
