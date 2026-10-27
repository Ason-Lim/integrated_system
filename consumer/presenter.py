"""추천 결과 → 화면 블록.

블록 타입 (web/index.html 이 렌더링, 다른 채널도 같은 JSON 사용 가능)
  text           : 짧은 안내 문장 (굵게 **...** 지원)
  product_list   : 카드 목록 (배지·실구매가·단가·근거칩·미확인칩·출처·조회시각·링크)
  comparison_pair: 2개씩 묶은 비교 카드 (각 카드에 reasoning·follow_up 칩 포함)
  notice         : 가격 기준 시각 / 예시 데이터 안내
  verdict        : "내 추천은 ○○!" 한 줄 결론
  clarify_form   : 빠진 조건을 묻는 선택형 질문 (라디오) + CTA
  chips          : 다음 행동 제안 (더 저렴한 것 / 후기 많은 순 ...)
"""
from __future__ import annotations

from datetime import datetime, timezone

from shared.decision_ledger import LedgerEntry, refresh_needed
from shared.logistics.shipping_agency import (
    AgencyUnavailable,
    ShippingRequest,
    total_landed_cost,
)
from shared.markets.base import MALL_LABELS
from shared.models import Block, Intent, ScoredOffer, notice_block, text_block

RECIPIENT_KR = {"senior": "부모님", "friends": "친구", "business": "거래처", "kids": "아이", "partner": "연인", "self": "나"}
OCCASION_KR = {"birthday": "생일", "chuseok": "추석", "seollal": "설", "thanks": "감사", "housewarming": "집들이",
               "camping": "캠핑", "party": "홈파티"}
LADDER = [5000, 10000, 20000, 30000, 50000, 100000, 200000, 300000, 500000, 1000000]


def won(v: int | None) -> str:
    return "미확인" if v is None else f"{v:,}원"


def man(v: int) -> str:
    return f"{v // 10000}만원" if v % 10000 == 0 else f"{v:,}원"


def ago(dt: datetime) -> tuple[str, bool]:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    stale = h >= 24
    if h < 1:
        return "방금 조회", stale
    if h < 24:
        return f"{int(h)}시간 전 조회", stale
    return f"{int(h // 24)}일 전 조회", stale


def card(so: ScoredOffer, rank: int, ledger: LedgerEntry | None = None) -> dict:
    o = so.offer
    when, stale = ago(o.observed_at)
    mall = o.mall_label or MALL_LABELS.get(o.mall, o.mall)
    # Decision Freshness Ledger (shadow) — 카드 단위로 유효성 정보를 실어 보낸다.
    ledger_fields: dict = {}
    if ledger is not None:
        rn = refresh_needed(ledger, [o])
        ledger_fields = {
            "decision_time": ledger.decision_time.isoformat(),
            "evidence_time": ledger.evidence_time.isoformat(),
            "revision_deadline": ledger.revision_deadline.isoformat(),
            "watch_conditions": list(ledger.watch_conditions),
            "stale_decision": rn["expired"],
            "refresh_needed": rn["needed"],
            "refresh_reasons": rn["changed"],
        }
    return {
        "decision": so.decision, "score_source": so.score_source, "rank": rank, "mall": o.mall, "pid": o.mall_product_id, "score": so.score,
        "badges": so.badges, "title": o.title, "image": o.image_url,
        "price": o.price, "shipping_fee": o.shipping_fee, "total": o.total_price,
        "original_price": o.original_price, "unit_price": o.unit_price, "unit_count": o.unit_count,
        "spec": o.spec, "reason": so.reason, "evidence": so.evidence, "unverified": so.unverified,
        "source": mall, "observed": when, "stale": stale, "url": o.url, "is_sample": o.is_sample,
        "cta": f"{mall}에서 보기" if o.url else "예시 데이터 (링크 없음)",
        # Merchant Decision Sufficiency (shadow)
        "rankable": so.rankable, "not_rankable_reason": so.not_rankable_reason,
        "rankability": o.rankability, "evidence_coverage": o.evidence_coverage,
        "missing_terms": o.missing_terms,
        **ledger_fields,
    }


