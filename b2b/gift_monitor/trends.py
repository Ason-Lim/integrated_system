"""입찰 트렌드 분석 — gift_trend_analyzer 대시보드의 집계(유형·예산대·기업유형·자격요건)를 이식하고
기관유형·시기·월별 마감 분포를 더했다. 리포트 문장은 집계 숫자에서만 만든다.

기본값으로 신뢰 등급이 낮은 공고(legacy_unverified)는 통계에서 뺀다.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from b2b import bids as store
from b2b.gift_monitor import classify


def _pool(include_unverified: bool, include_legacy: bool) -> list[store.BidNotice]:
    out = []
    for b in store.list_bids():
        if b.verification == "legacy_unverified" and not include_legacy:
            continue
        if b.verification == "unverified" and not include_unverified:
            continue
        out.append(b)
    return out


def _dist(counter: Counter, order: list[str]) -> list[dict]:
    total = sum(counter.values()) or 1
    keys = order + [k for k in counter if k not in order]
    return [{"label": k, "count": counter.get(k, 0), "pct": round(counter.get(k, 0) * 100 / total)} for k in keys
            if counter.get(k, 0) or k in order]


def analyze(include_unverified: bool = True, include_legacy: bool = False, today: date | None = None) -> dict:
    pool = _pool(include_unverified, include_legacy)
    excluded = {
        "legacy": sum(b.verification == "legacy_unverified" for b in store.list_bids()) if not include_legacy else 0,
        "unverified": sum(b.verification == "unverified" for b in store.list_bids()) if not include_unverified else 0,
    }
    dv = [(b, b.derived(today)) for b in pool]
    types = Counter(d["bid_type"] for _, d in dv)
    comp = Counter(d["company_type"] for _, d in dv)
    quals = Counter(q for _, d in dv for q in d["qualifications"])
    bands = Counter(d["budget_band"] for _, d in dv)
    inst = Counter(b.institution_type for b, _ in dv)
    occ = Counter(d["occasion"] for _, d in dv)
    status = Counter(d["status"] for _, d in dv)
    months = Counter()
    for b, _ in dv:
        if dd := classify.parse_date(b.deadline):
            months[f"{dd.year}-{dd.month:02d}"] += 1
    budgets = [b.budget for b, _ in dv if b.budget]
    total = len(pool)

    def share(c: Counter, k: str) -> int:
        return round(c.get(k, 0) * 100 / total) if total else 0

    physical = sum(v for k, v in types.items() if k.startswith("선물세트"))
    report = []
    if total:
        top_t = types.most_common(1)[0]
        report.append(f"집계 대상 {total}건 중 가장 많은 유형은 '{top_t[0]}'({top_t[1]}건, {share(types, top_t[0])}%)입니다. "
                      f"실물 선물세트는 {round(physical * 100 / total)}%, 상품권(온누리·모바일)은 "
                      f"{share(types, '온누리상품권') + share(types, '모바일상품권')}%입니다.")
        if budgets:
            budgets.sort()
            med = budgets[len(budgets) // 2]
            report.append(f"금액이 기재된 {len(budgets)}건의 예산 중앙값은 {med:,}원이고, 최소 {budgets[0]:,}원 · 최대 {budgets[-1]:,}원입니다. "
                          f"금액 미기재는 {bands.get('금액 미기재', 0)}건입니다.")
        if quals:
            q, n = quals.most_common(1)[0]
            report.append(f"자격·요건 키워드는 '{q}'이 {n}건으로 가장 자주 나타납니다 (규칙 키워드 기준이며 원문 평가표 확인 필요).")
        top_inst = inst.most_common(1)[0]
        report.append(f"기관 유형은 '{top_inst[0]}'이 {top_inst[1]}건으로 가장 많습니다.")
        open_n = status.get("입찰중", 0) + status.get("마감임박", 0)
        report.append(f"현재 참여 가능한 공고(입찰중·마감임박)는 {open_n}건입니다.")
    else:
        report.append("집계할 공고가 없습니다. 나라장터 수집이나 공고 직접 등록으로 데이터를 쌓아 주세요.")
    if excluded["legacy"]:
        report.append(f"미검증 기존 데이터 {excluded['legacy']}건은 통계에서 제외했습니다.")

    return {
        "total": total, "excluded": excluded,
        "kpi": {"open": status.get("입찰중", 0), "closing": status.get("마감임박", 0), "closed": status.get("입찰마감", 0),
                "physical_pct": round(physical * 100 / total) if total else 0,
                "voucher_pct": (share(types, "온누리상품권") + share(types, "모바일상품권")),
                "median_budget": sorted(budgets)[len(budgets) // 2] if budgets else None},
        "bid_types": _dist(types, classify.BID_TYPES),
        "budget_bands": _dist(bands, classify.BUDGET_BANDS),
        "company_types": _dist(comp, classify.COMPANY_TYPES),
        "qualifications": _dist(quals, classify.QUALIFICATIONS),
        "institution_types": _dist(inst, classify.INSTITUTION_TYPES[:-1]),
        "occasions": _dist(occ, classify.OCCASIONS),
        "deadline_months": [{"label": k, "count": months[k]} for k in sorted(months)],
        "report": report,
    }
