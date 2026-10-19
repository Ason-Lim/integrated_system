"""B2B 도메인 모델.

핵심 원칙 (bundle policy 와 동일하게 코드로 강제)
  - unknown_cost_is_zero = False : 미확인 비용은 0원이 아니다 → None 으로 두고 '확정 불가' 처리
  - public_price_is_quote = False : 공개 판매가 ≠ 공급 견적
  - 판정은 ELIGIBLE / HOLD / EXCLUDED 세 가지. 미확인이 하나라도 있으면 ELIGIBLE 이 될 수 없다.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["PASS", "FAIL", "UNKNOWN"]
Decision = Literal["ELIGIBLE", "HOLD", "EXCLUDED"]


class Provenance(BaseModel):
    """추출값의 근거 — 원문 어디서 나왔는지."""
    field: str
    value: Any
    quote: str = ""                      # 원문 발췌
    source: str = "prompt"               # prompt | bid_notice | rfp_document | default


class CategoryNeed(BaseModel):
    name: str                            # 식품 / 건강기능식품 / 생활용품 ...
    count: int = 1                       # 필요한 품목 수 (예: 2종)


class BidRequirement(BaseModel):
    bid_id: str | None = None
    title: str | None = None
    agency: str | None = None
    headcount: int | None = None
    budget_per_person: int | None = None
    vat_included: bool | None = None
    total_budget: int | None = None
    categories: list[CategoryNeed] = Field(default_factory=list)
    min_online_price: int | None = None   # 온라인 기준 최저가 하한 (상품 가치 조건)
    setup_days: int | None = None          # 폐쇄몰 구축 기한 (일)
    delivery_business_days: int | None = None
    exchange_business_days: int | None = None
    deadline: date | None = None
    settlement: str | None = None          # 정산 방식
    notes: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    def computed_total(self) -> int | None:
        if self.total_budget:
            return self.total_budget
        if self.headcount and self.budget_per_person:
            return self.headcount * self.budget_per_person
        return None

    def missing(self) -> list[str]:
        need = {"headcount": "예정 인원", "budget_per_person": "1인당 예산", "categories": "품목 구성",
                "delivery_business_days": "배송 기한", "min_online_price": "상품 가치 하한(온라인가)"}
        return [label for k, label in need.items() if not getattr(self, k)]


class Candidate(BaseModel):
    candidate_id: str
    supplier: str
    name: str
    option: str | None = None
    category: str | None = None
    url: str | None = None
    observed_price: int | None = None      # 과거 관측가 (확정 단가 아님)
    price_kind: str = "unknown"            # supplier_quote | public_retail | supply_table | ...
    observed_date: date | None = None
    expired_discount_price: int | None = None
    unit_price_quote: int | None = None    # 공급사 견적 단가 (없으면 None)
    online_min_price_verified: int | None = None
    stock_status: str = "unknown"
    quantity_available: int | None = None
    delivery_days: int | None = None
    exchange_days: int | None = None
    quote_valid_until: date | None = None
    packaging_cost: int | None = None
    shipping_cost: int | None = None       # 1인(1건) 기준 개별 배송비
    origin: str | None = None
    manufacturer: str | None = None
    notes: list[str] = Field(default_factory=list)
    is_sample: bool = False                # 예시 데이터 (제안서에서 제외)
    source: str = "evidence_bundle"        # evidence_bundle | core_observation | market_search | manual


class Check(BaseModel):
    key: str
    label: str
    status: Status
    expected: Any = None
    actual: Any = None
    note: str = ""
    question: str | None = None            # UNKNOWN 일 때 공급사에 물을 질문


class Evaluation(BaseModel):
    candidate: Candidate
    decision: Decision
    checks: list[Check]

    @property
    def unknown(self) -> list[Check]:
        return [c for c in self.checks if c.status == "UNKNOWN"]

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if c.status == "FAIL"]
