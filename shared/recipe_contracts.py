"""Recipe quantity contracts — smart conversion, estimation, and minimal questioning.

원칙
- 정확한 단위 환산(g↔kg, ml↔L)은 자동.
- 개수↔무게 같은 추정은 범위와 "대략" 표시.
- 조리 상태(마른/삶은)가 결과에 영향을 줄 때만 질문.
- "조금 있어요" 같은 모호한 표현은 정성 판단으로 진행.
- 요리 진행 가능 여부와 구매 확정 수량은 분리.
"""
from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field


# ── 단위 환산 ────────────────────────────────────────────────
_WEIGHT = {"g": 1.0, "kg": 1000.0}
_VOLUME = {"ml": 1.0, "l": 1000.0, "mL": 1.0, "L": 1000.0}

def _to_base(value: float, unit: str | None) -> tuple[float | None, str | None]:
    """Return (base_value, family) where family is 'weight' or 'volume'."""
    if value is None or not unit:
        return None, None
    u = unit.lower().strip()
    if u in _WEIGHT:
        return value * _WEIGHT[u], "weight"
    if u in _VOLUME:
        return value * _VOLUME[u], "volume"
    return None, None


def _from_base(base: float, family: str, target_unit: str) -> float | None:
    u = target_unit.lower().strip()
    table = _WEIGHT if family == "weight" else _VOLUME if family == "volume" else {}
    factor = table.get(u)
    return base / factor if factor else None


# ── 개수 ↔ 무게 참고 범위 (대략값) ────────────────────────────
# key: 재료명 키워드, value: (min_g, typical_g, max_g) per piece
_PIECE_WEIGHT = {
    "양파": (150, 200, 280),
    "감자": (100, 150, 220),
    "당근": (80, 120, 180),
    "계란": (50, 55, 65),
    "달걀": (50, 55, 65),
    "토마토": (120, 180, 250),
    "사과": (150, 200, 280),
    "바나나": (100, 120, 150),
}


def _estimate_pieces_to_g(name: str, pieces: float) -> tuple[float, float, float] | None:
    """Return (min, typical, max) grams for the given piece count, or None."""
    for key, (lo, mid, hi) in _PIECE_WEIGHT.items():
        if key in name:
            return lo * pieces, mid * pieces, hi * pieces
    return None


# ── 정성 표현 ─────────────────────────────────────────────────
_VAGUE_ENOUGH = {"충분", "많이", "넉넉", "잔뜩", "가득"}
_VAGUE_LITTLE = {"조금", "약간", "살짝", "좀", "소량"}
_VAGUE_NONE = {"없음", "없어", "없다", "0", "없다"}