def _follow_up_chips(so: ScoredOffer) -> list[dict]:
    """카드별 후속 질문 칩. 클릭 시 message 모드로 대화에 전송된다."""
    chips: list[dict] = []
    if so.offer.total_price is not None:
        chips.append({"label": "이거 더 저렴한 곳 있어?", "value": f"{so.offer.title} 더 저렴한 곳"})
    if so.offer.unit_price is not None:
        chips.append({"label": "단가 비교해줘", "value": f"{so.offer.title} 단가 비교"})
    if so.unverified:
        chips.append({"label": "배송비 확인해줘", "value": f"{so.offer.title} 배송비 확인"})
    if so.offer.mall:
        chips.append({"label": "비슷한 상품 더 보여줘", "value": f"{so.offer.title} 비슷한 상품"})
    return chips[:3]


def _reasoning(so: ScoredOffer) -> str:
    """카드 하단에 노출할 추천 이유 한 줄."""
    if so.reason:
        return so.reason
    if so.evidence:
        return f"{', '.join(so.evidence)} 근거로 추천했어요."
    return "조건 적합도와 가격을 함께 고려했어요."


def comparison_pair(items: list[ScoredOffer], start_rank: int = 1,
                    ledger: LedgerEntry | None = None) -> list[dict]:
    """상품 리스트를 2개씩 묶어 비교 카드 쌍을 만든다.

    반환 구조 (각 원소가 하나의 comparison_pair 블록 data):
      {
        "pair_index": 0,
        "cards": [
          { ...card(so, rank)..., "reasoning": str, "follow_up": [{"label","value"}] },
          { ...card(so, rank)..., "reasoning": str, "follow_up": [{"label","value"}] },
        ],
        "compare": True,          # 두 카드 비교 UI 표시 여부
        "chips": [{"label","value"}],  # 쌍 단위 후속 질문 (선택)
      }
    마지막에 카드가 1장만 남으면 cards 길이가 1이 된다.
    """
    pairs: list[dict] = []
    for i in range(0, len(items), 2):
        chunk = items[i:i + 2]
        cards = []
        for j, so in enumerate(chunk):
            c = card(so, start_rank + i + j, ledger=ledger)
            c["reasoning"] = _reasoning(so)
            c["follow_up"] = _follow_up_chips(so)
            cards.append(c)
        pair_chips: list[dict] = []
        if len(cards) == 2:
            pair_chips = [
                {"label": "둘 중 뭐가 나아?", "value": f"{cards[0]['title']} vs {cards[1]['title']} 비교"},
                {"label": "가격만 비교", "value": f"{cards[0]['title']} vs {cards[1]['title']} 가격 비교"},
            ]
        pairs.append({
            "pair_index": i // 2,
            "cards": cards,
            "compare": len(cards) == 2,
            "chips": pair_chips,
        })
    return pairs


