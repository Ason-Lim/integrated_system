"""SAFE-QE 스타일 확장어 필터 (shadow) — arXiv:2610.13810 축소 구현.

LLM 이 만든 확장어 중 상품 근거(제목·스펙·설명)에 없는 속성을 걸러낸다.
'맛있는 사과' → '고당도 홍로' 처럼 근거 없는 속성을 고객 요구로 승격하지 않는다.
"""
from __future__ import annotations

import re

# 상품 근거에 없으면 요구로 승격하면 안 되는 속성 유형
ATTRIBUTE_PATTERNS = {
    "grade": re.compile(r"(특|상|중|하)등급|1\+|프리미엄급"),
    "origin": re.compile(r"(횡성|안동|성주|나주|제주|고창|의성|상주|영주|담양|해남)"),
    "cultivar": re.compile(r"(홍로|부사|시나노골드|감홍|샤인머스캣|설향|금실|대봉|단감)"),
    "sugar": re.compile(r"당도\s*\d+(?:\.\d+)?|고당도|저당도"),
    "size": re.compile(r"(특대|대과|중과|소과|\d+\s*(?:g|kg|mm|cm))"),
}


def _supported(term: str, evidence: str) -> bool:
    return term in evidence


def filter_expansion(original: str, expanded: list[str], evidence: str) -> dict:
    """확장어를 근거 지원 여부로 분류한다.

    반환: {"kept": [...], "dropped": [...], "unsupported_rate": float, "attribute_conflicts": [...]}
    """
    ev = (evidence or "").lower()
    kept, dropped, conflicts = [], [], []
    for term in expanded:
        t = term.strip()
        if not t or t in original:
            continue
        if _supported(t.lower(), ev):
            kept.append(t)
            continue
        dropped.append(t)
        for kind, rx in ATTRIBUTE_PATTERNS.items():
            if rx.search(t):
                conflicts.append({"term": t, "attribute": kind})
                break
    total = len(kept) + len(dropped)
    rate = round(len(dropped) / total, 3) if total else 0.0
    return {"kept": kept, "dropped": dropped, "unsupported_rate": rate, "attribute_conflicts": conflicts}
