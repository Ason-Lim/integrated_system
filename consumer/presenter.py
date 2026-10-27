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

import re

from datetime import datetime, timezone

from shared.decision_ledger import LedgerEntry, refresh_needed
from shared.logistics.shipping_agency import (
    AgencyUnavailable,
    ShippingRequest,
    total_landed_cost,
)
from shared.markets.base import MALL_LABELS, NO_RATING_MALLS
from shared import affiliate, food24_catalog
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
        # 평점·후기·도착일을 판매처 API가 주지 않으면 '판매처에서 확인' 안내 (미확인 경고 아님)
        "check_at_mall": o.mall in NO_RATING_MALLS and o.rating is None,
        "delivery_hint": "로켓배송" if (o.raw or {}).get("isRocket") else None,
        # 식약처 품목제조보고(식품정보24)와 제조사까지 맞는 경우에만 원재료·소비기한 근거를 싣는다
        "public_info": _public_info(o.title),
        # 제휴(수수료) 링크 여부 — 카드·구매 버튼에 표기
        "affiliate": bool(o.url) and affiliate.is_affiliate(o.mall),
        "affiliate_program": affiliate.program(o.mall) if o.url else None,
        # Merchant Decision Sufficiency (shadow)
        "rankable": so.rankable, "not_rankable_reason": so.not_rankable_reason,
        "rankability": o.rankability, "evidence_coverage": o.evidence_coverage,
        "missing_terms": o.missing_terms,
        **ledger_fields,
    }


def _public_info(title: str) -> dict | None:
    try:
        rec = food24_catalog.match(title)
    except Exception:
        return None
    return food24_catalog.public_info(rec) if rec and rec.get("company_matched") else None


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
        first = (product.split() or [product])[0]
        blocks = [text_block(f"**{product}** 조건에 맞는 상품을 찾지 못했어요."
                             + (f" {' / '.join(tips)} 다시 찾아볼까요?" if tips else " 다른 표현으로 알려주시겠어요?"))]
        if tips:   # 예산·구매처 조건이 있을 때만 조건 조정 질문이 의미 있다
            blocks.append(Block(type="clarify_form", data=_form(s, items, force_budget=True)))
        elif first and first != product:
            blocks.append(Block(type="chips", data={"mode": "message",
                                                    "items": [{"label": f"'{first}'로 다시 찾기", "value": f"{first} 추천해줘"}]}))
        return blocks

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
    # 수수료 고지는 응답 '첫 부분'에 넣는다 (with_disclosure, DialogueManager._reply 에서 공통 처리)

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


# ── 레시피 (공공 레시피 DB 원문) ─────────────────────────────────
# 장보기 칩에서 뺄 기본 양념·물 (대부분 집에 있어 상품 검색 가치가 낮다)
PANTRY = {"물", "소금", "설탕", "후추", "후춧가루", "식용유", "참기름", "들기름", "간장", "진간장", "국간장",
          "다진마늘", "마늘", "올리브유", "식초", "소금물", "깨소금", "참깨", "깨소금", "통깨", "맛술", "물엿", "올리고당", "고춧가루"}


def _pantry(name: str) -> bool:
    return name.replace(" ", "") in PANTRY


def _recipe_facts(r: dict) -> str:
    def last(v):  # '주식류 · 밥류 · 밥류 · 잡곡밥' → '잡곡밥' (분류 경로는 마지막 단계만)
        parts = [p.strip() for p in re.split(r"[·>]", str(v or "")) if p.strip()]
        return parts[-1] if parts else None
    bits = [r.get("region"), r.get("house"), last(r.get("category")), last(r.get("method")),
            r.get("time"), r.get("servings"), r.get("level")]
    kcal = r.get("kcal")
    if kcal:
        bits.append(kcal if "cal" in str(kcal).lower() else f"{kcal}kcal")
    return " · ".join(dict.fromkeys(str(b) for b in bits if b))


def recipe_list_blocks(query_terms: list[str], recipes: list[dict]) -> list[Block]:
    head = " ".join(query_terms) or "요청하신 요리"
    lines = [f"**{head}** 레시피를 공공 레시피 DB에서 {len(recipes)}개 찾았어요. 보고 싶은 레시피를 골라 주세요."]
    for r in recipes:
        main = [i["name"] for i in r.get("ingredients", []) if not _pantry(i["name"])][:4]
        desc = " · ".join(x for x in [_recipe_facts(r), f"재료 {len(r.get('ingredients', []))}가지" if r.get("ingredients") else ""] if x)
        lines.append(f"- **{r['name']}** — {desc}" if desc else f"- **{r['name']}**")
        if main:
            lines.append(f"  - 주재료: {', '.join(main)}")
    return [
        text_block("\n".join(lines)),
        Block(type="chips", data={"mode": "message",
                                  "items": [{"label": r["name"], "value": f"{r['name']} 레시피 보기"} for r in recipes]}),
    ]


