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
