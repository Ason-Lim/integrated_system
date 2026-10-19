"""Local decision contracts; no network, inferred quality or production governance changes."""
from datetime import datetime, timezone
from shared.models import Offer

POLICY_VERSION = "kop-local-2026-10-16-v1"

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
    return {"policy_version": POLICY_VERSION, "status": "NOT_RANKABLE" if gaps else "RANKABLE",
            "missing": gaps, "next_evidence": list(gaps),
            "observed_at": observed.isoformat(), "scope": "local_candidate_comparison"}

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
