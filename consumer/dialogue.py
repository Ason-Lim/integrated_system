"""대화 상태 머신 — docs/architecture/CONVERSATION_STATE_MACHINE.md(V2) 의 축소 구현.

원칙: "추천 먼저, 조정은 대화로". 상품만 알면 바로 추천하고, 빠진 조건(예산·구매처·대상)은
추천 카드 '아래'에서 선택형으로 묻는다. 한 번에 최대 2개 질문.

UNDERSTAND ──(상품 모름)──▶ CLARIFY ──▶ RECOMMEND ──▶ REFINE ──▶ RECOMMEND ...
                                              │
                                              └─(follow_up 칩)──▶ EXPLORE ──▶ RECOMMEND ...
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

from shared.engines.recommender import Recommender
from shared.models import Block, Intent
from shared.nlu.service import NLUService
from shared import store
from shared.decision_ledger import LedgerEntry, invalidated, open_entry
from shared import persona
from consumer import presenter


class Stage(str, Enum):
    UNDERSTAND = "understand"
    CLARIFY = "clarify"
    RECOMMEND = "recommend"
    REFINE = "refine"
    EXPLORE = "explore"


@dataclass
class Session:
    id: str
    stage: Stage = Stage.UNDERSTAND
    slots: dict = field(default_factory=dict)
    turns: int = 0
    last_items: list = field(default_factory=list)
    last_query: str | None = None
    # 레시피 멀티턴 상태
    recipe_title: str | None = None
    recipe_ingredients: list[dict] = field(default_factory=list)  # 누적 재료
    recipe_mode: bool = False
    # GeoIP 로 판별한 클라이언트 국가 코드 (ISO 3166-1 alpha-2). 미확인 시 None.
    country_code: str | None = None
    # Decision Freshness Ledger (shadow)
    ledger: LedgerEntry | None = None
    # 근거 기반 페르소나 (SimInter, shadow)
    persona: persona.Persona | None = None


# 빠른 응답 칩 → 슬롯 변경 (서버가 해석, LLM 불필요)
REFINE_CHIPS = {
    "더 저렴한 것": {"priority": "price"},
    "후기 많은 순": {"priority": "trust"},
    "프리미엄으로": {"priority": "quality"},
    "선물용으로": {"purpose": "gift"},
}

# follow_up 칩 → EXPLORE 액션 (LLM 없이 규칙 기반 처리)
# presenter._follow_up_chips / comparison_pair 의 value 형식과 매칭된다.
EXPLORE_PATTERNS: list[tuple[str, str]] = [
    ("더 저렴한 곳", "cheaper"),
    ("단가 비교", "unit_compare"),
    ("배송비 확인", "shipping"),
    ("비슷한 상품", "similar"),
    ("가격 비교", "pair_price"),
    ("비교", "pair_compare"),
]


def _explore_action(text: str) -> str | None:
    """follow_up 칩 문구에서 EXPLORE 액션을 판별한다."""
    for needle, action in EXPLORE_PATTERNS:
        if needle in text:
            return action
    return None


def _match_item(items: list, text: str):
    """칩 문구에 포함된 상품 제목으로 last_items 에서 항목을 찾는다."""
    for so in items:
        title = getattr(so.offer, "title", "") or ""
        if title and title in text:
            return so
    return None


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
               answers: dict | None = None, chip: str | None = None,
               country_code: str | None = None) -> dict:
        s = self.session(sid)
        s.turns += 1
        if country_code:
            s.country_code = country_code

        # follow_up 칩 → EXPLORE (LLM 호출 없이 규칙 기반 즉시 응답)
        explore_text = (message or chip or "").strip()
        action = _explore_action(explore_text) if explore_text else None
        if action and s.last_items:
            s.stage = Stage.EXPLORE
            return self._explore(s, action, explore_text)

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

        # SimInter: 실제 행동 근거로만 선호를 추론한다. 근거 없는 선호는 UNKNOWN 으로 남긴다.
        if self.persist:
            try:
                s.persona = persona.infer(store.behavior_evidence(s.id))
                for k, v in s.persona.slots().items():
                    intent.slots.setdefault(k, v)
            except Exception:
                s.persona = None

        query, items = self.rec.recommend(intent, session_id=s.id)
        # Decision Freshness Ledger: 추천 시점·근거 시점·실행 예정 시점·재검토 마감 기록
        s.ledger = open_entry(intent, [x.offer for x in items])
        if self.persist:
            try:
                store.record_offers([x.offer for x in items])
                store.log_search(s.id, query, intent, len(items), self.rec.last_engine)
                store.record_ledger(s.id, s.ledger)
            except Exception:
                pass
        s.stage = Stage.RECOMMEND
        s.last_items = items
        s.last_query = query
        blocks = presenter.recommendation_blocks(intent, items, active_malls=self.rec.markets.active,
                                                 country_code=s.country_code, ledger=s.ledger,
                                                 persona_unknown=s.persona.unknown if s.persona else None)
        return self._reply(s, blocks, intent=intent)

    # ── EXPLORE: follow_up 칩에 대한 규칙 기반 즉시 응답 ─────────────
    def _explore(self, s: Session, action: str, text: str) -> dict:
        items = s.last_items
        target = _match_item(items, text)

        if action == "cheaper":
            return self._explore_cheaper(s, target)
        if action == "unit_compare":
            return self._explore_unit(s, target)
        if action == "shipping":
            return self._explore_shipping(s, target)
        if action == "similar":
            return self._explore_similar(s, target)
        if action in ("pair_compare", "pair_price"):
            return self._explore_pair(s, action == "pair_price")

        # 매칭 실패 시 안전한 안내
        return self._reply(s, [
            presenter.text_block("어떤 상품을 기준으로 볼지 알려주시면 바로 비교해 드릴게요."),
            Block(type="chips", data={"items": ["더 저렴한 것", "후기 많은 순"], "mode": "chip"}),
        ])

    def _explore_cheaper(self, s: Session, target) -> dict:
        items = s.last_items
        if target is None:
            target = items[0]
        base = target.offer.total_price or target.offer.price or 0
        cheaper = [x for x in items if (x.offer.total_price or x.offer.price or 0) < base]
        cheaper.sort(key=lambda x: (x.offer.total_price or x.offer.price or 0))
        if not cheaper:
            return self._reply(s, [
                presenter.text_block(f"**{target.offer.title}**보다 저렴한 후보는 지금 목록에 없어요. "
                                     "예산 범위를 넓히거나 구매처 제한을 풀면 더 찾아볼 수 있어요."),
                Block(type="chips", data={"items": ["더 저렴한 것", "프리미엄으로"], "mode": "chip"}),
            ])
        head = f"**{target.offer.title}**보다 저렴한 후보 {len(cheaper)}개를 찾았어요."
        blocks = [presenter.text_block(head)]
        if len(cheaper) >= 2:
            blocks.append(Block(type="comparison_pair", data={"pairs": presenter.comparison_pair(cheaper[:2])}))
        else:
            blocks.append(Block(type="product_list",
                                data={"items": [presenter.card(cheaper[0], 1)], "compare": False}))
        blocks.append(Block(type="chips", data={"items": ["단가 비교해줘", "배송비 확인해줘"], "mode": "message"}))
        return self._reply(s, blocks)

    def _explore_unit(self, s: Session, target) -> dict:
        items = s.last_items
        if target is None:
            target = items[0]
        with_unit = [x for x in items if x.offer.unit_price is not None]
        if not with_unit:
            return self._reply(s, [
                presenter.text_block("단가를 계산할 수 있는 상품이 없어요. 용량·수량 정보가 있는 상품으로 다시 찾아볼까요?"),
            ])
        with_unit.sort(key=lambda x: x.offer.unit_price)
        lines = [f"- **{x.offer.title}**: {presenter.won(x.offer.unit_price)}/단위" for x in with_unit[:5]]
        return self._reply(s, [
            presenter.text_block(f"단가 기준 정렬 결과예요.\n" + "\n".join(lines)),
            Block(type="chips", data={"items": ["더 저렴한 것", "비슷한 상품 더 보여줘"], "mode": "message"}),
        ])

    def _explore_shipping(self, s: Session, target) -> dict:
        items = s.last_items
        if target is None:
            target = items[0]
        o = target.offer
        fee = "미확인" if o.shipping_fee is None else presenter.won(o.shipping_fee)
        total = "미확인" if o.total_price is None else presenter.won(o.total_price)
        return self._reply(s, [
            presenter.text_block(
                f"**{o.title}**\n- 상품가: {presenter.won(o.price)}\n- 배송비: {fee}\n- 실구매가: {total}"
            ),
            Block(type="chips", data={"items": ["더 저렴한 것", "단가 비교해줘"], "mode": "message"}),
        ])

    def _explore_similar(self, s: Session, target) -> dict:
        items = s.last_items
        if target is None:
            target = items[0]
        others = [x for x in items if x is not target]
        if not others:
            return self._reply(s, [
                presenter.text_block("지금 목록에는 비슷한 후보가 더 없어요. 조건을 조금 바꿔 다시 찾아볼까요?"),
                Block(type="chips", data={"items": ["더 저렴한 것", "프리미엄으로"], "mode": "chip"}),
            ])
        head = f"**{target.offer.title}**와 함께 볼 만한 후보예요."
        blocks = [presenter.text_block(head)]
        if len(others) >= 2:
            blocks.append(Block(type="comparison_pair", data={"pairs": presenter.comparison_pair(others[:2])}))
        else:
            blocks.append(Block(type="product_list",
                                data={"items": [presenter.card(others[0], 1)], "compare": False}))
        blocks.append(Block(type="chips", data={"items": ["더 저렴한 것", "후기 많은 순"], "mode": "chip"}))
        return self._reply(s, blocks)

    def _explore_pair(self, s: Session, price_only: bool) -> dict:
        items = s.last_items[:2]
        if len(items) < 2:
            return self._reply(s, [
                presenter.text_block("비교할 후보가 2개 이상 필요해요. 조건을 조금 넓혀 다시 찾아볼까요?"),
            ])
        a, b = items
        pa = a.offer.total_price or a.offer.price
        pb = b.offer.total_price or b.offer.price
        lines = [f"- **{a.offer.title}**: {presenter.won(pa)}"]
        if not price_only:
            lines.append(f"  - 근거: {', '.join(a.evidence) if a.evidence else '정보 없음'}")
        lines.append(f"- **{b.offer.title}**: {presenter.won(pb)}")
        if not price_only:
            lines.append(f"  - 근거: {', '.join(b.evidence) if b.evidence else '정보 없음'}")
        if pa is not None and pb is not None:
            diff = abs(pa - pb)
            cheaper = a if pa < pb else b
            lines.append(f"\n가격 차이는 **{presenter.won(diff)}**이고, 더 저렴한 쪽은 **{cheaper.offer.title}**이에요.")
        return self._reply(s, [
            presenter.text_block("두 후보를 비교했어요.\n" + "\n".join(lines)),
            Block(type="chips", data={"items": ["더 저렴한 것", "단가 비교해줘"], "mode": "message"}),
        ])

    def _reply(self, s: Session, blocks: list[Block], intent: Intent | None = None) -> dict:
        ledger = s.ledger.to_dict() if s.ledger else None
        return {
            "session_id": s.id, "stage": s.stage.value, "slots": s.slots,
            "intent": intent.model_dump() if intent else None,
            "ledger": ledger,
            "persona": s.persona.audit() if s.persona else None,
            "blocks": [b.model_dump() for b in blocks],
        }
