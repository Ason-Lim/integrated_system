"""대화 상태 머신 — docs/architecture/CONVERSATION_STATE_MACHINE.md(V2) 의 축소 구현.

원칙: "추천 먼저, 조정은 대화로". 상품만 알면 바로 추천하고, 빠진 조건(예산·구매처·대상)은
추천 카드 '아래'에서 선택형으로 묻는다. 한 번에 최대 2개 질문.

UNDERSTAND ──(상품 모름)──▶ CLARIFY ──▶ RECOMMEND ──▶ REFINE ──▶ RECOMMEND ...
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from shared.engines.recommender import Recommender
from shared.models import Block, Intent
from shared.nlu.service import NLUService
from shared import store
from consumer import presenter


class Stage(str, Enum):
    UNDERSTAND = "understand"
    CLARIFY = "clarify"
    RECOMMEND = "recommend"
    REFINE = "refine"


@dataclass
class Session:
    id: str
    stage: Stage = Stage.UNDERSTAND
    slots: dict = field(default_factory=dict)
    turns: int = 0
    last_items: list = field(default_factory=list)
    # 레시피 멀티턴 상태
    recipe_title: str | None = None
    recipe_ingredients: list[dict] = field(default_factory=list)  # 누적 재료
    recipe_mode: bool = False


# 빠른 응답 칩 → 슬롯 변경 (서버가 해석, LLM 불필요)
REFINE_CHIPS = {
    "더 저렴한 것": {"priority": "price"},
    "후기 많은 순": {"priority": "trust"},
    "프리미엄으로": {"priority": "quality"},
    "선물용으로": {"purpose": "gift"},
}


class DialogueManager:
    def __init__(self, nlu: NLUService | None = None, recommender: Recommender | None = None,
                 persist: bool = True):
        self.nlu = nlu or NLUService()
        self.rec = recommender or Recommender()
        self.sessions: dict[str, Session] = {}
        self.persist = persist

    def session(self, sid: str | None) -> Session:
        if sid and sid in self.sessions:
            return self.sessions[sid]
        s = Session(id=sid or uuid.uuid4().hex[:12])
        self.sessions[s.id] = s
        return s

    # ── 입력 3종: 자유 문장 / 폼 응답 / 칩 ────────────────────────
    def handle(self, sid: str | None, message: str | None = None,
               answers: dict | None = None, chip: str | None = None) -> dict:
        s = self.session(sid)
        s.turns += 1
        if chip and chip in REFINE_CHIPS:
            s.slots.update(REFINE_CHIPS[chip])
            s.stage = Stage.REFINE
            intent = Intent(action="recommend_food", slots=dict(s.slots), source="chip")
        elif answers:
            s.slots.update(presenter.decode_answers(answers))
            s.stage = Stage.REFINE
            intent = Intent(action="recommend_food", slots=dict(s.slots), source="form")
        else:
            text = (message or chip or "").strip()
            new = self.nlu.parse(text)
            # 새 상품이 나오면 주제 전환: 예산·대상 등 이전 조건은 버리고 구매처만 유지
            if new.slots.get("product") and new.slots.get("product") != s.slots.get("product"):
                keep = {k: s.slots[k] for k in ("mall",) if k in s.slots}
                s.slots = {**keep, **new.slots}
            else:
                s.slots.update(new.slots)
            intent = Intent(action=new.action, context=new.context, slots=dict(s.slots),
                            confidence=new.confidence, source=new.source)

        if intent.action == "recipe":
            s.stage = Stage.CLARIFY
            s.last_items = []
            return self._reply(s, [presenter.text_block("원문 레시피와 보유 재료를 확인하겠습니다. 요리 이름·인분 수·레시피 원문 또는 출처를 알려주세요. 재료는 필수/선택으로 구분하고 단위와 조리 상태를 확인한 뒤 부족분만 계산합니다." )], intent=intent)

        if not intent.slots.get("product"):
            s.stage = Stage.CLARIFY
            return self._reply(s, presenter.ask_product_blocks(intent))

        query, items = self.rec.recommend(intent, session_id=s.id)
        if self.persist:
            try:
                store.record_offers([x.offer for x in items])
                store.log_search(s.id, query, intent, len(items), self.rec.last_engine)
            except Exception:
                pass
        s.stage = Stage.RECOMMEND
        s.last_items = items
        blocks = presenter.recommendation_blocks(intent, items, active_malls=self.rec.markets.active)
        return self._reply(s, blocks, intent=intent)

    def _reply(self, s: Session, blocks: list[Block], intent: Intent | None = None) -> dict:
        return {
            "session_id": s.id, "stage": s.stage.value, "slots": s.slots,
            "intent": intent.model_dump() if intent else None,
            "blocks": [b.model_dump() for b in blocks],
        }
