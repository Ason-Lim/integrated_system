"""추천 서비스 — 두 앱이 공유하는 단일 진입점.

intent ─▶ 검색어 생성 ─▶ (commerce_ai 엔진 | 마켓 검색 + 기본 랭커) ─▶ 예산 필터 ─▶ 배지·근거
"""
from __future__ import annotations

from shared.config import Settings, get_settings
from shared.engines import simple_ranker
from shared.engines.commerce_ai_adapter import CommerceAIEngine
from shared.markets.registry import MarketRegistry
from shared.models import Intent, ScoredOffer
from shared.assurance import assess
from shared.query_expansion import filter_expansion, log_unsupported

PURPOSE_KR = {"gift": "선물세트", "camping": "캠핑용"}


def build_query(intent: Intent) -> str:
    s = intent.slots
    parts = [str(s["product"])] if s.get("product") else []
    if s.get("purpose") == "gift" and s.get("product") and "선물" not in s["product"]:
        parts.append("선물세트")
    if not parts and s.get("category"):
        cat = s["category"]
        parts += cat if isinstance(cat, list) else [cat]
    return " ".join(parts).strip()


class Recommender:
    def __init__(self, settings: Settings | None = None, markets: MarketRegistry | None = None,
                 engine: CommerceAIEngine | None = None):
        self.s = settings or get_settings()
        self.markets = markets or MarketRegistry(self.s)
        self.engine = engine or CommerceAIEngine(self.s)
        self.last_engine = self.mode
        self.last_dropped_irrelevant = 0

    @property
    def mode(self) -> str:
        return "commerce_ai_v8" if self.engine.available else "markets+simple_ranker"

    def recommend(self, intent: Intent, *, session_id: str | None = None, limit: int = 3) -> tuple[str, list[ScoredOffer]]:
        query = build_query(intent)
        if not query:
            return "", []
        ranked: list[ScoredOffer] = []
        if self.engine.available:
            try:
                ranked = self.engine.recommend(query, intent, session_id, limit=20)
            except Exception:
                ranked = []
        self.last_engine = "commerce_ai_v8" if ranked else "markets+simple_ranker"
        if not ranked:
            malls = [intent.slots["mall"]] if intent.slots.get("mall") else None
            offers = self.markets.search(query, malls=malls, limit=30)
            # 마켓 검색은 일치 상품이 없어도 인기 상품을 돌려줄 수 있다 (예: 사과 검색에 섬유유연제).
            # 상품어가 제목에 하나도 없는 후보는 랭킹 전에 제외하고, 0개면 '찾지 못함'으로 보낸다.
            kept = relevant_offers(offers, intent)
            self.last_dropped_irrelevant = len(offers) - len(kept)
            ranked = simple_ranker.rank(kept, intent, query)
        # SAFE-QE: 검색 결과의 상품 근거(제목·스펙·설명)로 확장어를 재검증한다.
        # 근거에 없는 확장어는 요구로 승격하지 않고 로그로만 남긴다.
        if intent.slots.get("_expansion") and ranked:
            evidence = " ".join(
                " ".join(filter(None, (x.offer.title, x.offer.spec, x.offer.description)))
                for x in ranked[:20]
            )
            exp = filter_expansion(query, list(intent.slots["_expansion"].get("kept", [])), evidence)
            intent.slots["_expansion"] = exp
            log_unsupported(query, exp, source="recommender")
        ranked = apply_budget(ranked, intent)
        if intent.slots.get("priority") == "trust":      # '후기 많은 순'
            ranked.sort(key=lambda x: -(x.offer.review_count or 0))
        elif intent.slots.get("priority") == "price":    # '더 저렴한 것'
            ranked.sort(key=lambda x: x.offer.total_price or x.offer.price)
        # Sponsorship never changes the organic order; only decidable offers lead.
        ranked = [x for x in ranked if not x.offer.is_sponsored]
        for x in ranked:
            x.decision = assess(x.offer)
            if intent.slots.get("allergen"):
                x.decision["status"] = "NOT_RANKABLE"
                x.decision["missing"].append("allergen_source_verification")
                x.decision["next_evidence"].append("allergen_source_verification")
                x.unverified.append("알레르기 성분·교차오염 원문 확인")
            if x.decision["status"] != "RANKABLE":
                x.rankable = False
                x.not_rankable_reason = x.not_rankable_reason or "구매조건 근거 부족"
        ranked.sort(key=lambda x: (not x.rankable, x.decision["status"] != "RANKABLE"))
        n = max(1, min(20, int(intent.slots.get("quantity") or limit)))
        # NOT_RANKABLE 은 순위 비교에서 제외하고, 랭킹 가능 후보가 없을 때만 참고용으로 노출한다.
        rankable = [x for x in ranked if x.rankable]
        top = (rankable or ranked)[:n]
        assign_badges(top)
        for so in top:
            so.reason = so.reason or compose_reason(so)
        return query, top


def relevant_offers(offers: list, intent: Intent) -> list:
    """상품어(slots.product) 중 하나라도 제목에 있는 후보만 남긴다. 띄어쓰기 차이는 무시한다."""
    terms = [t for t in str(intent.slots.get("product") or "").split() if len(t) >= 2]
    if not terms:
        return offers
    out = []
    for o in offers:
        title = o.title or ""
        flat = title.replace(" ", "")
        if any(t in title or t in flat for t in terms):
            out.append(o)
    return out


def apply_budget(items: list[ScoredOffer], intent: Intent) -> list[ScoredOffer]:
    lo, hi = intent.slots.get("budget_min"), intent.slots.get("budget_max")
    if not lo and not hi:
        return items
    out = []
    for so in items:
        p = so.offer.total_price
        if p is None:
            # 배송비 미확인 → 상품가로 상·하한을 보수적으로 검사한다.
            base = so.offer.price
            if hi and base > hi:
                continue
            if lo and base < lo:
                continue
            so.unverified.append("배송비 포함 예산 충족 여부")
            out.append(so)
            continue
        if hi and p > hi:
            continue
        if lo and p < lo:
            continue
        out.append(so)
    return out


def assign_badges(items: list[ScoredOffer]) -> None:
    if not items:
        return
    rankable = [x for x in items if x.rankable]
    if rankable:
        rankable[0].badges.append("1순위 추천")
    priced = [x for x in items if x.rankable and x.offer.total_price is not None]
    if len(priced) >= 2:
        cheapest = min(priced, key=lambda x: x.offer.total_price)
        if cheapest is not items[0]:
            cheapest.badges.append("표시 총액 낮음")
    reviewed = [x for x in items if x.rankable and x.offer.review_count]
    if len(reviewed) >= 2:
        most = max(reviewed, key=lambda x: x.offer.review_count)
        if not most.badges:
            most.badges.append("후기 많음")
    for x in items:
        o = x.offer
        if o.original_price and o.original_price > o.price:
            pct = round((o.original_price - o.price) / o.original_price * 100)
            if pct >= 5:
                x.badges.append(f"{pct}% 할인")
        if not x.rankable:
            x.badges.append("비교 불가")


def compose_reason(so: ScoredOffer) -> str:
    o = so.offer
    bits = []
    if o.description:
        bits.append(o.description)
    # 가격·후기 수는 카드의 가격줄·근거칩에 이미 있으므로 중복하지 않는다
    return ". ".join(bits) + ("." if bits else "")