def recipe_detail_blocks(r: dict) -> list[Block]:
    md = [f"**{r['name']}**"]
    facts = _recipe_facts(r)
    if facts:
        md.append(facts)
    if r.get("summary"):
        md.append(r["summary"][:400])
    ings = r.get("ingredients") or []
    md.append("")
    md.append("**재료**")
    if ings:
        md += [f"- {i['name']} {i.get('amount') or ''}".rstrip() for i in ings]
    elif r.get("ingredients_raw"):
        md.append(r["ingredients_raw"])
    if r.get("steps"):
        md.append("")
        md.append("**만드는 법**")
        md += [f"- {n}) {st['text']}" for n, st in enumerate(r["steps"], 1)]
    if r.get("tip"):
        md += ["", f"**참고** {r['tip']}"]
    md.append("")
    src = r.get("source_name") or "공공 레시피 DB"
    if r.get("literature"):
        src += f" · 문헌: {r['literature']}"
    md.append(f"출처: {src} (원문 그대로 옮겼어요. 분량은 출처 기준입니다)")
    shop = [i["name"] for i in ings if not _pantry(i["name"])][:5]
    blocks = [text_block("\n".join(md))]
    if shop:
        blocks.append(text_block("필요한 재료를 바로 찾아볼까요? 집에 있는 재료는 빼고 골라 주세요."))
        blocks.append(Block(type="chips", data={"mode": "message",
                                                "items": [{"label": f"{n} 사러 가기", "value": f"{n} 추천해줘"} for n in shop]}))
    return blocks



# ── 식재료 보관·손질 (농사로 공공 자료) ─────────────────────────────
def storage_blocks(guide: dict | None, asked: str, recipes_available: bool = False) -> list[Block]:
    word = asked or (guide or {}).get("name") or "이 식재료"
    chips = [{"label": f"{word} 상품 보기", "value": f"{word} 추천해줘"}]
    if recipes_available:
        chips.append({"label": f"{word} 레시피", "value": f"{word} 레시피 알려줘"})
    if not guide:
        return [text_block(f"**{word}** 보관·손질 방법은 확인된 공공 자료(농촌진흥청 농사로)에서 찾지 못했어요. "
                           "근거 없는 보관 기간이나 방법은 안내하지 않을게요. 상품 페이지의 보관 안내를 함께 확인해 주세요."),
                Block(type="chips", data={"mode": "message", "items": chips})]
    md = [f"**{word} 보관·손질 방법**"]
    if guide.get("name") and guide["name"] != word:
        md.append(f"공공 자료의 **{guide['name']}** 항목 기준이에요.")
    for key, title in (("storage", "보관법"), ("prep", "손질법"), ("eat", "먹는 법"), ("purchase", "고르는 법")):
        rows = guide.get(key) or []
        if rows:
            md += ["", f"**{title}**"] + [f"- {r}" for r in rows]
    md += ["", f"출처: {guide.get('source_name') or '농촌진흥청 농사로'} (원문 내용 그대로 옮겼어요)"]
    return [text_block("\n".join(md)), Block(type="chips", data={"mode": "message", "items": chips})]



# ── 지역 정보 (농사로 지역특산물·농가맛집·향토/종가음식) ─────────────
ASK_REGIONS = ["경북 특산물", "전남 특산물", "강원 특산물", "제주 특산물"]


