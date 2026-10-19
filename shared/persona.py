"""근거 기반 고객 페르소나 (SimInter, arXiv:2610.18308 축소 구현).

원칙: LLM 이 성격·취향을 지어내지 않는다. click_log / search_log 에 기록된 실제 행동만 근거로
선호(가격형·품질형·리뷰형)를 추론하고, 근거가 없는 속성은 UNKNOWN 으로 남겨 추가 질문 대상으로 돌려준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PREFERENCE_KEYS = ("price", "quality", "trust")


@dataclass
class PersonaClaim:
    key: str
    value: str | None            # None = UNKNOWN
    evidence: list[str] = field(default_factory=list)
    counter_evidence: list[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return bool(self.value) and bool(self.evidence)


@dataclass
class Persona:
    claims: dict[str, PersonaClaim] = field(default_factory=dict)

    @property
    def unknown(self) -> list[str]:
        return [k for k, c in self.claims.items() if not c.supported]

    def slots(self) -> dict:
        """근거가 있는 선호만 슬롯으로 승격한다."""
        return {k: c.value for k, c in self.claims.items() if c.supported}

    def audit(self) -> dict:
        total = len(self.claims)
        supported = sum(1 for c in self.claims.values() if c.supported)
        return {"total": total, "supported": supported,
                "unsupported_rate": round((total - supported) / total, 3) if total else 0.0,
                "unknown": self.unknown}


def infer(evidence: dict) -> Persona:
    """행동 근거로만 선호를 추론한다. 근거가 없으면 value=None(UNKNOWN)."""
    clicks = evidence.get("clicks") or []
    searches = evidence.get("searches") or []
    claims: dict[str, PersonaClaim] = {k: PersonaClaim(key=k, value=None) for k in PREFERENCE_KEYS}

    # 1) 검색 슬롯에 명시된 priority 는 가장 강한 근거
    for s in searches:
        slots = s.get("slots") or {}
        p = slots.get("priority")
        if p in claims:
            claims[p].value = p
            claims[p].evidence.append(f"검색 슬롯 priority={p}")

    # 2) 클릭 행동: 낮은 순위(3위 이하) 클릭은 가격/품질 선호 신호
    for c in clicks:
        rank = c.get("rank")
        if rank is None:
            continue
        if rank >= 3:
            claims["price"].evidence.append(f"{rank}위 상품 클릭")
        if rank == 1:
            claims["trust"].counter_evidence.append("1위 상품 클릭 (가격 선호와 반대 신호)")

    # 3) 근거가 2개 이상 쌓인 선호만 확정한다 (단일 클릭은 노이즈)
    for k, c in claims.items():
        if c.value is None and len(c.evidence) >= 2:
            c.value = k
    return Persona(claims=claims)
