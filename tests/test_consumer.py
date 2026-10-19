from fastapi.testclient import TestClient

from consumer.app import app

c = TestClient(app)


def types(r):
    return [b["type"] for b in r["blocks"]]


def test_recommend_first_then_ask():
    r = c.post("/api/chat", json={"message": "두바이 쫀득쿠키 추천해줘"}).json()
    assert types(r)[:2] == ["text", "product_list"]
    assert "clarify_form" in types(r)  # 질문은 추천 뒤에


def test_form_answer_refines():
    r = c.post("/api/chat", json={"message": "두바이 쫀득쿠키"}).json()
    r2 = c.post("/api/chat", json={"session_id": r["session_id"], "answers": {"budget": "10000-20000"}}).json()
    items = next(b for b in r2["blocks"] if b["type"] == "product_list")["data"]["items"]
    assert all(10000 <= (i["total"] or i["price"]) <= 20000 for i in items)


def test_no_product_asks():
    r = c.post("/api/chat", json={"message": "선물 추천해줘"}).json()
    assert r["stage"] == "clarify"


def test_click_redirect_only_to_known_items():
    assert c.get("/go/nope/1", follow_redirects=False).headers["location"] == "/"


def test_ledger_recorded_on_recommend():
    r = c.post("/api/chat", json={"message": "두바이 쫀득쿠키 추천해줘"}).json()
    assert r["ledger"] is not None
    assert r["ledger"]["decision_time"] and r["ledger"]["revision_deadline"]
    assert "price" in r["ledger"]["watch_conditions"]
    led = c.get(f"/api/decision/ledger/{r['session_id']}").json()
    assert led["ledger"]["snapshot_keys"]


def test_not_rankable_separated_from_ranking():
    from shared.assurance import decision_sufficiency
    from shared.models import Offer
    o = Offer(mall="sample", title="사과", price=10000, shipping_fee=3000)
    suff = decision_sufficiency(o)
    assert suff["rankability"] != "DETERMINATE"
    assert "total_cost" in suff["missing"]


def test_card_carries_ledger_fields():
    r = c.post("/api/chat", json={"message": "두바이 쫀득쿠키 추천해줘"}).json()
    cards = []
    for b in r["blocks"]:
        if b["type"] == "product_list":
            cards.extend(b["data"]["items"])
        elif b["type"] == "comparison_pair":
            for p in b["data"]["pairs"]:
                cards.extend(p["cards"])
    assert cards
    first = cards[0]
    assert first["decision_time"] and first["evidence_time"] and first["revision_deadline"]
    assert "price" in first["watch_conditions"]
    assert first["refresh_needed"] is False


def test_safe_qe_drops_unsupported_expansion():
    from shared.query_expansion import filter_expansion
    # 상품 근거에 '홍로'가 없으면 확장어로 승격하지 않는다
    r = filter_expansion("맛있는 사과", ["고당도", "홍로"], "사과 5kg 특등급")
    assert "홍로" in r["dropped"]
    assert r["unsupported_rate"] > 0
    assert any(c["attribute"] == "cultivar" for c in r["attribute_conflicts"])
    # 근거에 있으면 유지
    r2 = filter_expansion("맛있는 사과", ["홍로"], "홍로 사과 5kg")
    assert r2["kept"] == ["홍로"] and not r2["dropped"]


def test_persona_unknown_without_evidence():
    from shared.persona import infer
    p = infer({"clicks": [], "searches": []})
    assert p.unknown == ["price", "quality", "trust"]
    assert p.slots() == {}
    assert p.audit()["unsupported_rate"] == 1.0


def test_persona_uses_behavior_evidence():
    from shared.persona import infer
    p = infer({"clicks": [{"rank": 4}, {"rank": 5}], "searches": []})
    assert p.claims["price"].value == "price"
    assert p.slots() == {"price": "price"}
    assert "quality" in p.unknown


def test_ledger_detects_price_change():
    from datetime import timedelta
    from shared.decision_ledger import open_entry, refresh_needed
    from shared.models import Intent, Offer
    o = Offer(mall="sample", title="사과", price=10000, shipping_fee=3000)
    intent = Intent(action="recommend_food", slots={"product": "사과"})
    entry = open_entry(intent, [o])
    changed = o.model_copy(update={"price": 12000})
    rn = refresh_needed(entry, [changed])
    assert rn["needed"] is True
    assert any(c["reason"] == "price_changed" for c in rn["changed"])
    # 유효 기한 경과
    rn2 = refresh_needed(entry, [o], now=entry.revision_deadline + timedelta(hours=1))
    assert rn2["expired"] is True