def local_blocks(region: str | None, specialties: list[dict], restaurants: list[dict],
                 recipes: list[dict], data_ready: bool) -> list[Block]:
    if not region:
        msg = ("어느 지역이 궁금하세요? 시군 이름(예: 문경, 안동)이나 도 이름으로 물어봐 주세요."
               if data_ready else "지역 정보(농사로 지역특산물·농가맛집)가 아직 준비되지 않았어요.")
        return [text_block(msg), Block(type="chips", data={"mode": "message", "items": ASK_REGIONS})]
    if not (specialties or restaurants or recipes):
        return [text_block(f"**{region}** 지역의 특산물·농가맛집을 공공 자료(농촌진흥청 농사로)에서 찾지 못했어요.")]
    md = [f"**{region}** 지역 정보예요."]
    if specialties:
        md += ["", "**지역특산물**"] + [f"- {r['name']} ({r['region']})" for r in specialties[:10]]
        if len(specialties) > 10:
            md.append(f"- 외 {len(specialties) - 10}개")
    if restaurants:
        md += ["", "**농가맛집**"]
        for r in restaurants[:3]:
            from shared.local_knowledge import menu_names
            # API 대표메뉴 필드가 짧은 메뉴명이면 그대로, 아니면 본문의 '대표 상차림' 제목들
            menus = [r["menu"]] if r.get("menu") and len(r["menu"]) <= 40 else menu_names(r)
            bits = [r.get("address"), f"대표메뉴 {', '.join(menus)}" if menus else None,
                    r.get("hours"), f"휴무 {r['closed']}" if r.get("closed") else None, r.get("tel")]
            md.append(f"- **{r['name']}** — " + " · ".join(b for b in bits if b))
    if recipes:
        md += ["", "**이 지역의 향토·종가음식**"] + [f"- {r['name']}" + (f" ({r['house']})" if r.get("house") else "")
                                               for r in recipes]
    md += ["", "출처: 농촌진흥청 농사로 지역특산물·농가맛집·향토음식 (영업 정보는 방문 전 확인해 주세요)"]
    chips = [{"label": f"{r['name']} 사러 가기", "value": f"{region} {r['name']} 추천해줘"} for r in specialties[:3]]
    chips += [{"label": f"{r['name']} 레시피", "value": f"{r['name']} 레시피 보기"} for r in recipes[:2]]
    blocks = [text_block("\n".join(md))]
    if chips:
        blocks.append(Block(type="chips", data={"mode": "message", "items": chips}))
    return blocks


def specialty_note(sp: dict) -> Block:
    return text_block(f"참고: **{sp['name']}**은(는) 농촌진흥청 농사로 지역특산물에 등록된 **{sp['region']}** 특산물이에요.")



# ── 제휴 링크 고지 (응답 첫 부분) ─────────────────────────────────


def _malls_in(blocks: list[Block]) -> list[str]:
    malls: list[str] = []
    def walk(x):
        if isinstance(x, dict):
            if x.get("url") and x.get("mall"):
                malls.append(x["mall"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for b in blocks:
        if b.type in ("product_list", "comparison_pair", "candidate_compare", "sponsored_list"):
            walk(b.data)
    return malls


def with_disclosure(blocks: list[Block]) -> list[Block]:
    """제휴 링크가 있는 응답이면 맨 앞에 고지 블록을 붙인다 (이미 있으면 그대로)."""
    if any(b.type == "notice" and (b.data or {}).get("affiliate") for b in blocks):
        return blocks
    text = affiliate.disclosure(_malls_in(blocks))
    if not text:
        return blocks
    return [Block(type="notice", data={"md": text, "tone": "info", "affiliate": True})] + blocks



def recipe_not_found_blocks(word: str) -> list[Block]:
    return [text_block(f"**{word}** 레시피를 공공 레시피 DB(식품안전나라·농식품정보누리·농사로)에서 찾지 못했어요. "
                       "다른 요리 이름이나 재료로 물어봐 주시거나, 가지고 계신 레시피 원문을 알려주시면 필요한 재료를 계산해 드릴게요."),
            Block(type="chips", data={"mode": "message", "items": [
                {"label": f"{word} 상품 보기", "value": f"{word} 추천해줘"},
                {"label": f"{word} 보관법", "value": f"{word} 보관 어떻게 해?"}]})]



# ── 구매 + '먹는 법·같이 살 거' (공공 레시피 근거) ─────────────────
def eat_pairing_blocks(product: str, recipe: dict, want_eat: bool, want_pairing: bool) -> list[Block]:
    md = [f"**{product} 먹는 법·곁들임** ({recipe.get('source_name') or '공공 레시피 DB'} '{recipe['name']}' 기준)"]
    if want_eat and recipe.get("steps"):
        md += [f"- {n}) {st['text']}" for n, st in enumerate(recipe["steps"][:5], 1)]
    key = product.replace(" ", "")
    sides = [i["name"] for i in recipe.get("ingredients", [])
             if not _pantry(i["name"]) and key not in i["name"].replace(" ", "") and i["name"].replace(" ", "") not in key][:5]
    blocks = []
    if sides:
        md.append(f"함께 준비하면 좋은 재료: {', '.join(sides)}")
    blocks.append(text_block("\n".join(md)))
    chips = [{"label": f"{n} 사러 가기", "value": f"{n} 추천해줘"} for n in (sides if want_pairing else [])[:4]]
    chips.append({"label": f"{recipe['name']} 레시피 전체", "value": f"{recipe['name']} 레시피 보기"})
    blocks.append(Block(type="chips", data={"mode": "message", "items": chips}))
    return blocks
