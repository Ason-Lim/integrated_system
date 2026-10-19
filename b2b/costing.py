"""1인당 비용 구조 — '미확인은 0원이 아니다'.

44,000원 - 공급사 인도 비용 - 추가 포장 - 개별 배송 - 운영·CS/하자 - 폐쇄몰 구축비 배분 - 기타
→ 모든 항목이 확인되어야 잔여액(마진)을 '확정'으로 표시한다.
공개 판매가를 매입비로 '가정'한 시나리오는 별도로, 가정임을 명시해서만 보여준다.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from b2b.models import BidRequirement, Candidate

COMPONENTS = [
    ("supply", "상품 매입가 (공급사 인도 기준)"),
    ("packaging", "추가 포장"),
    ("shipping", "개별 배송 (도서산간 포함)"),
    ("ops_cs", "운영·CS·하자 대응"),
    ("mall_build", "폐쇄몰 구축비 배분"),
    ("other", "기타 확인 비용"),
]


class CostLine(BaseModel):
    key: str
    label: str
    amount: int | None = None
    basis: str = "미확인"


class CostAnalysis(BaseModel):
    budget_per_person: int | None
    vat_included: bool | None
    lines: list[CostLine]
    known_total: int
    unknown: list[str]
    residual: int | None              # 모든 항목 확인 시에만 값
    scenarios: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def analyze(req: BidRequirement, inputs: dict[str, int | None] | None = None,
            proxy_candidates: list[Candidate] | None = None, mall_build_total: int | None = None) -> CostAnalysis:
    inputs = dict(inputs or {})
    if mall_build_total is not None and req.headcount:
        inputs["mall_build"] = round(mall_build_total / req.headcount)
    lines = []
    for key, label in COMPONENTS:
        v = inputs.get(key)
        basis = "입력값" if v is not None else "미확인"
        if key == "mall_build" and mall_build_total is not None:
            basis = f"고정비 {mall_build_total:,}원 ÷ {req.headcount:,}명"
        lines.append(CostLine(key=key, label=label, amount=v, basis=basis))
    known = sum(l.amount for l in lines if l.amount is not None)
    unknown = [l.label for l in lines if l.amount is None]
    b = req.budget_per_person
    residual = (b - known) if (b and not unknown) else None

    scenarios = []
    for c in proxy_candidates or []:
        if c.observed_price is None or not b:
            continue
        gap = b - c.observed_price
        scenarios.append({
            "candidate": c.name, "assumed_supply": c.observed_price,
            "gap_before_other_costs": gap,
            "verdict": ("추가 비용 전에도 예산 초과 — B2B 견적 없이는 실행 가능성 입증 불가" if gap < 0
                        else "차액은 확정 수익이 아님 — 포장·배송·운영비 확인 전"),
        })

    notes = []
    if req.min_online_price and b:
        notes.append(f"온라인가 {req.min_online_price:,}원 이상은 '상품 가치' 조건이며 매입가 의무가 아니므로 "
                     f"{b - req.min_online_price:,}원을 이익으로 확정하지 않습니다.")
    if req.headcount and req.categories:
        n = sum(x.count for x in req.categories)
        notes.append(f"{req.headcount:,}명은 전체 {n}종 선택에 대한 예정 인원입니다. 상품별 주문량은 미확인으로 두며 "
                     f"{req.headcount:,}÷{n} 균등 수량을 적용하지 않습니다.")
    if req.vat_included is not None:
        notes.append("VAT " + ("포함" if req.vat_included else "별도") + " 기준 — 견적별 VAT 기준을 반드시 명시받고 세무 처리는 별도 확인합니다.")
    return CostAnalysis(budget_per_person=b, vat_included=req.vat_included, lines=lines, known_total=known,
                        unknown=unknown, residual=residual, scenarios=scenarios, notes=notes)
