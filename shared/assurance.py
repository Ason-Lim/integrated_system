"""Local decision contracts; no network, inferred quality or production governance changes.

Merchant Decision Sufficiency (arXiv:2610.17378) 를 shadow 로 반영한다.
필수조건(총비용·반품·서비스일·variant)이 판매처 근거로 확정 불가하면 점수를 낮추는 대신
NOT_RANKABLE 로 분리한다. 근거 coverage 와 missingness 를 함께 돌려준다.
"""
from datetime import datetime, timezone
from shared.models import Offer

POLICY_VERSION = "kop-local-2026-10-16-v2"

# 구매 mandate 의 필수 조건 — 판매처 근거로 확정 가능해야 한다
MANDATE_TERMS = ("total_cost", "return_terms", "service_date", "variant_id")
# 이 항목이 UNKNOWN 이면 점수 하향이 아니라 랭킹 분리(NOT_RANKABLE) 대상이다.
HARD_TERMS = ("total_cost",)
# 계층 속성 (HASTE) — 장기꼬리 상품 비교에 필요한 최소 속성
HIERARCHY_TERMS = ("item", "variety", "grade", "spec_grade")


def _term_state(offer: Offer, term: str) -> str:
    """DETERMINATE / INDETERMINATE / UNKNOWN."""
    if term == "total_cost":
        if offer.total_cost_determinate is True and offer.total_price is not None:
            return "DETERMINATE"
        if offer.total_cost_determinate is False:
            return "INDETERMINATE"
        return "UNKNOWN"
    if term == "return_terms":
        if offer.return_terms:
            return "DETERMINATE"
        if offer.return_policy:
            return "INDETERMINATE"
        return "UNKNOWN"
    if term == "service_date":
        if offer.service_date:
            return "DETERMINATE"
        if offer.delivery_terms:
            return "INDETERMINATE"
        return "UNKNOWN"
    if term == "variant_id":
        return "DETERMINATE" if offer.variant_id else "UNKNOWN"
    return "UNKNOWN"


def hierarchy_coverage(offer: Offer) -> dict:
    """계층 속성(품목→품종→등급→규격) 보존 여부를 계산한다."""
    present = [t for t in HIERARCHY_TERMS if getattr(offer, t)]
    missing = [t for t in HIERARCHY_TERMS if not getattr(offer, t)]
    return {"present": present, "missing": missing,
            "coverage": round(len(present) / len(HIERARCHY_TERMS), 3)}


def decision_sufficiency(offer: Offer) -> dict:
    """판매처 근거로 구매조건이 확정 가능한지 평가한다.

    - HARD_TERMS(총비용)가 UNKNOWN/INDETERMINATE 이면 NOT_RANKABLE 로 분리한다.
    - 그 외 필수조건이 미확정이면 INDETERMINATE/UNKNOWN 으로 표시한다.
    """
    states = {t: _term_state(offer, t) for t in MANDATE_TERMS}
    determinate = [t for t, s in states.items() if s == "DETERMINATE"]
    missing = [t for t, s in states.items() if s != "DETERMINATE"]
    coverage = len(determinate) / len(MANDATE_TERMS)
    hard_unknown = [t for t in HARD_TERMS if states.get(t) != "DETERMINATE"]
    if hard_unknown:
        rankability = "NOT_RANKABLE"
    elif any(s == "INDETERMINATE" for s in states.values()):
        rankability = "INDETERMINATE"
    elif missing:
        rankability = "UNKNOWN"
    else:
        rankability = "DETERMINATE"
    return {"states": states, "coverage": round(coverage, 3), "missing": missing,
            "hard_unknown": hard_unknown, "rankability": rankability,
            "hierarchy": hierarchy_coverage(offer)}


def assess(offer: Offer, *, now=None, max_age_hours=24):
    now = now or datetime.now(timezone.utc)
    observed = offer.observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    age = (now - observed).total_seconds() / 3600
    gaps = []
    for field in ("variant_id", "return_policy", "delivery_terms", "source_refs"):
        if not getattr(offer, field):
            gaps.append(field)
    if offer.total_price is None:
        gaps.append("shipping_fee")
    if offer.price <= 0:
        gaps.append("price")
    if age < 0 or age >= max_age_hours:
        gaps.append("fresh_price")
    if offer.is_sample:
        gaps.append("real_product")
    suff = decision_sufficiency(offer)
    # 근거 coverage 부족은 점수 하향이 아니라 랭킹 분리 사유
    if suff["rankability"] != "DETERMINATE":
        gaps.extend(f"term:{t}" for t in suff["missing"])
    # 총비용 확정 불가 → 무조건 NOT_RANKABLE
    if suff["rankability"] == "NOT_RANKABLE":
        gaps.extend(f"hard:{t}" for t in suff["hard_unknown"])
    return {"policy_version": POLICY_VERSION, "status": "NOT_RANKABLE" if gaps else "RANKABLE",
            "missing": gaps, "next_evidence": list(gaps),
            "observed_at": observed.isoformat(), "scope": "local_candidate_comparison",
            "sufficiency": suff}

def price_gap(retail: Offer, wholesale: Offer):
    """No kg conversion or quality equivalence inferred from titles."""
    fields = ("variant_id", "weight_g", "origin", "grade")
    if any(getattr(retail, k) is None or getattr(retail, k) != getattr(wholesale, k) for k in fields):
        return {"status": "NOT_COMPARABLE", "question": "동일 옵션·중량·원산지·등급을 확인해 주세요."}
    if retail.total_price is None or wholesale.total_price is None:
        return {"status": "NOT_COMPARABLE", "question": "양쪽 배송비와 판매단위를 확인해 주세요."}
    gap = wholesale.total_price - retail.total_price
    return {"status": "PRICE_INVERSION" if gap > 0 else "COMPARABLE", "gap_won": gap,
            "question": "품질·수량·견적 유효기간을 공급사에 확인해 주세요.", "is_quote": False}
