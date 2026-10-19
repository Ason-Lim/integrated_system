"""commerce_ai_generator 랭킹 엔진 어댑터 (Strangler 패턴).

commerce_ai 의 공개 파사드 run_recommendation_pipeline(q, priority, session_id, limit) 를 그대로 호출하고
결과 item dict 를 공통 ScoredOffer 로 바꾼다. 엔진 내부(Recommendation Provider V8, food knowledge,
cross-border 등)는 건드리지 않는다.

COMMERCE_AI_PATH 가 없거나 import/DB 연결이 실패하면 available=False → 기본 랭커로 폴백.
"""
from __future__ import annotations

import importlib
import logging
import sys

from shared.config import Settings, get_settings
from shared.models import Intent, Offer, ScoredOffer

log = logging.getLogger(__name__)

PRIORITY_MAP = {"price": "price", "value": "value", "quality": "quality", "trust": "trust"}


class CommerceAIEngine:
    name = "commerce_ai_v8"

    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self._fn = None
        if self.s.commerce_ai_path:
            try:
                if self.s.commerce_ai_path not in sys.path:
                    sys.path.insert(0, self.s.commerce_ai_path)
                mod = importlib.import_module("app.services.recommendation_pipeline")
                self._fn = mod.run_recommendation_pipeline
            except Exception as e:
                log.warning("commerce_ai 엔진 비활성: %s", e)

    @property
    def available(self) -> bool:
        return self._fn is not None

    def recommend(self, query: str, intent: Intent, session_id: str | None, limit: int = 10) -> list[ScoredOffer]:
        if not self._fn:
            return []
        priority = PRIORITY_MAP.get(intent.slots.get("priority", ""), "ranking")
        res = self._fn(q=query, priority=priority, session_id=session_id, limit=limit)
        return [self._to_scored(it) for it in res.get("items", [])]

    @staticmethod
    def _to_scored(it: dict) -> ScoredOffer:
        platform = (it.get("platform") or it.get("platform_name") or "").lower()
        offer = Offer(
            mall=platform or "commerce_ai", mall_label=it.get("mall_name") or it.get("platform_name") or platform,
            mall_product_id=str(it.get("product_id") or it.get("id") or ""),
            title=it.get("product_name") or it.get("name") or "",
            price=int(float(it.get("price") or 0)),
            shipping_fee=it.get("shipping_fee") if it.get("shipping_fee") is not None else None,
            original_price=int(float(it["original_price"])) if it.get("original_price") else None,
            review_count=it.get("review_count"), rating=it.get("rating"),
            url=it.get("product_url") or it.get("url"),
            image_url=it.get("thumbnail_url") or it.get("image") or it.get("image_url"),
        )
        score_key = next((k for k in ("v7_final_score", "final_recommendation_score", "score")
                          if isinstance(it.get(k), (int, float)) and not isinstance(it[k], bool)), None)
        reason = it.get("recommendation_reason") or ""
        so = ScoredOffer(offer=offer, score=float(it[score_key]) if score_key else 0, score_source=score_key or "unavailable", reason=reason,
                         evidence=[x for x in (it.get("recommendation_reason_1"), it.get("recommendation_reason_2")) if x],
                         engine="commerce_ai_v8")
        if offer.rankability == "NOT_RANKABLE":
            so.rankable = False
            so.not_rankable_reason = "판매처 근거로 구매조건 확정 불가"
        return so
