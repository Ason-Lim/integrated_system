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