class RecipeEvidence(BaseModel):
    source_id: str
    raw_text: str
    cooking_state: str | None = None
    page: int | None = Field(None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    status: str = "EXTRACTED_UNVERIFIED"

    def quantities(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "explicit_quantities": re.findall(
                r"\d+(?:\.\d+)?\s*(?:kg|g|ml|mL|L|개|알)(?![A-Za-z])", self.raw_text
            ),
            "cooking_state": self.cooking_state,
            "source_id": self.source_id,
            "requires_review": True,
        }


def shortage(
    required: float | None,
    owned: float | None,
    required_unit: str | None,
    owned_unit: str | None,
    required_state: str | None,
    owned_state: str | None,
    *,
    name: str = "",
    owned_raw: str | None = None,
) -> dict[str, Any]:
    """Calculate shortage with smart conversion and minimal questioning.

    Returns keys:
      shortage, shortage_unit, confidence ("exact"|"estimated"|"qualitative"),
      cooking_possible (bool), purchase_confirmed (bool),
      question (str|None), note (str|None), shopping_dispatch (always False)
    """
    result: dict[str, Any] = {
        "shortage": None,
        "shortage_unit": required_unit,
        "confidence": None,
        "cooking_possible": None,
        "purchase_confirmed": False,
        "question": None,
        "note": None,
        "shopping_dispatch": False,
    }

    # ── 정성 표현 처리 ────────────────────────────────────────
    if owned_raw:
        raw_low = owned_raw.lower()
        if any(w in raw_low for w in _VAGUE_ENOUGH):
            result.update(confidence="qualitative", cooking_possible=True,
                          note="보유량이 충분하다고 판단했습니다. 구매 수량은 확인하지 않습니다.")
            return result
        if any(w in raw_low for w in _VAGUE_NONE):
            result.update(shortage=required, shortage_unit=required_unit,
                          confidence="qualitative", cooking_possible=False,
                          purchase_confirmed=True,
                          note="보유량이 없다고 판단했습니다.")
            return result
        if any(w in raw_low for w in _VAGUE_LITTLE):
            result.update(confidence="qualitative", cooking_possible=True,
                          note="보유량이 조금 있다고 판단했습니다. 정확한 구매량은 추가 확인이 필요할 수 있습니다.")
            return result

    if required is None or owned is None:
        result["question"] = "필요량과 보유량을 확인해 주세요."
        return result

    if required < 0 or owned < 0:
        raise ValueError("quantity must be nonnegative")

    # ── 조리 상태 충돌 ────────────────────────────────────────
    if required_state and owned_state and required_state != owned_state:
        result["question"] = (
            f"{name or '이 재료'}는 필요량이 '{required_state}' 상태인데 "
            f"보유량은 '{owned_state}' 상태입니다. "
            f"보유한 {owned_state} 재료를 활용할까요, 아니면 {required_state} 재료로 구매할까요?"
        )
        result["cooking_possible"] = True  # 요리 안내는 계속 가능
        return result

    # ── 단위 환산 ─────────────────────────────────────────────
    req_base, req_fam = _to_base(required, required_unit)
    own_base, own_fam = _to_base(owned, owned_unit)

    if req_base is not None and own_base is not None and req_fam == own_fam:
        diff = max(0.0, req_base - own_base)
        # 원래 단위로 되돌림
        out_unit = required_unit or owned_unit
        out_val = _from_base(diff, req_fam, out_unit) if out_unit else diff
        result.update(
            shortage=round(out_val, 2) if out_val is not None else round(diff, 2),
            shortage_unit=out_unit,
            confidence="exact",
            cooking_possible=diff <= 0,
            purchase_confirmed=True,
            note="단위를 자동 환산했습니다." if required_unit != owned_unit else None,
        )
        return result

    # ── 개수 ↔ 무게 추정 ──────────────────────────────────────
    if required_unit in ("g", "kg") and owned_unit in ("개", "알", "ea"):
        est = _estimate_pieces_to_g(name, owned)
        if est:
            lo, mid, hi = est
            req_g = req_base or required
            # 보수적으로 최소 추정값으로 부족분 계산
            diff = max(0.0, req_g - lo)
            result.update(
                shortage=round(diff, 1),
                shortage_unit="g",
                confidence="estimated",
                cooking_possible=req_g <= hi,
                purchase_confirmed=False,
                note=f"1개당 약 {lo/owned:.0f}~{hi/owned:.0f}g으로 추정했습니다. 구매 수량은 확인이 필요합니다.",
            )
            return result

    if owned_unit in ("g", "kg") and required_unit in ("개", "알", "ea"):
        result["question"] = f"{name or '이 재료'}의 필요량이 '개' 단위입니다. 보유량(g)을 개수로 환산하려면 대략 크기를 알려주세요."
        result["cooking_possible"] = True
        return result

    # ── 그 외 미해결 ──────────────────────────────────────────
    result["question"] = "단위를 확인해 주세요. (무게는 g/kg, 부피는 ml/L, 개수는 '개'로 입력하면 자동 처리됩니다.)"
    result["cooking_possible"] = True
    return result
