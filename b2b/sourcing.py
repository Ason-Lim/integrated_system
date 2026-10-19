"""후보 발굴 — 공통 코어(shared)를 '읽기 전용'으로 재사용.

1) 근거 저장소(bundle)  2) 소비자 앱이 쌓은 관측 가격(core.offer_observation)  3) 마켓 검색(shared.markets)
발굴된 상품은 모두 '공개 판매가 관측' 후보이며 견적·공급 확인 전까지 HOLD 로 시작한다.
"""
from __future__ import annotations

import hashlib
from datetime import date

from b2b.evidence import infer_category, upsert_candidate
from b2b.models import BidRequirement, Candidate
from shared import store
from shared.markets.registry import MarketRegistry

CATEGORY_QUERIES = {
    "식품": ["과일 선물세트", "참기름 선물세트", "견과류 선물세트", "한우 선물세트"],
    "건강기능식품": ["홍삼 선물세트", "프로바이오틱스 선물세트"],
    "생활용품": ["타월 선물세트", "핸드크림 선물세트"],
}


def _cid(prefix: str, *parts) -> str:
    return prefix + "-" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def discover(req: BidRequirement, categories: list[str] | None = None, markets: MarketRegistry | None = None,
             per_query: int = 4) -> list[Candidate]:
    markets = markets or MarketRegistry()
    cats = categories or [c.name for c in req.categories]
    floor = req.min_online_price or 0
    found: list[Candidate] = []
    for cat in cats:
        for q in CATEGORY_QUERIES.get(cat, [cat + " 선물세트"]):
            for o in markets.search(q, limit=per_query):
                price = o.total_price or o.price
                if floor and price < floor * 0.8:
                    continue
                c = Candidate(
                    candidate_id=_cid("mkt", o.mall, o.mall_product_id or o.title), supplier=o.mall_label or o.mall,
                    name=o.title, option=None, category=infer_category(o.title) or cat, url=o.url,
                    observed_price=price, price_kind="public_retail", observed_date=o.observed_at.date(),
                    notes=(["예시 데이터 — 실제 상품 아님"] if o.is_sample else []) + ["마켓 검색 관측가 — 견적 아님"],
                    source="market_search", is_sample=o.is_sample)
                found.append(c)
        # 소비자 앱 관측 이력 (실데이터만)
        for row in store.recent_observations(cat, limit=5):
            found.append(Candidate(
                candidate_id=_cid("obs", row["mall"], row["mall_product_id"]), supplier=row["mall"], name=row["title"],
                category=infer_category(row["title"]) or cat, url=row["url"], observed_price=row["price"],
                price_kind="public_retail", observed_date=(row["observed_at"].date() if row.get("observed_at") else date.today()),
                notes=["소비자 앱 관측 이력"], source="core_observation"))
    uniq = {c.candidate_id: c for c in found}
    for c in uniq.values():
        upsert_candidate(c)
    return list(uniq.values())


def coverage(req: BidRequirement, evals) -> list[dict]:
    rows = []
    for need in req.categories:
        mine = [e for e in evals if e.candidate.category == need.name]
        rows.append({
            "category": need.name, "need": need.count,
            "eligible": sum(e.decision == "ELIGIBLE" for e in mine),
            "hold": sum(e.decision == "HOLD" for e in mine),
            "excluded": sum(e.decision == "EXCLUDED" for e in mine),
            "gap": max(0, need.count - sum(e.decision != "EXCLUDED" for e in mine)),
        })
    return rows
