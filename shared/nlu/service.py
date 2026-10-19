"""NLU 서비스 — food-nlu(LLM + 사전 DB)를 1차로, 규칙 NLU 를 안전망으로 합친다.

  사용자 문장 ─┬─▶ food-nlu FoodNLU.parse()   (FOOD_NLU_PATH + DATABASE_URL + LLM 있을 때)
               └─▶ rule_nlu.parse()            (항상)
                       ▼
                 merge: LLM 결과를 우선하되, LLM 이 놓친 숫자 슬롯(예산·수량)과
                        몰 이름은 규칙 결과로 보강 (숫자는 규칙이 더 정확)
"""
from __future__ import annotations

import importlib
import logging
import sys

from shared.config import Settings, get_settings
from shared.models import Intent
from shared.nlu import rule_nlu
from shared.query_expansion import filter_expansion, log_unsupported

log = logging.getLogger(__name__)

RULE_AUTHORITATIVE = ("budget_min", "budget_max", "quantity", "mall", "priority", "purpose", "recipient", "occasion", "allergen")


class NLUService:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self._food_nlu = None
        if self.s.food_nlu_path and self.s.llm_provider != "none":
            try:
                if self.s.food_nlu_path not in sys.path:
                    sys.path.insert(0, self.s.food_nlu_path)
                self._food_nlu = importlib.import_module("nlu").FoodNLU()
            except BaseException as e:  # FoodNLU 는 DATABASE_URL 없으면 sys.exit 를 호출함
                log.warning("food-nlu 비활성: %s", e)
                self._food_nlu = None

    @property
    def mode(self) -> str:
        return "food-nlu+rule" if self._food_nlu else "rule"

    def parse(self, text: str, prior: dict | None = None) -> Intent:
        rule = rule_nlu.parse(text)
        intent = rule
        if self._food_nlu is not None:
            try:
                r = self._food_nlu.parse(text)
                if r.get("action_intent"):
                    slots = dict(r.get("slots") or {})
                    for k in RULE_AUTHORITATIVE:
                        if k in rule.slots:
                            slots[k] = rule.slots[k]
                    # SAFE-QE: LLM 확장어 중 상품 근거에 없는 속성은 요구로 승격하지 않는다.
                    # evidence 는 원문이 아니라 상품 근거(제목·스펙·설명)여야 한다.
                    if slots.get("product"):
                        evidence = str(slots.get("_evidence") or "")
                        exp = filter_expansion(text, str(slots["product"]).split(), evidence)
                        slots["_expansion"] = exp
                        log_unsupported(text, exp, source="food_nlu")
                        if exp["dropped"]:
                            slots["product"] = " ".join([str(slots["product"])] + exp["kept"]).strip()
                    intent = Intent(action=r["action_intent"], context=r.get("context_intent") or rule.context,
                                    slots=slots, confidence=float(r.get("confidence") or 0), source="merged")
            except Exception as e:
                log.warning("food-nlu parse 실패, 규칙 결과 사용: %s", e)
        if prior:  # 멀티턴: 이전 슬롯 위에 새 슬롯을 덮어쓴다
            merged = dict(prior)
            merged.update(intent.slots)
            intent.slots = merged
        return intent
