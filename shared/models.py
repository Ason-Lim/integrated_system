"""공통 도메인 모델.

Offer     : 마켓 어댑터가 돌려주는 '관측된' 판매 정보 (가격은 관측 시점 값)
Intent    : NLU 결과 (action / context / slots)
Block     : 화면 구성 단위. 서버가 블록 목록을 내려주면 웹·블로그·메신저가 각자 렌더링한다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Offer(BaseModel):
    mall: str                                   # coupang | naver | sample | ...
    mall_label: str = ""                        # 화면 표시용 몰 이름
    mall_product_id: str | None = None
    title: str
    brand: str | None = None
    category: str | None = None
    price: int = 0                              # 상품가
    shipping_fee: int | None = None             # None = 미확인 (0원과 다름)
    original_price: int | None = None
    rating: float | None = None
    review_count: int | None = None
    url: str | None = None
    image_url: str | None = None
    unit_count: int | None = None               # 개입 수 (20개입 등)
    weight_g: float | None = None
    spec: str | None = None                     # "24인치 · FHD · 180Hz" 같은 한 줄 스펙
    description: str | None = None
    observed_at: datetime = Field(default_factory=now_utc)
    is_sample: bool = False                     # 데모용 가상 데이터 표시
    variant_id: str | None = None
    seller: str | None = None
    origin: str | None = None
    grade: str | None = None
    return_policy: str | None = None
    delivery_terms: str | None = None
    is_sponsored: bool = False
    source_refs: list[str] = Field(default_factory=list)
    # ── 판매처 결정 가능성 (Merchant Decision Sufficiency) ──
    # 각 항목은 판매처가 공개한 근거로 확정 가능한지 여부. None = 미확인.
    total_cost_determinate: bool | None = None      # 총비용(배송·수수료 포함) 확정 가능
    return_terms: str | None = None                 # 반품/취소 조건 원문
    service_date: str | None = None                 # 서비스/배송 예정일
    evidence_coverage: float | None = None          # 필수조건 근거 coverage (0~1)
    missing_terms: list[str] = Field(default_factory=list)  # 확정 불가 항목 키
    rankability: str = "UNKNOWN"                    # DETERMINATE | INDETERMINATE | UNKNOWN | NOT_RANKABLE
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)

    @property
    def total_price(self) -> int | None:
        """배송비 포함 실구매가. 배송비 미확인이면 None."""
        if self.shipping_fee is None:
            return None
        return self.price + self.shipping_fee

    @property
    def unit_price(self) -> int | None:
        if self.total_price is not None and self.unit_count and self.unit_count > 1:
            return round((self.total_price or self.price) / self.unit_count)
        return None


class Intent(BaseModel):
    action: str = "recommend_food"
    context: str | None = None
    slots: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    source: str = "rule"                        # rule | llm | merged
    # ── Decision Freshness Ledger (shadow) ──
    decision_time: datetime | None = None
    evidence_time: datetime | None = None
    intended_action_time: datetime | None = None
    revision_deadline: datetime | None = None
    watch_conditions: list[str] = Field(default_factory=list)


class ScoredOffer(BaseModel):
    offer: Offer
    score: float = 0.0
    badges: list[str] = Field(default_factory=list)
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)      # 확인된 근거
    unverified: list[str] = Field(default_factory=list)    # 미확인 항목
    engine: str = "simple_ranker"
    score_source: str = "simple_ranker"
    decision: dict[str, Any] = Field(default_factory=dict)
    rankable: bool = True                                  # False → 비교·순위 대상 아님
    not_rankable_reason: str | None = None


# ── 화면 블록 (server-driven UI) ──────────────────────────────
class Block(BaseModel):
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


def text_block(md: str) -> Block:
    return Block(type="text", data={"md": md})


def notice_block(md: str, tone: Literal["info", "warn"] = "info") -> Block:
    return Block(type="notice", data={"md": md, "tone": tone})