def budget_buckets(items: list[ScoredOffer]) -> list[dict]:
    prices = sorted((x.offer.total_price or x.offer.price) for x in items) or [20000]
    mid = prices[len(prices) // 2]
    lo = max([v for v in LADDER if v <= mid] or [LADDER[0]])
    hi = next((v for v in LADDER if v > lo), lo * 2)
    return [
        {"label": f"{man(lo)} 이하", "value": f"0-{lo}"},
        {"label": f"{man(lo)}~{man(hi)}", "value": f"{lo}-{hi}"},
        {"label": f"{man(hi)} 이상", "value": f"{hi}-"},
    ]


def decode_answers(ans: dict) -> dict:
    """폼 응답 → 슬롯. None 은 '조건 해제'를 뜻한다."""
    out: dict = {}
    if b := ans.get("budget"):
        lo, _, hi = b.partition("-")
        out["budget_min"] = int(lo) if lo and lo != "0" else None
        out["budget_max"] = int(hi) if hi else None
    if m := ans.get("mall"):
        out["mall"] = None if m == "any" else m
    if r := ans.get("recipient"):
        out["recipient"] = r
        out["purpose"] = "gift"
    if p := ans.get("priority"):
        out["priority"] = p
    return out


def ask_product_blocks(intent: Intent) -> list[Block]:
    who = RECIPIENT_KR.get(intent.slots.get("recipient", ""), "")
    lead = f"{who}께 드릴 " if who and who != "나" else ""
    return [
        text_block(f"좋아요. {lead}어떤 상품을 찾고 계세요? 상품명이나 종류만 알려주시면 바로 골라 드릴게요."),
        Block(type="chips", data={"items": ["견과류 선물세트", "사과 선물세트", "두바이 쫀득쿠키", "캠핑 고기"], "mode": "message"}),
    ]


def _estimate_landed(so: ScoredOffer) -> dict | None:
    """상품 1건의 최종 견적을 계산한다. 실패 시 None (예시 데이터를 실제 견적으로 섞지 않는다)."""
    o = so.offer
    price = o.price
    if price is None:
        return None
    # Offer 가격은 KRW 기준. 배송대행지 API 는 USD 신고가를 요구하므로 환율로 역산한다.
    fx = 1350.0
    product_usd = price / fx
    req = ShippingRequest(
        origin_country="US",
        dest_country="KR",
        weight_kg=1.0,          # TODO: 상품 스펙에서 무게/부피를 얻을 수 있게 되면 대체
        declared_value_usd=product_usd,
    )
    try:
        lc = total_landed_cost(product_usd=product_usd, req=req)
    except AgencyUnavailable:
        return None
    return {
        "agency": lc.agency,
        "shipping_krw": lc.shipping_krw,
        "agency_fee_krw": lc.agency_fee_krw,
        "duty_krw": lc.duty_krw,
        "vat_krw": lc.vat_krw,
        "total_krw": lc.total_krw,
        "eta_days_min": lc.eta_days_min,
        "eta_days_max": lc.eta_days_max,
        "fx_krw_per_usd": lc.fx_krw_per_usd,
        "notes": lc.notes,
    }


def _shipping_options_block(items: list[ScoredOffer]) -> Block:
    """해외 사용자에게만 노출하는 배송 대행 옵션 안내 + 예상 견적."""
    options = [
        {"id": "forwarder", "label": "배송 대행지 이용", "desc": "현지 주소로 받은 뒤 국제 배송으로 전달"},
        {"id": "direct", "label": "해외 직배송", "desc": "판매처가 해외로 직접 발송하는 경우"},
        {"id": "agent", "label": "구매 대행 서비스", "desc": "결제·통관을 대행해 주는 서비스"},
    ]
    estimates = []
    for so in items[:3]:
        est = _estimate_landed(so)
        entry = {"title": so.offer.title, "mall": so.offer.mall}
        if est:
            entry["estimate"] = est
        estimates.append(entry)
    note = "현재 위치가 한국이 아니에요. 아래 방법으로 받을 수 있어요."
    if not any("estimate" in e for e in estimates):
        note += " 배송대행지 API 키가 설정되지 않아 예상 견적은 표시할 수 없어요."
    return Block(type="shipping_options", data={
        "title": "해외 배송 옵션",
        "note": note,
        "options": options,
        "items": estimates,
    })


def recommendation_blocks(intent: Intent, items: list[ScoredOffer], active_malls: list[str],
                          country_code: str | None = None,
                          ledger: LedgerEntry | None = None,
                          persona_unknown: list[str] | None = None) -> list[Block]:
    s = intent.slots
    product = s.get("product", "")
    compare = intent.action == "compare_info"
    if not items and compare:
        return [text_block(f"**{product}** 관련 상품을 찾지 못했어요. 비교하고 싶은 품종이나 산지 이름을 알려주시겠어요?")]
    if not items:
        tips = []
        if s.get("budget_max") or s.get("budget_min"):
            tips.append("예산 범위를 넓혀")
        if s.get("mall"):
            tips.append("구매처 제한을 풀어")
        return [text_block(f"**{product}** 조건에 맞는 상품을 찾지 못했어요."
                           + (f" {' / '.join(tips)} 다시 찾아볼까요?" if tips else " 다른 표현으로 알려주시겠어요?")),
                Block(type="clarify_form", data=_form(s, items, force_budget=True))]

    mall = MALL_LABELS.get(s.get("mall") or "", "")
    ctx = []
    if s.get("recipient") in RECIPIENT_KR and s["recipient"] != "self":
        ctx.append(f"{RECIPIENT_KR[s['recipient']]}께 드릴")
    if s.get("occasion") in OCCASION_KR:
        ctx.append(f"{OCCASION_KR[s['occasion']]}용")
    if s.get("budget_max") or s.get("budget_min"):
        lo, hi = s.get("budget_min"), s.get("budget_max")
        ctx.append(f"{man(lo)}~{man(hi)}" if lo and hi else f"{man(hi)} 이하" if hi else f"{man(lo)} 이상")
    all_sample = all(x.offer.is_sample for x in items)
    where = f"{mall}에서 살 수 있는 " if mall and not all_sample else ""
    head = f"{where}{' '.join(ctx) + ' ' if ctx else ''}**{product}** 중에는 이 {len(items)}가지를 추천해요."
    if compare:
        axis = {"origin": "산지", "variety": "품종"}.get(s.get("compare_axis") or "", "상품")
        head = (f"**{product}** {axis} 비교 질문으로 이해했어요. 차이는 아래 후보의 상품 정보(제목·설명)로 "
                "확인되는 범위에서만 보여드리고, 확인되지 않은 맛·당도 차이는 단정하지 않을게요.")

    cards = [card(x, i + 1, ledger=ledger) for i, x in enumerate(items)]
    rankable_items = [x for x in items if x.rankable]
    not_rankable = [c for c in cards if not c["rankable"]]
    blocks = [text_block(head)]
    # 상품이 있으면 항상 product_list/comparison_pair 를 notice 보다 먼저 노출한다.
    if len(rankable_items) >= 2:
        blocks.append(Block(type="comparison_pair",
                            data={"pairs": comparison_pair(rankable_items, ledger=ledger)}))
    elif rankable_items:
        blocks.append(Block(type="product_list",
                            data={"items": [card(rankable_items[0], 1, ledger=ledger)], "compare": False}))
    elif cards:
        blocks.append(Block(type="product_list", data={"items": cards, "compare": False}))
    if not_rankable:
        blocks.append(notice_block(
            f"구매조건(총비용·반품·서비스일·옵션) 근거가 부족한 후보 {len(not_rankable)}개는 "
            "순위 비교에서 분리했어요. 아래 목록은 참고용입니다.", "warn"))
        blocks.append(Block(type="product_list", data={"items": not_rankable, "compare": False}))

    stale = any(c["stale"] for c in cards)
    note = "가격·리뷰 수는 표시된 조회 시각 기준이며 현재 가격·재고와 다를 수 있어요."
    if any(c["shipping_fee"] is None for c in cards):
        note += " 배송비가 '미확인'인 상품은 실구매가가 더 높을 수 있어요."
    if any(c["is_sample"] for c in cards):
        note = "지금은 **예시 데이터**로 동작 중이에요 (마켓 API 키 미설정). " + note
    blocks.append(notice_block(note, "warn" if stale or any(c["is_sample"] for c in cards) else "info"))

    # Decision Freshness Ledger: 결제 직전 재검토가 필요하면 알림을 띄운다.
    if ledger is not None:
        rn = refresh_needed(ledger, [x.offer for x in items])
        if rn["needed"]:
            reasons = {c["reason"] for c in rn["changed"]}
            if "action_window_expired" in reasons or rn["expired"]:
                msg = "추천 유효 기한이 지났어요. 결제 전에 가격·배송비를 다시 확인해 주세요."
            elif "price_changed" in reasons:
                msg = "추천 이후 **가격이 변경**됐어요. 결제 전에 최신 가격을 확인해 주세요."
            elif "shipping_fee_changed" in reasons:
                msg = "추천 이후 **배송비가 변경**됐어요. 실구매가를 다시 확인해 주세요."
            elif "delivery_date_changed" in reasons:
                msg = "추천 이후 **배송 예정일이 변경**됐어요. 받으실 날짜를 다시 확인해 주세요."
            else:
                msg = "추천 이후 상품 조건이 변경됐어요. 결제 전에 다시 확인해 주세요."
            blocks.append(notice_block(msg, "warn"))

    top = rankable_items[0] if rankable_items else items[0]
    why = (f"{', '.join(top.evidence)}로 근거가 가장 탄탄하고 조건에도 잘 맞아요" if top.evidence
           else "조건 적합도와 가격을 함께 봤어요")
    if top.rankable and top.decision.get("status") == "RANKABLE":  # type: ignore[union-attr]
        blocks.append(Block(type="verdict", data={"md": f"우선 비교할 후보는 **{top.offer.title}**입니다. {why}."}))
    else:
        blocks.append(notice_block("현재는 탐색 후보입니다. 옵션·배송·반품·출처가 확인되기 전에는 최종 추천을 확정하지 않습니다.", "warn"))
    if any(x.offer.url for x in items):
        blocks.append(notice_block("일부 구매 링크에서 수수료가 발생할 수 있으며 무료 서비스 운영에 도움이 됩니다. 협력 여부는 일반 추천 순위에 반영하지 않습니다."))

    # 해외 사용자(KR 이 아닌 국가 코드가 확인된 경우)에게만 배송 대행 옵션 노출
    if country_code and country_code.upper() != "KR":
        blocks.append(_shipping_options_block(items))

    form = _form(s, items, persona_unknown=persona_unknown, skip_budget=compare)
    if form["questions"]:
        blocks.append(Block(type="clarify_form", data=form))
    blocks.append(Block(type="chips", data={"items": ["더 저렴한 것", "후기 많은 순", "프리미엄으로"], "mode": "chip"}))
    return blocks


def _form(s: dict, items: list[ScoredOffer], force_budget: bool = False,
          persona_unknown: list[str] | None = None, skip_budget: bool = False) -> dict:
    qs = []
    # 정보·비교 질문(compare_info)에는 예산을 묻지 않는다.
    if not skip_budget and (force_budget or not (s.get("budget_max") or s.get("budget_min"))):
        qs.append({"id": "budget", "label": "예산은 어느 정도인가요?", "options": budget_buckets(items)})
    if s.get("purpose") == "gift" and not s.get("recipient"):
        qs.append({"id": "recipient", "label": "누구에게 드리나요?", "options": [
            {"label": "부모님·어르신", "value": "senior"}, {"label": "거래처·직장", "value": "business"},
            {"label": "친구·연인", "value": "friends"}]})
    elif not s.get("mall") and len(qs) < 2:
        qs.append({"id": "mall", "label": "주로 어디서 사세요?", "options": [
            {"label": "쿠팡", "value": "coupang"}, {"label": "네이버", "value": "naver"}, {"label": "상관없음", "value": "any"}]})
    # SimInter: 행동 근거가 없는 선호는 지어내지 않고 직접 묻는다.
    if persona_unknown and "priority" in persona_unknown and len(qs) < 2:
        qs.append({"id": "priority", "label": "고를 때 무엇을 가장 중요하게 보세요?", "options": [
            {"label": "가격", "value": "price"}, {"label": "품질", "value": "quality"},
            {"label": "후기·신뢰", "value": "trust"}]})
    return {"questions": qs[:2], "submit": "이 조건으로 다시 추천받기"}
